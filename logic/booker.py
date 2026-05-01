# logic/booker.py
import os
import time
import random
import base64
import logging
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

_logger = get_logger(__name__)


class _AccountLoggerAdapter(logging.LoggerAdapter):
    """自动给每条日志加 [account] 前缀（供 SeatBooker 内部统一打 tag）。"""
    def process(self, msg, kwargs):
        tag = f"[{self.extra.get('account', 'unknown')}]"
        s = str(msg)
        # 已含相同 tag 的句子；或调用方已用 [%s] 占位（args 里会注入 account）→ 都跳过，避免重复 tag
        if tag in s or "[%s]" in s:
            return msg, kwargs
        return f"{tag} {msg}", kwargs


# ttshitu API 启用窗口（含起止）
API_WINDOW_START = dt_time(6, 30, 0)
API_WINDOW_END = dt_time(6, 35, 0)
CAPTCHA_FAST_FAIL_KEYWORDS = (
    "验证码错误",
    "请重试",
    "系统繁忙",
    "请稍后",
    "操作过于频繁",
    "提交失败",
)


def _should_use_api():
    """
    是否应启用 ttshitu API。
    - config.FORCE_API_ALWAYS=True → 任何时段都用 API
    - 否则仅在 6:30:00-6:35:00 抢座窗口启用
    """
    try:
        import config as _cfg
        if getattr(_cfg, "FORCE_API_ALWAYS", False):
            return True
    except Exception as e:
        _logger.warning("⚠️ 读取 FORCE_API_ALWAYS 失败: %s，回退时间窗口判断", e)
    try:
        now_t = utils.get_beijing_time().time()
    except Exception:
        return False
    return API_WINDOW_START <= now_t <= API_WINDOW_END


