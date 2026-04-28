# logic/booker.py
import os
import time
import random
import base64
from datetime import datetime, timezone, timedelta, time as dt_time
from io import BytesIO

from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from core.logger import get_logger
from core import utils

logger = get_logger(__name__)


# ttshitu API 启用窗口（含起，不含止）
API_WINDOW_START = dt_time(6, 30, 0)
API_WINDOW_END = dt_time(6, 35, 0)


def _should_use_api():
    """
    是否应启用 ttshitu API。
    - main.FORCE_API_ALWAYS=True → 任何时段都用 API
    - 否则仅在 6:30:00-6:35:00 抢座窗口启用
    """
    try:
        import main as _main
        if getattr(_main, "FORCE_API_ALWAYS", False):
            return True
    except Exception:
        pass
    try:
        now_t = utils.get_beijing_time().time()
    except Exception:
        return False
    return API_WINDOW_START <= now_t < API_WINDOW_END


class SeatBooker:
    def __init__(self, driver, account: str = ""):
        self.driver = driver
        self.account = account or "unknown"
        self.wait = WebDriverWait(driver, 5)

    def _save_failure_screenshot(self, tag="failure"):
        """保存失败截图到 logs 目录，用于事后分析（文件名含账号防止双账号互相覆盖）"""
        try:
            log_dir = getattr(__import__("config"), "LOG_DIR", "logs")
            os.makedirs(log_dir, exist_ok=True)
            now = datetime.now(timezone(timedelta(hours=8)))
            filename = f"screenshot_{self.account}_{tag}_{now.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(log_dir, filename)
            self.driver.save_screenshot(filepath)
            logger.info("📸 失败截图已保存: %s", filepath)
        except Exception:
            logger.warning("⚠️ 截图保存失败")

    def click_time_label(self, column_index, time_str, timeout=5):
        """
        辅助函数：点击时间标签 (增加超时参数)
        """
        try:
            # 尝试定位时间标签
            xpath = f'(//div[@class="times-roll"])[{column_index}]//label[contains(text(), "{time_str}")]'
            # 使用传入的 timeout
            label = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            label.click()
            return True
        except TimeoutException:
            return False
        except NoSuchElementException:
            # 如果元素结构发生变化，捕获并返回 False
            return False

    def select_time_and_wait(self, seat_num, start_time, end_time):
        """
        选好座位和时间，等待命令
        """
        # 兼容用户输入的 "001" 或 "01" 等前导零，统一抹平为 "1"，以匹配网页上的真实座号
        clean_seat_num = str(int(seat_num)) if str(seat_num).isdigit() else str(seat_num)

        logger.info("🔒 正在尝试锁定座位 %s (%s-%s)...", clean_seat_num, start_time, end_time)
        try:
            # 1. 点击座位 (精确匹配，杜绝 3 匹配到 138 的 Bug)
            xpath = f'//div[contains(@class, "seat-name") and normalize-space(text())="{clean_seat_num}"]'
            try:
                seat_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", seat_elem)
                seat_elem.click()
            except Exception:
                logger.warning("⚠️ 座位 %s 找不到或不可点击，跳过", seat_num)
                return False

            # 2. 动态轮询等待弹窗出现，同时监听可能弹出的错误提示(如"约满"、"没有可约时间")
            start_wait = time.time()
            popup_found = False
            while time.time() - start_wait < 5:
                # a) 检查是否有报错 Toast
                error_msgs = self.driver.find_elements(By.CLASS_NAME, "el-message__content")
                if error_msgs:
                    msg = error_msgs[-1].text.strip()
                    if msg and ("没有可约时间" in msg or "约满" in msg or "不可" in msg or "已经被" in msg):
                        logger.warning("⚠️ 座位 %s 被拒:【%s】，立即跳过该座位", seat_num, msg)
                        return False
                
                # b) 检查预约弹窗是否已经成功弹出
                if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                    popup_found = True
                    break
                    
                time.sleep(0.3)

            if not popup_found:
                logger.warning("⚠️ 座位 %s 点击后未弹出预约框且无提示，跳过", seat_num)
                return False

            # 3. 选择开始时间 (Column 1)
            if not self.click_time_label(1, start_time):
                logger.warning("⚠️ 座位 %s 的开始时间 %s 不可选 (被占或未开放)", seat_num, start_time)
                self.close_popup()
                return False

            # 🔴 【核心修改】增加强制等待，确保右侧时间轴渲染出来
            time.sleep(0.5)

            # 4. 选择结束时间 (Column 2)
            # 增加 Timeout 到 3 秒，防止找不到元素
            if not self.click_time_label(2, end_time, timeout=3):
                logger.warning("⚠️ 座位 %s 的结束时间 %s 不可选，或元素未渲染", seat_num, end_time)
                self.close_popup()
                return False

            logger.info("✅ %s (%s-%s) 锁定成功！等待开火...", seat_num, start_time, end_time)
            return True

        except Exception as e:
            # 捕获所有选座异常
            logger.error("❌ 选座异常 %s: %s", seat_num, e)
            self.close_popup()
            return False

    def get_available_seats(self):
        """
        获取当前自习室页面上所有座位编号。
        返回座位编号字符串列表。
        """
        try:
            seat_elems = self.driver.find_elements(By.CSS_SELECTOR, "div.seat-name")
            seats = []
            for el in seat_elems:
                name = el.text.strip()
                if name:
                    seats.append(name)
            logger.info("🪑 当前页面共找到 %d 个座位", len(seats))
            return seats
        except Exception as e:
            logger.warning("⚠️ 获取座位列表失败: %s", e)
            return []

    def select_random_available(self, start_time, end_time, stop_event=None, exclude_seats=None):
        """
        从当前自习室随机选一个可用座位（排除已尝试失败的）。
        成功返回座位号，失败返回 None。
        """
        exclude = set(exclude_seats or [])
        all_seats = self.get_available_seats()
        candidates = [s for s in all_seats if s not in exclude]

        if not candidates:
            logger.info("💔 没有可尝试的候选座位了（全部已排除或无座位）")
            return None

        random.shuffle(candidates)
        logger.info("🎲 随机回退：将尝试 %d 个候选座位", len(candidates))

        for seat in candidates:
            if stop_event and stop_event.is_set():
                break
            if self.select_time_and_wait(seat, start_time, end_time):
                return seat

        return None

    def fire_submit(self):
        """
        开火！点击提交按钮，处理验证码，再次点击提交完成预约。
        流程：立即预约 → 验证码弹窗 → 点字+确定 → 再点立即预约
        """
        try:
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, ".el-button.submit-btn")
            submit_btn.click()
        except Exception as e:
            logger.error("❌ 提交失败: %s", e)
            return False

        # 处理点选验证码（如果出现）
        if not self._handle_click_captcha():
            return False

        # 验证码通过后，尝试再次点击「立即预约」
        # 有些情况下系统会自动提交，按钮已消失，两种都算成功
        try:
            time.sleep(0.5)
            submit_btn = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-button.submit-btn"))
            )
            submit_btn.click()
            logger.info("🚀 验证码通过，已再次点击立即预约！")
        except (TimeoutException, NoSuchElementException):
            logger.info("🚀 验证码通过，预约已自动提交。")
        return True

    # ------------------------------------------------------------------
    #  分阶段时序提交（验证码预加载策略）
    #  流程: 6:29:50 触发 → 预分析 → 6:29:58 点字 → 6:30:00 确定
    # ------------------------------------------------------------------

    def fire_submit_trigger(self):
        """
        时序提交 - 阶段1: 仅点击"立即预约"按钮，触发验证码弹窗。
        """
        try:
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, ".el-button.submit-btn")
            submit_btn.click()
            logger.info("🔥 已点击「立即预约」，等待验证码弹窗...")
            return True
        except Exception as e:
            logger.error("❌ 提交按钮点击失败: %s", e)
            return False

    def _grab_captcha_images(self):
        """提取目标文字图 + 背景大图的原始 bytes，以及背景元素。"""
        target_el = self.driver.find_element(
            By.CSS_SELECTOR, ".captcha-modal-click img.captcha-text"
        )
        target_src = target_el.get_attribute("src") or ""
        if "base64" not in target_src:
            return None, None, None
        target_bytes = base64.b64decode(target_src.split(",", 1)[1])

        bg_el = self.driver.find_element(
            By.CSS_SELECTOR, ".captcha-modal-content img"
        )
        bg_src = bg_el.get_attribute("src") or ""
        if "base64" not in bg_src:
            return None, None, None
        bg_bytes = base64.b64decode(bg_src.split(",", 1)[1])
        return target_bytes, bg_bytes, bg_el

    def _build_solve_data(self, click_points_in_bg, bg_el, bg_pil):
        """把"实际像素坐标"转换为相对于 bg 元素中心的 CSS 偏移量。"""
        display_w = bg_el.size["width"]
        display_h = bg_el.size["height"]
        actual_w, actual_h = bg_pil.size
        if actual_w <= 0 or actual_h <= 0 or display_w <= 0 or display_h <= 0:
            return None
        scale_x = display_w / actual_w
        scale_y = display_h / actual_h

        offsets = []
        for px, py in click_points_in_bg:
            offsets.append((px * scale_x - display_w / 2, py * scale_y - display_h / 2))
        return {
            "solved": True,
            "no_captcha": False,
            "click_offsets": offsets,
            "bg_el": bg_el,
        }

    def _solve_captcha_via_api(self, target_bytes, bg_bytes, bg_el):
        """图鉴 API 求解。返回 solve_data dict 或 None。"""
        from core.captcha_api import get_client
        client = get_client()
        if client is None:
            return None
        result = client.solve_click_captcha(target_bytes, bg_bytes)
        if not result.get("success"):
            logger.warning("⚠️ 图鉴 API 求解失败: %s", result.get("error"))
            return None
        bg_pil = result["bg_pil"]
        solve_data = self._build_solve_data(result["click_points_in_bg"], bg_el, bg_pil)
        if solve_data:
            api_id = result.get("id", "")
            solve_data["api_id"] = api_id
            logger.info(
                "✅ 图鉴 API 求解完成，%d 个点击点 | id=%s（如识别错可在 5 分钟内手动 reporterror）",
                len(solve_data["click_offsets"]),
                api_id,
            )
        return solve_data

    def _solve_captcha_locally(self, target_bytes, bg_bytes, bg_el):
        """本地 ddddocr 求解。返回 solve_data dict 或 None。"""
        from core.captcha import click_solver
        click_points = click_solver.solve(target_bytes, bg_bytes)
        if not click_points:
            return None
        bg_pil = Image.open(BytesIO(bg_bytes))
        solve_data = self._build_solve_data(click_points, bg_el, bg_pil)
        if solve_data:
            logger.info("✅ 本地 OCR 求解完成，%d 个点击点", len(solve_data["click_offsets"]))
        return solve_data

    def pre_solve_captcha(self, max_retries=10):
        """
        时序提交 - 阶段2: 预分析点选验证码。
        在 fire_at 之前完成 OCR 识别和坐标计算，为精确点击做准备。

        判定 6:30:00-6:35:00 启用图鉴 API；其他时段使用本地 ddddocr。

        Returns:
            dict: solved/no_captcha 标志 + 预计算的点击数据(click_offsets + bg_el)
        """
        # 等待验证码弹窗出现
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".captcha-modal-container"))
            )
        except TimeoutException:
            logger.info("ℹ️ 未检测到验证码弹窗")
            return {"solved": False, "no_captcha": True}

        use_api = _should_use_api()
        logger.info(
            "🔐 检测到点选验证码，开始预分析（识别引擎=%s）...",
            "ttshitu API" if use_api else "本地 ddddocr",
        )

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("🔄 预分析第 %d/%d 次...", attempt, max_retries)
                time.sleep(0.15)  # 等待图片渲染（base64内嵌,无需久等）

                target_bytes, bg_bytes, bg_el = self._grab_captcha_images()
                if target_bytes is None or bg_bytes is None:
                    logger.warning("⚠️ 验证码图片未加载，等待...")
                    time.sleep(1)
                    continue

                # 抢座窗口期内优先 API；失败时立即回退本地
                solve_data = None
                if use_api:
                    solve_data = self._solve_captcha_via_api(target_bytes, bg_bytes, bg_el)
                if solve_data is None:
                    solve_data = self._solve_captcha_locally(target_bytes, bg_bytes, bg_el)

                if not solve_data:
                    logger.warning("⚠️ 验证码求解失败，刷新重试...")
                    self._refresh_click_captcha()
                    continue

                logger.info("✅ 验证码预分析完成！%d 个点击目标", len(solve_data["click_offsets"]))
                return solve_data

            except Exception as e:
                logger.warning("⚠️ 预分析异常: %s", e)
                if attempt < max_retries:
                    self._refresh_click_captcha()

        logger.error("❌ 验证码预分析 %d 次均失败", max_retries)
        self._save_failure_screenshot("pre_solve_failed")
        return {"solved": False, "no_captcha": False}

    def _report_api_error_safe(self, api_id):
        """识别错了 → 调图鉴 reporterror 接口退费（5 分钟内有效）。"""
        if not api_id:
            return
        try:
            from core.captcha_api import get_client
            client = get_client()
            if client and client.report_error(api_id):
                logger.info("💰 已向图鉴上报识别错误 id=%s（5 分钟内退还次数）", api_id)
        except Exception as e:
            logger.warning("⚠️ 上报识别错误失败: %s", e)

    def _save_captcha_attempt_screenshot(self, tag="after_clicks"):
        """
        点完验证码、点确定之前 → 截一张全屏图，方便日后排查识别准确率。
        命名: logs/captcha_<tag>_<YYYYMMDD_HHMMSS_fff>.png
        """
        try:
            log_dir = getattr(__import__("config"), "LOG_DIR", "logs")
            sub_dir = os.path.join(log_dir, "captcha_attempts")
            os.makedirs(sub_dir, exist_ok=True)
            now = datetime.now(timezone(timedelta(hours=8)))
            stamp = now.strftime("%Y%m%d_%H%M%S_") + f"{now.microsecond // 1000:03d}"
            filename = f"captcha_{self.account}_{tag}_{stamp}.png"
            filepath = os.path.join(sub_dir, filename)
            self.driver.save_screenshot(filepath)
            logger.info("📸 验证码点击后留档: %s", filepath)
            return filepath
        except Exception as e:
            logger.warning("⚠️ 验证码截图失败: %s", e)
            return None

    def execute_captcha_clicks(self, solve_data):
        """
        时序提交 - 阶段3a: 按预计算坐标点击验证码文字。
        点击全部坐标后，会立刻截一张图（用于事后排查）。
        """
        if not solve_data or not solve_data.get("solved"):
            return False

        bg_el = solve_data["bg_el"]
        offsets = solve_data.get("click_offsets") or []
        if not offsets:
            return False

        for offset_x, offset_y in offsets:
            ActionChains(self.driver).move_to_element_with_offset(
                bg_el, offset_x, offset_y
            ).click().perform()
            time.sleep(0.15)

        logger.info("✅ 验证码文字已全部点击 (%d 个点)", len(offsets))

        # 点击完成、确认按钮按下之前，截图留档（不阻塞主流程）
        try:
            self._save_captcha_attempt_screenshot(tag="before_confirm")
        except Exception:
            pass

        return True

    def execute_clicks_fast(self, solve_data):
        """
        ⚡ 极速点击验证码文字：一次 ActionChain 批量完成，无额外等待。
        专用于三阶段精准时序（:59 点文字 → :00 点确定）。
        """
        if not solve_data or not solve_data.get("solved"):
            return False
        bg_el = solve_data["bg_el"]
        offsets = solve_data.get("click_offsets") or []
        if not offsets:
            return False
        try:
            chain = ActionChains(self.driver)
            for ox, oy in offsets:
                chain.move_to_element_with_offset(bg_el, ox, oy).click()
            chain.perform()
            logger.info("⚡ 验证码文字极速点击完成 (%d 个点)", len(offsets))
            return True
        except Exception as e:
            logger.error("❌ 极速点击失败: %s", e)
            return False

    def fire_captcha_blitz(self, solve_data):
        """
        ⚡ 闪电模式：一次 ActionChain 批量点击所有验证码文字 + 立即 JS 点确定。
        整个操作只有 2 次 IPC 调用（1次perform + 1次execute_script），< 50ms 完成。
        消除了旧流程中"点完文字等几秒再点确定"导致服务器刷新验证码的致命问题。
        """
        if not solve_data or not solve_data.get("solved"):
            return False

        bg_el = solve_data["bg_el"]
        offsets = solve_data.get("click_offsets") or []
        if not offsets:
            return False

        try:
            # 1) 一次 ActionChain 批量点击所有文字坐标（1次IPC）
            chain = ActionChains(self.driver)
            for ox, oy in offsets:
                chain.move_to_element_with_offset(bg_el, ox, oy).click()
            chain.perform()

            # 2) 立即 JS 点击确定按钮（1次IPC，比 Selenium click 快 30-80ms）
            self.driver.execute_script(
                "var btn = document.querySelector('.captcha-modal-footer .confirm-btn');"
                "if(btn) btn.click();"
            )
            logger.info("⚡ 闪电提交：%d个文字+确定 一气呵成！", len(offsets))

            # 3) 检查验证码是否通过（弹窗消失）
            try:
                WebDriverWait(self.driver, 12).until(
                    EC.invisibility_of_element_located(
                        (By.CSS_SELECTOR, ".captcha-modal-container")
                    )
                )
                logger.info("✅ 验证码确认通过！")
            except TimeoutException:
                logger.warning("⚠️ 验证码可能未通过（弹窗未消失）")
                self._save_failure_screenshot("captcha_confirm_timeout")
                return False

            # 4) 尝试再次点击「立即预约」（部分场景需要二次确认）
            try:
                submit_btn = WebDriverWait(self.driver, 1).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-button.submit-btn"))
                )
                submit_btn.click()
                logger.info("🚀 已再次点击「立即预约」")
            except (TimeoutException, NoSuchElementException):
                logger.info("🚀 预约已自动提交")

            return True

        except Exception as e:
            logger.error("❌ 闪电提交失败: %s", e)
            return False

    def click_captcha_confirm(self):
        """
        时序提交 - 阶段3b: 点击验证码"确定"按钮，完成预约。
        改用 JS click,绕过 Selenium wire protocol 的 IPC 开销 (省 30-80ms)。
        """
        try:
            # 走 JS 直接触发 click 事件,比 element.click() 快几十毫秒
            clicked = self.driver.execute_script(
                "var btn = document.querySelector('.captcha-modal-footer .confirm-btn');"
                "if (btn) { btn.click(); return true; } else { return false; }"
            )
            if not clicked:
                # JS 找不到按钮 → 兜底回退 Selenium 找元素
                confirm_btn = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-footer .confirm-btn"
                )
                confirm_btn.click()
            logger.info("🚀 已点击验证码「确定」！")

            # 等待验证码弹窗消失 → 验证通过
            try:
                WebDriverWait(self.driver, 12).until(
                    EC.invisibility_of_element_located(
                        (By.CSS_SELECTOR, ".captcha-modal-container")
                    )
                )
                logger.info("✅ 验证码确认通过！")
            except TimeoutException:
                logger.warning("⚠️ 验证码可能未通过（弹窗未消失）")
                self._save_failure_screenshot("captcha_confirm_timeout")
                return False

            # 尝试再次点击「立即预约」（部分场景需要二次确认）
            try:
                time.sleep(0.2)
                submit_btn = WebDriverWait(self.driver, 1).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-button.submit-btn"))
                )
                submit_btn.click()
                logger.info("🚀 已再次点击「立即预约」")
            except (TimeoutException, NoSuchElementException):
                logger.info("🚀 预约已自动提交")

            return True

        except Exception as e:
            logger.error("❌ 点击确定按钮失败: %s", e)
            return False

    # ------------------------------------------------------------------
    #  点选验证码处理
    # ------------------------------------------------------------------

    def _handle_click_captcha(self, max_retries=10):
        """
        检测并处理预约提交后弹出的点选文字验证码。
        如果没有弹出验证码则直接返回 True。

        判定 6:30:00-6:35:00 启用图鉴 API；其他时段使用本地 ddddocr。
        """
        # 检测验证码弹窗是否出现
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".captcha-modal-container"))
            )
        except TimeoutException:
            return True

        use_api = _should_use_api()
        logger.info(
            "🔐 检测到点选验证码！识别引擎=%s",
            "ttshitu API" if use_api else "本地 ddddocr",
        )

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("🔄 验证码第 %d/%d 次尝试...", attempt, max_retries)
                time.sleep(0.4)

                target_bytes, bg_bytes, bg_el = self._grab_captcha_images()
                if target_bytes is None or bg_bytes is None:
                    logger.warning("⚠️ 验证码图片未加载，等待...")
                    time.sleep(1)
                    continue

                solve_data = None
                if use_api:
                    solve_data = self._solve_captcha_via_api(target_bytes, bg_bytes, bg_el)
                if solve_data is None:
                    solve_data = self._solve_captcha_locally(target_bytes, bg_bytes, bg_el)

                if not solve_data:
                    logger.warning("⚠️ 验证码求解失败，刷新重试...")
                    self._refresh_click_captcha()
                    continue

                if not self.execute_captcha_clicks(solve_data):
                    self._refresh_click_captcha()
                    continue

                # 点击「确定」
                time.sleep(0.4)
                confirm_btn = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-footer .confirm-btn"
                )
                confirm_btn.click()

                # 等待弹窗消失 → 验证通过
                try:
                    WebDriverWait(self.driver, 3).until(
                        EC.invisibility_of_element_located(
                            (By.CSS_SELECTOR, ".captcha-modal-container")
                        )
                    )
                    logger.info("✅ 点选验证码通过！")
                    return True
                except TimeoutException:
                    logger.warning("⚠️ 验证码未通过，刷新重试...")
                    # API 识别错了 → 上报退费
                    self._report_api_error_safe(solve_data.get("api_id"))
                    self._refresh_click_captcha()
                    continue

            except Exception as e:
                logger.warning("⚠️ 验证码处理异常: %s", e)
                if attempt < max_retries:
                    self._refresh_click_captcha()

        logger.error("❌ 点选验证码 %d 次尝试均失败", max_retries)
        self._save_failure_screenshot("captcha_failed")
        return False

    def _refresh_click_captcha(self):
        """点击刷新图标获取新验证码"""
        try:
            refresh_btn = self.driver.find_element(
                By.CSS_SELECTOR, ".captcha-modal-title img.refresh"
            )
            refresh_btn.click()
            time.sleep(0.3)  # base64内嵌图片,0.3s足够渲染
        except Exception:
            logger.warning("⚠️ 刷新验证码按钮点击失败")

    def check_result(self):
        """检查结果（抢座窗口期 3s 即超时,加快失败回退）"""
        try:
            # 抢座窗口期 5s 太慢,缩到 3s,失败弹窗一闪即逝时也能尽早进入下一优先级
            res_element = WebDriverWait(self.driver, 3).until(EC.any_of(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约成功')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '有效预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '已有预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约失败')]"))
            ))

            result_text = res_element.text
            logger.info("📝 结果反馈: %s", result_text)

            # 如果是成功提示，关闭弹窗
            if "预约成功" in result_text or "有效预约" in result_text:
                self.close_popup()
                return True
            # 如果是失败提示，也需要关闭弹窗并返回失败
            elif "已有预约" in result_text or "预约失败" in result_text:
                self._save_failure_screenshot("booking_failed")
                self.close_popup()
                return False  # 返回 False，触发重试/恢复逻辑

            self._save_failure_screenshot("unknown_result")
            return False  # 默认失败
        except Exception:
            self._save_failure_screenshot("check_timeout")
            return False

    def close_popup(self):
        """
        关闭座位预约弹窗。多 selector 兜底:
          1) .reserve-box 内部的 i.el-icon-close
          2) 通用 .close-icon (本站另一处弹窗叉号 class)
          3) .el-dialog__headerbtn (Element UI 默认对话框关闭键)
          4) 任意 [class*='close']
          5) 全部失败 → 按 ESC
        判定弹窗消失即视为成功,不再卡 2 秒等待。
        """
        from selenium.webdriver.common.keys import Keys

        logger.info("❌ 正在尝试关闭预约弹窗...")
        candidates = [
            (By.CSS_SELECTOR, ".reserve-box .el-icon-close"),
            (By.CSS_SELECTOR, ".reserve-box .close-icon"),
            (By.CSS_SELECTOR, ".reserve-box .el-dialog__headerbtn"),
            (By.CSS_SELECTOR, ".reserve-box [class*='close']"),
            (By.CSS_SELECTOR, ".close-icon"),
            (By.CSS_SELECTOR, ".el-dialog__headerbtn"),
        ]
        for by, sel in candidates:
            try:
                els = self.driver.find_elements(by, sel)
                for el in els:
                    if not el.is_displayed():
                        continue
                    try:
                        el.click()
                    except Exception:
                        # 兜底用 JS 点击,避免被遮挡
                        self.driver.execute_script("arguments[0].click();", el)
                    # 简短确认弹窗消失
                    try:
                        WebDriverWait(self.driver, 1).until(
                            EC.invisibility_of_element_located((By.CLASS_NAME, "reserve-box"))
                        )
                    except TimeoutException:
                        pass
                    if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                        logger.info("✅ 预约弹窗已关闭 (selector=%s)", sel)
                        return True
            except Exception:
                continue

        # 兜底: ESC 键
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
            if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                logger.info("✅ 预约弹窗已通过 ESC 关闭。")
                return True
        except Exception:
            pass

        # 弹窗已经不在 DOM 里也算成功
        if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
            return True

        logger.warning("⚠️ 预约弹窗未能关闭,可能影响下一优先级选座。")
        return False