class SeatBooker:
    def __init__(self, driver, account: str = ""):
        self.driver = driver
        self.account = account or "unknown"
        self.wait = WebDriverWait(driver, 5)
        # 最近一次 select_time_and_wait 失败的原因（供外层日志冒泡）
        self.last_lock_failure_reason = ""
        # 账号专属日志适配器：所有日志自动带上 [account] 前缀，供按账号拆分日志路由使用
        self.log = _AccountLoggerAdapter(_logger, {"account": self.account})

    def get_captcha_max_retries(self) -> int:
        """API 每个座位最多 5 次重试，本地 OCR 最多 10 次"""
        return 5 if _should_use_api() else 10

    def has_active_reservation(self) -> bool:
        """检查当前账号是否有活跃的预约（已预约 或 履约中），或当天已达3次预约上限"""
        try:
            self.log.info("🔍 [%s] 正在检查是否有已有预约...", self.account)
            # 1. 找到"我的预约"按钮并点击
            try:
                my_res_btn = WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '我的预约')]"))
                )
                self.driver.execute_script("arguments[0].click();", my_res_btn)
            except Exception as e:
                self.log.warning("⚠️ [%s] 未找到'我的预约'按钮，跳过检查。(%s)", self.account, e)
                return False

            # 2. 给予充足的时间等待前端拉取并渲染预约列表
            time.sleep(2.0)

            # 确保表格头部确实可见（如果还是没可见，可能点击失败了，再尝试找一次点一下）
            try:
                WebDriverWait(self.driver, 3).until(
                    EC.visibility_of_element_located((By.XPATH, "//th[contains(text(), '状态')]"))
                )
            except Exception:
                # 补点一次
                try:
                    btns = self.driver.find_elements(By.XPATH, "//*[contains(text(), '我的预约')]")
                    for btn in btns:
                        self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(2.0)
                except Exception:
                    pass

            # 3. 轮询检查是否有活跃状态（因为网络可能慢）
            active_elements = []
            for _ in range(4):
                # 使用 contains(., '...') 而不是 text()，以支持嵌套标签（如 <td><div class="cell">已预约</div></td>）
                active_elements = self.driver.find_elements(By.XPATH, "//td[contains(., '已预约') or contains(., '履约中')]")
                # 作为补充备用方案，也可直接扫描整个页面的纯文本
                if not active_elements:
                    if "已预约" in self.driver.page_source or "履约中" in self.driver.page_source:
                        active_elements = [True] # 只要有就行

                if active_elements:
                    break
                time.sleep(0.5)

            if len(active_elements) > 0:
                self.log.warning("🛑 [%s] 检测到账号已有【已预约】或【履约中】的座位，停止抢座！", self.account)
                return True

            self.log.info("✅ [%s] 无活跃预约。", self.account)

            # 4. 统计当天预约记录数（每人每天上限3次）
            today_count = self.count_today_reservations()
            if today_count >= 3:
                self.log.warning("🛑 [%s] 当天已有 %d 条预约记录（上限3次），停止抢座！", self.account, today_count)
                try:
                    back_btn = self.driver.find_element(By.XPATH, "//*[contains(text(), '自选座位')]")
                    self.driver.execute_script("arguments[0].click();", back_btn)
                    time.sleep(1.0)
                except Exception:
                    pass
                return True

            self.log.info("✅ [%s] 当天记录数 %d/3，继续流程。", self.account, today_count)

            # 5. 切回"自选座位"
            try:
                back_btn = self.driver.find_element(By.XPATH, "//*[contains(text(), '自选座位')]")
                self.driver.execute_script("arguments[0].click();", back_btn)
                time.sleep(1.0)
            except Exception:
                pass
            return False

        except Exception as e:
            self.log.warning("⚠️ [%s] 检查已有预约时发生异常，默认判定为无预约: %s", self.account, e)
            try:
                back_btn = self.driver.find_element(By.XPATH, "//*[contains(text(), '自选座位')]")
                self.driver.execute_script("arguments[0].click();", back_btn)
            except Exception:
                pass
            return False

    def count_today_reservations(self) -> int:
        """统计当天预约记录总数（无论状态：已预约/履约中/已取消 都算）"""
        try:
            beijing_now = datetime.now(timezone(timedelta(hours=8)))
            today_str = f"{beijing_now.year}-{beijing_now.month}-{beijing_now.day}"
            date_elements = self.driver.find_elements(By.XPATH, f"//td[contains(text(), '{today_str}')]")
            count = len(date_elements)
            self.log.info("📊 [%s] 当天(%s)共有 %d 条预约记录", self.account, today_str, count)
            return count
        except Exception as e:
            self.log.warning("⚠️ [%s] 统计当天预约记录失败: %s", e)
            return 0

    def _save_screenshot(self, tag="step"):
        """保存截图到会话文件夹（若有）或 logs 目录"""
        try:
            log_dir = getattr(self, "session_dir", None) or getattr(__import__("config"), "LOG_DIR", "logs")
            os.makedirs(log_dir, exist_ok=True)
            now = datetime.now(timezone(timedelta(hours=8)))
            seat = getattr(self, "current_seat", "unknown")
            retry = getattr(self, "current_retry", 0)
            prio = getattr(self, "current_priority", 0)
            filename = f"{prio}_{seat}_{retry}_{tag}_{now.strftime('%Y%m%d_%H%M%S')}.png"
            filepath = os.path.join(log_dir, filename)
            self.driver.save_screenshot(filepath)
            self.log.info("📸 [%s] 截图: %s", self.account, os.path.relpath(filepath))
            return filepath
        except Exception:
            self.log.warning("⚠️ [%s] 截图保存失败", self.account)
            return None

    def click_time_label(self, column_index, time_str, timeout=5):
        """
        辅助函数：点击时间标签 (增加超时参数)，使用精确匹配避免 9:00 匹配到 19:00
        """
        try:
            # 格式化时间，处理前导零
            parts = time_str.split(':')
            if len(parts) == 2:
                time_padded = f"{int(parts[0]):02d}:{parts[1]}"
                time_unpadded = f"{int(parts[0])}:{parts[1]}"
            else:
                time_padded = time_str
                time_unpadded = time_str

            # 使用精确匹配，同时兼容带前导零和不带前导零的显示格式
            xpath = f'(//div[@class="times-roll"])[{column_index}]//label[normalize-space(text())="{time_padded}" or normalize-space(text())="{time_unpadded}"]'
            # 使用传入的 timeout
            label = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
            label.click()
            return True
        except TimeoutException:
            return False
        except NoSuchElementException:
            # 如果元素结构发生变化，捕获并返回 False
            return False

    def _get_latest_ui_message(self):
        """读取页面上最近的一条提示文本（toast / message-box / notification）。"""
        selectors = [
            (By.CLASS_NAME, "el-message__content"),
            (By.CLASS_NAME, "el-message-box__message"),
            (By.CSS_SELECTOR, ".el-message .el-message__content"),
            (By.CSS_SELECTOR, ".el-message--error .el-message__content"),
            (By.CSS_SELECTOR, ".el-message--warning .el-message__content"),
            (By.CSS_SELECTOR, ".el-notification__content"),
            (By.CSS_SELECTOR, ".el-alert__content"),
            (By.CSS_SELECTOR, "[class*='message']"),
            (By.CSS_SELECTOR, "[class*='toast']"),
        ]
        for by, selector in selectors:
            try:
                elements = self.driver.find_elements(by, selector)
            except Exception:
                continue
            for el in reversed(elements):
                try:
                    msg = (el.text or "").strip()
                except Exception:
                    continue
                if msg:
                    return msg
        # 兜底：直接扫页面文本中的关键失败提示
        page = self.driver.page_source or ""
        for kw in ("没有可用时间", "没有可约时间", "约满", "不可预约", "当前不可用"):
            if kw in page:
                return kw
        return ""

    def _wait_captcha_result(self, timeout=3.2, poll_interval=0.06):
        """
        等待验证码提交反馈：
        - 弹窗消失 => 通过
        - 出现系统失败提示（验证码错误/系统繁忙等）=> 立即失败，避免傻等超时
        """
        start_wait = time.time()
        last_msg = ""
        while time.time() - start_wait < timeout:
            if not self.driver.find_elements(By.CSS_SELECTOR, ".captcha-modal-container"):
                return True, ""

            # 闪电检测：扫 page_source 中的失败关键词（比等 UI 元素渲染更快）
            ps = self.driver.page_source or ""
            for kw in CAPTCHA_FAST_FAIL_KEYWORDS:
                if kw in ps:
                    self.log.warning("⚡ [%s] 闪电检测到失败关键词: %s", self.account, kw)
                    return False, kw

            msg = self._get_latest_ui_message()
            if msg:
                last_msg = msg
                if any(keyword in msg for keyword in CAPTCHA_FAST_FAIL_KEYWORDS):
                    return False, msg

            time.sleep(poll_interval)

        return False, last_msg

    def select_time_and_wait(self, seat_num, start_time, end_time):
        """
        选好座位和时间，等待命令
        """
        # 兼容用户输入的 "001" 或 "01" 等前导零，统一抹平为 "1"，以匹配网页上的真实座号
        clean_seat_num = str(int(seat_num)) if str(seat_num).isdigit() else str(seat_num)
        # 重置失败原因
        self.last_lock_failure_reason = ""

        self.log.info("🔒 [%s] 正在尝试锁定座位 %s (%s-%s)...", self.account, clean_seat_num, start_time, end_time)
        try:
            # 0. 彻底清理所有可能遮挡的弹窗（验证码弹窗、预约窗、消息框等）
            self._cleanup_all_popups()

            # 1. 点击座位 (精确匹配，杜绝 3 匹配到 138 的 Bug)
            xpath = f'//div[contains(@class, "seat-name") and normalize-space(text())="{clean_seat_num}"]'
            try:
                seat_elem = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", seat_elem)
                try:
                    seat_elem.click()
                except Exception as click_err:
                    # 区分两种情况：被弹窗/遮罩拦截 vs 元素消失。前者用 JS 强点重试一次。
                    err_name = type(click_err).__name__
                    if "Intercept" in err_name:
                        self.log.debug("⚠️ [%s] 座位 %s 点击被拦截（%s），自动关闭遮挡后重试。",
                                       self.account, seat_num, err_name)
                        self.close_popup()
                        time.sleep(0.1)
                        # JS 强点（绕过遮罩判断），失败再算"找不到/不可点击"
                        self.driver.execute_script("arguments[0].click();", seat_elem)
                    else:
                        raise
            except Exception:
                self.last_lock_failure_reason = f"座位 {seat_num} 在当前自习室找不到或不可点击"
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
                return False

            # 2. 闪电检测：先查 page_source 看有没有失败提示（比等 UI 元素快）
            page_fail_kw = ("没有可用时间", "没有可约时间", "约满", "不可预约", "当前不可用",
                            "无法预约", "已满", "已被", "不可用", "没有可用")
            ps = self.driver.page_source or ""
            fast_fail_hit = next((kw for kw in page_fail_kw if kw in ps), None)
            if fast_fail_hit:
                self.last_lock_failure_reason = f"座位 {seat_num} 被系统拒绝：{fast_fail_hit}"
                self.log.warning("⚠️ [%s] %s，立即跳过该座位", self.account, self.last_lock_failure_reason)
                if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                    self.close_popup()
                return False

            fail_kw_list = (
                "没有可约时间", "没有可用时间", "约满", "不可预约", "当前不可用",
                "无法预约", "已满", "已被", "不可用", "没有可用",
            )
            # 3. 动态轮询等待弹窗出现，同时监听可能弹出的错误提示
            start_wait = time.time()
            popup_found = False
            last_toast_msg = ""
            while time.time() - start_wait < 3:
                # a) 检查是否有报错 Toast
                msg = self._get_latest_ui_message()
                if msg:
                    last_toast_msg = msg
                    hit_kw = next((kw for kw in fail_kw_list if kw in msg), None)
                    if hit_kw:
                        self.last_lock_failure_reason = f"座位 {seat_num} 被系统拒绝：{hit_kw}"
                        self.log.warning("⚠️ [%s] %s，立即跳过该座位", self.account, self.last_lock_failure_reason)
                        # ⚠️ 关键修复：toast 与 reserve-box 可能同时出现，必须把残留弹窗关掉
                        # 否则会拦住下一座位的点击 → 让本来存在的座位也"找不到/不可点击"
                        if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                            self.close_popup()
                        return False

                # b) 检查预约弹窗是否已经成功弹出
                if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                    popup_found = True
                    break

                time.sleep(0.1)

            if not popup_found:
                if last_toast_msg:
                    self.last_lock_failure_reason = f"座位 {seat_num} 点击后未弹出预约框，最后提示：{last_toast_msg}"
                else:
                    self.last_lock_failure_reason = f"座位 {seat_num} 点击后未弹出预约框且无任何提示"
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
                if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                    self.close_popup()
                return False

            # 4. 选择开始时间 (Column 1)
            # 缩短超时时间，实现"闪电失败" (fail-fast)，如果 1 秒内找不到就开始找下一个座位
            if not self.click_time_label(1, start_time, timeout=1.0):
                self.last_lock_failure_reason = (
                    f"座位 {seat_num} 的【开始时间 {start_time}】不存在/不可选"
                )
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
                self.close_popup()
                return False

            # 🔴 增加极短的强制等待，确保右侧时间轴渲染出来
            time.sleep(0.3)

            # 5. 选择结束时间 (Column 2)
            # 缩短超时时间到 1.0 秒，如果不可选立即失败
            if not self.click_time_label(2, end_time, timeout=1.0):
                self.last_lock_failure_reason = (
                    f"座位 {seat_num} 的【结束时间 {end_time}】不存在/不可选 "
                    f"（开始时间 {start_time} 已选，但结束时间被后续用户占用或超出可约范围）"
                )
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
                self.close_popup()
                return False

            self.log.info("✅ [%s] 座位 %s (%s-%s) 锁定成功！等待开火...", self.account, seat_num, start_time, end_time)
            return True

        except Exception as e:
            # 捕获所有选座异常
            self.last_lock_failure_reason = f"座位 {seat_num} 选座过程发生异常: {e}"
            self.log.error("❌ [%s] %s", self.account, self.last_lock_failure_reason)
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
            self.log.info("🪑 当前页面共找到 %d 个座位", len(seats))
            return seats
        except Exception as e:
            self.log.warning("⚠️ 获取座位列表失败: %s", e)
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
            self.log.info("💔 没有可尝试的候选座位了（全部已排除或无座位）")
            return None

        random.shuffle(candidates)
        self.log.info("🎲 随机回退：将尝试 %d 个候选座位", len(candidates))

        for seat in candidates:
            if stop_event and stop_event.is_set():
                break
            if self.select_time_and_wait(seat, start_time, end_time):
                return seat

        return None

    def fire_submit_trigger(self):
        """
        时序提交 - 阶段1: 仅点击"立即预约"按钮，触发验证码弹窗。
        """
        try:
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, ".el-button.submit-btn")
            submit_btn.click()
            self.log.info("🔥 已点击「立即预约」，等待验证码弹窗...")
            return True
        except Exception as e:
            self.log.error("❌ 提交按钮点击失败: %s", e)
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
        if actual_w <= 0 or actual_h <= 0:
            self.log.warning("⚠️ 验证码背景图尺寸异常 (%dx%d)，跳过", actual_w, actual_h)
            return None
        # 兜底：display 尺寸为 0 时用实际图片尺寸
        if display_w <= 0:
            display_w = actual_w
        if display_h <= 0:
            display_h = actual_h
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
            self.log.warning("⚠️ 图鉴 API 求解失败: %s", result.get("error"))
            return None
        bg_pil = result["bg_pil"]
        solve_data = self._build_solve_data(result["click_points_in_bg"], bg_el, bg_pil)
        if solve_data:
            api_id = result.get("id", "")
            solve_data["api_id"] = api_id
            self.log.info("✅ 图鉴 API 求解完成，%d个点击点 | id=%s", len(solve_data["click_offsets"]), api_id)
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
            self.log.info("✅ 本地 OCR 求解完成，%d 个点击点", len(solve_data["click_offsets"]))
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
            self.log.info("ℹ️ 未检测到验证码弹窗")
            return {"solved": False, "no_captcha": True}

        self._save_screenshot("1_captcha_popup")
        use_api = _should_use_api()
        self.log.info("🔐 检测到点选验证码，开始预分析（识别引擎=%s）...", "ttshitu API" if use_api else "本地 ddddocr")

        for attempt in range(1, max_retries + 1):
            try:
                self.log.info("🔄 预分析第 %d/%d 次...", attempt, max_retries)
                time.sleep(0.15)  # 等待图片渲染（base64内嵌,无需久等）

                target_bytes, bg_bytes, bg_el = self._grab_captcha_images()
                if target_bytes is None or bg_bytes is None:
                    self.log.warning("⚠️ 验证码图片未加载，等待...")
                    time.sleep(1)
                    continue

                # 抢座窗口期内优先 API；失败时立即回退本地
                solve_data = None
                if use_api:
                    solve_data = self._solve_captcha_via_api(target_bytes, bg_bytes, bg_el)
                if solve_data is None:
                    solve_data = self._solve_captcha_locally(target_bytes, bg_bytes, bg_el)

                if not solve_data:
                    self.log.warning("⚠️ 验证码求解失败，刷新重试...")
                    self._refresh_click_captcha()
                    continue

                self.log.info("✅ 验证码预分析完成！%d 个点击目标", len(solve_data["click_offsets"]))
                return solve_data

            except Exception as e:
                self.log.warning("⚠️ 预分析异常: %s", e)
                if attempt < max_retries:
                    self._refresh_click_captcha()

        self.log.error("❌ 验证码预分析 %d 次均失败", max_retries)
        self._save_screenshot("pre_solve_failed")
        return {"solved": False, "no_captcha": False}

    def _report_api_error_safe(self, api_id):
        """识别错了 → 调图鉴 reporterror 接口退费（5 分钟内有效）。"""
        if not api_id:
            return
        try:
            from core.captcha_api import get_client
            client = get_client()
            if client and client.report_error(api_id):
                self.log.info("💰 已向图鉴上报识别错误 id=%s（5 分钟内退还次数）", api_id)
        except Exception as e:
            self.log.warning("⚠️ 上报识别错误失败: %s", e)

    def fire_captcha_blitz(self, solve_data):
        """
        ⚡ 闪电模式：ActionChains 点字（真实鼠标事件）+ Selenium 点确认。
        关键：必须用 solve_data 里缓存的 bg_el 原件，不能重新抓！
        因为坐标偏移量是基于当时那个元素的尺寸算的，换一张图坐标就错了。
        """
        if not solve_data or not solve_data.get("solved"):
            return False

        offsets = solve_data.get("click_offsets") or []
        bg_el = solve_data.get("bg_el")
        if not offsets or not bg_el:
            return False

        try:
            # ActionChains 用缓存的原 bg_el 点击（偏移量与之匹配）
            chain = ActionChains(self.driver)
            for ox, oy in offsets:
                chain.move_to_element_with_offset(bg_el, ox, oy).click()
            chain.perform()

            self._save_screenshot("2_text_clicked")
            # 步骤2: 等待确认按钮出现（条件渲染：点击文字后 Vue 才把按钮插入 DOM）
            btn_exists = False
            btn_ready = False
            btn_diag = "missing"
            display_w = bg_el.size["width"]
            display_h = bg_el.size["height"]
            for i in range(60):  # 最多等 3 秒
                time.sleep(0.05)
                # 1.5 秒后按钮仍不存在 → JS 兜底：用精确坐标派发 MouseEvent 到图片上
                if i == 30 and not btn_exists:
                    self.log.info("⚡ [%s] ActionChains 未命中，JS 兜底补点...", self.account)
                    for ox, oy in offsets:
                        px_css = ox + display_w / 2  # center-relative → top-left CSS 坐标
                        py_css = oy + display_h / 2
                        self.driver.execute_script(
                            "var img = arguments[0];"
                            "var x=arguments[1], y=arguments[2];"
                            "var r = img.getBoundingClientRect();"
                            "img.dispatchEvent(new MouseEvent('click',{"
                            "  clientX:r.left+x, clientY:r.top+y,"
                            "  bubbles:true, cancelable:true, view:window"
                            "}));"
                            , bg_el, px_css, py_css)
                info = self.driver.execute_script(
                    "var footer = document.querySelector('.captcha-modal-footer');"
                    "if(!footer) return 'no_footer';"
                    "var btn = footer.querySelector('.el-button.confirm-btn');"
                    "if(!btn) return 'no_btn';"
                    "var style = window.getComputedStyle(btn);"
                    "return JSON.stringify({"
                    "  disabled: btn.disabled,"
                    "  ariaDisabled: btn.getAttribute('aria-disabled'),"
                    "  className: btn.className,"
                    "  pointerEvents: style.pointerEvents,"
                    "  cursor: style.cursor,"
                    "  opacity: style.opacity"
                    "});"
                )
                btn_diag = info
                if info in ("no_footer", "no_btn"):
                    continue  # 按钮还没渲染，继续等
                btn_exists = True
                import json as _json
                try:
                    d = _json.loads(info)
                except Exception:
                    d = {"raw": info}
                self.log.info("⚡ [%s] 确认按钮状态: disabled=%s, ptrEvt=%s, cursor=%s, class=%s",
                    self.account, d.get("disabled"), d.get("pointerEvents"), d.get("cursor"), d.get("className"))
                is_disabled = d.get("disabled") is True or "disabled" in d.get("className", "").lower()
                if not is_disabled and d.get("pointerEvents") != "none" and d.get("cursor") != "not-allowed":
                    btn_ready = True
                    break
            if not btn_exists:
                self.log.warning("⚡ [%s] 确认按钮始终未出现 (diag=%s)，文字点击可能未命中", self.account, btn_diag)

            # 步骤3: Selenium 点击确认
            btn_clicked = False
            if btn_ready:
                try:
                    confirm_btn = self.driver.find_element(By.CSS_SELECTOR, ".captcha-modal-footer .el-button.confirm-btn")
                    confirm_btn.click()
                    btn_clicked = True
                except Exception:
                    self.log.warning("⚡ [%s] Selenium 点确认失败", self.account)
            else:
                self.log.warning("⚡ [%s] 确认按钮未就绪: %s", self.account, btn_diag)

            self.log.info("⚡ 闪电提交：%d个文字+确定 (btn=%s)", len(offsets), "clicked" if btn_clicked else "not_clicked")
            if btn_clicked:
                self._save_screenshot("3_confirm_clicked")

            # 3) 闪电检测：提交后立即扫 page_source 看是否有"验证码错误"
            ps = self.driver.page_source or ""
            captcha_wrong = any(kw in ps for kw in ("验证码错误", "请重试"))
            if captcha_wrong:
                self.log.warning("⚡ [%s] 闪电检测到验证码错误，立即向图鉴报错！", self.account)
                self._report_api_error_safe(solve_data.get("api_id"))
                # 判断两种情况
                captcha_still_there = self.is_captcha_popup_present()
                reserve_still_there = bool(self.driver.find_elements(By.CLASS_NAME, "reserve-box"))
                if not captcha_still_there and not reserve_still_there:
                    self.log.warning("⚠️ [%s] 预约窗和验证码均已消失 → 需重新锁定座位", self.account)
                elif captcha_still_there:
                    self.log.info("🔄 [%s] 验证码已自动刷新 → 将重新求解并提交", self.account)
                return False

            # 4) 检查验证码是否通过（优先监听系统提示，避免无谓等待）
            captcha_ok, fail_msg = self._wait_captcha_result(timeout=2.0)
            if captcha_ok:
                self.log.info("✅ 验证码确认通过！")
            else:
                if fail_msg:
                    self.log.warning("⚠️ 验证码未通过: %s", fail_msg)
                    if "验证码错误" in fail_msg:
                        self._report_api_error_safe(solve_data.get("api_id"))
                else:
                    self.log.warning("⚠️ 验证码可能未通过（弹窗未消失）")
                    self._save_screenshot("captcha_confirm_timeout")
                return False

            # 5) 尝试再次点击「立即预约」（部分场景需要二次确认）
            try:
                submit_btn = WebDriverWait(self.driver, 1).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".el-button.submit-btn"))
                )
                submit_btn.click()
                self.log.info("🚀 已再次点击「立即预约」")
            except (TimeoutException, NoSuchElementException):
                self.log.info("🚀 预约已自动提交")

            return True

        except Exception as e:
            self.log.error("❌ 闪电提交失败: %s", e)
            return False

    def _close_captcha_modal(self):
        """点击验证码弹窗的取消按钮来关闭"""
        try:
            # 遍历弹窗底部所有元素，找到含"取消"文本的点击
            result = self.driver.execute_script(
                "var all = document.querySelectorAll('.captcha-modal-footer *');"
                "for (var i = 0; i < all.length; i++) {"
                "  if (all[i].textContent && all[i].textContent.indexOf('取消') >= 0 && all[i].textContent.length < 10) {"
                "    all[i].click(); return 'cancel';"
                "  }"
                "}"
                "return 'not_found';"
            )
            if result != "cancel":
                # JS 没找到，用 Selenium XPath 兜底
                try:
                    cancel_btn = self.driver.find_element(By.XPATH, "//*[contains(text(), '取消')]")
                    cancel_btn.click()
                except Exception:
                    pass
        except Exception:
            pass

    def _cleanup_all_popups(self):
        """彻底清理页面上所有可能遮挡座位的弹窗"""
        try:
            self._close_captcha_modal()
            if self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                self.close_popup()
            self.driver.execute_script(
                "document.querySelectorAll('.v-modal, .el-dialog__wrapper')"
                ".forEach(function(el) { el.style.display = ''; });"
            )
        except Exception:
            pass

    def is_captcha_popup_present(self):
        """判断验证码弹窗是否存在，并清理可能遮挡的系统原生或业务层报错弹窗"""
        try:
            btns = self.driver.find_elements(By.CSS_SELECTOR, ".el-message-box__btns button")
            for btn in btns:
                if btn.is_displayed():
                    btn.click()
                    time.sleep(0.1)
        except Exception:
            pass
        return len(self.driver.find_elements(By.CSS_SELECTOR, ".captcha-modal-container")) > 0

    def _refresh_click_captcha(self):
        """点击刷新图标获取新验证码，多选择器兜底"""
        for sel in (".captcha-modal-title img.refresh",
                    ".captcha-modal-title img[class*='refresh']",
                    ".captcha-modal-title img",
                    "//img[contains(@class, 'refresh')]"):
            try:
                if sel.startswith("//"):
                    btn = self.driver.find_element(By.XPATH, sel)
                else:
                    btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                btn.click()
                time.sleep(0.3)
                return
            except Exception:
                continue
        self.log.warning("⚠️ 刷新验证码按钮点击失败")

    def check_result(self):
        """
        检查提交结果。
        返回:
          - {"status":"success", ...}
          - {"status":"retry_captcha", ...}  # 验证码错误/系统繁忙，可继续当前座位重试
          - {"status":"failed", ...}
        """
        try:
            # 抢座窗口期 3s 超时,失败弹窗一闪即逝时也能尽早决策
            res_element = WebDriverWait(self.driver, 3).until(EC.any_of(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约成功')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '有效预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '已有预约')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '预约失败')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '验证码错误')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '系统繁忙')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '请稍后')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '请重试')]")),
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '操作过于频繁')]")),
            ))

            result_text = res_element.text
            self.log.info("📝 结果反馈: %s", result_text)

            # 如果是成功提示，关闭弹窗
            if "预约成功" in result_text or "有效预约" in result_text:
                self.close_popup()
                return {"status": "success", "text": result_text}

            # 这类失败通常可刷新验证码后继续当前座位尝试
            if (
                "验证码错误" in result_text
                or "系统繁忙" in result_text
                or "请稍后" in result_text
                or "请重试" in result_text
                or "操作过于频繁" in result_text
            ):
                return {
                    "status": "retry_captcha",
                    "text": result_text,
                    "report_api_error": ("验证码错误" in result_text),
                }

            # 其它失败提示：关闭弹窗并换下一个座位
            if "已有预约" in result_text or "预约失败" in result_text:
                self._save_screenshot("booking_failed")
                self.close_popup()
                return {"status": "failed", "text": result_text}

            self._save_screenshot("unknown_result")
            return {"status": "failed", "text": result_text}
        except Exception:
            self._save_screenshot("check_timeout")
            return {"status": "failed", "text": "check_timeout"}

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
                        self.driver.execute_script("arguments[0].click();", el)
                    try:
                        WebDriverWait(self.driver, 1).until(
                            EC.invisibility_of_element_located((By.CLASS_NAME, "reserve-box"))
                        )
                    except TimeoutException:
                        pass
                    if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                        return True
            except Exception:
                continue

        # 兜底: ESC 键
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
            if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
                return True
        except Exception:
            pass

        if not self.driver.find_elements(By.CLASS_NAME, "reserve-box"):
            return True

        self.log.warning("⚠️ 预约弹窗未能关闭,可能影响下一优先级选座。")
        return False
