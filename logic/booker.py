# logic/booker.py
import os
import time
import random
import base64
from datetime import datetime, timezone, timedelta
from io import BytesIO

from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from core.logger import get_logger

logger = get_logger(__name__)


class SeatBooker:
    def __init__(self, driver):
        self.driver = driver
        self.wait = WebDriverWait(driver, 5)

    def _save_failure_screenshot(self, tag="failure"):
        """保存失败截图到 logs 目录，用于事后分析"""
        try:
            log_dir = getattr(__import__("config"), "LOG_DIR", "logs")
            os.makedirs(log_dir, exist_ok=True)
            now = datetime.now(timezone(timedelta(hours=8)))
            filename = f"screenshot_{tag}_{now.strftime('%Y%m%d_%H%M%S')}.png"
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

    def pre_solve_captcha(self, max_retries=5):
        """
        时序提交 - 阶段2: 预分析点选验证码。
        在 fire_at 之前完成 OCR 识别和坐标计算，为精确点击做准备。

        Returns:
            dict: solved/no_captcha 标志 + 预计算的点击数据
        """
        from core.captcha import click_solver

        # 等待验证码弹窗出现
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".captcha-modal-container"))
            )
        except TimeoutException:
            logger.info("ℹ️ 未检测到验证码弹窗")
            return {"solved": False, "no_captcha": True}

        logger.info("🔐 检测到点选验证码，开始预分析...")

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("🔄 预分析第 %d/%d 次...", attempt, max_retries)
                time.sleep(0.5)  # 等待图片渲染

                # ① 提取目标文字图片
                target_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-click img.captcha-text"
                )
                target_src = target_el.get_attribute("src") or ""
                if "base64" not in target_src:
                    logger.warning("⚠️ 目标文字图片未加载，等待...")
                    time.sleep(1)
                    continue
                target_bytes = base64.b64decode(target_src.split(",", 1)[1])

                # ② 提取背景大图
                bg_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-content img"
                )
                bg_src = bg_el.get_attribute("src") or ""
                if "base64" not in bg_src:
                    logger.warning("⚠️ 背景图片未加载，等待...")
                    time.sleep(1)
                    continue
                bg_bytes = base64.b64decode(bg_src.split(",", 1)[1])

                # ③ 求解
                click_points = click_solver.solve(target_bytes, bg_bytes)
                if not click_points:
                    logger.warning("⚠️ 验证码求解失败，刷新重试...")
                    self._refresh_click_captcha()
                    continue

                # ④ 计算显示尺寸与实际图像的缩放比
                display_w = bg_el.size["width"]
                display_h = bg_el.size["height"]
                pil_img = Image.open(BytesIO(bg_bytes))
                actual_w, actual_h = pil_img.size
                scale_x = display_w / actual_w
                scale_y = display_h / actual_h

                logger.info("✅ 验证码预分析完成！%d 个点击目标，坐标: %s", len(click_points), click_points)
                return {
                    "solved": True,
                    "no_captcha": False,
                    "click_points": click_points,
                    "bg_el": bg_el,
                    "display_w": display_w,
                    "display_h": display_h,
                    "scale_x": scale_x,
                    "scale_y": scale_y,
                }

            except Exception as e:
                logger.warning("⚠️ 预分析异常: %s", e)
                if attempt < max_retries:
                    self._refresh_click_captcha()

        logger.error("❌ 验证码预分析 %d 次均失败", max_retries)
        self._save_failure_screenshot("pre_solve_failed")
        return {"solved": False, "no_captcha": False}

    def execute_captcha_clicks(self, solve_data):
        """
        时序提交 - 阶段3a: 按预计算坐标点击验证码文字。
        """
        if not solve_data.get("solved"):
            return False

        bg_el = solve_data["bg_el"]
        display_w = solve_data["display_w"]
        display_h = solve_data["display_h"]
        scale_x = solve_data["scale_x"]
        scale_y = solve_data["scale_y"]

        for px, py in solve_data["click_points"]:
            offset_x = px * scale_x - display_w / 2
            offset_y = py * scale_y - display_h / 2
            ActionChains(self.driver).move_to_element_with_offset(
                bg_el, offset_x, offset_y
            ).click().perform()
            time.sleep(0.15)  # 缩短间隔（原 0.3s）提高速度

        logger.info("✅ 验证码文字已全部点击")
        return True

    def click_captcha_confirm(self):
        """
        时序提交 - 阶段3b: 点击验证码"确定"按钮，完成预约。
        """
        try:
            confirm_btn = self.driver.find_element(
                By.CSS_SELECTOR, ".captcha-modal-footer .confirm-btn"
            )
            confirm_btn.click()
            logger.info("🚀 已点击验证码「确定」！")

            # 等待验证码弹窗消失 → 验证通过
            try:
                WebDriverWait(self.driver, 3).until(
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

    def _handle_click_captcha(self, max_retries=5):
        """
        检测并处理预约提交后弹出的点选文字验证码。
        如果没有弹出验证码则直接返回 True。
        """
        from core.captcha import click_solver

        # 检测验证码弹窗是否出现
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".captcha-modal-container"))
            )
        except TimeoutException:
            # 没有验证码弹窗，直接通过
            return True

        logger.info("🔐 检测到点选验证码！")

        for attempt in range(1, max_retries + 1):
            try:
                logger.info("🔄 验证码第 %d/%d 次尝试...", attempt, max_retries)
                time.sleep(0.5)  # 等待图片渲染

                # ① 提取目标文字图片
                target_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-click img.captcha-text"
                )
                target_src = target_el.get_attribute("src") or ""
                if "base64" not in target_src:
                    logger.warning("⚠️ 目标文字图片未加载，等待...")
                    time.sleep(1)
                    continue
                target_bytes = base64.b64decode(target_src.split(",", 1)[1])

                # ② 提取背景大图
                bg_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-content img"
                )
                bg_src = bg_el.get_attribute("src") or ""
                if "base64" not in bg_src:
                    logger.warning("⚠️ 背景图片未加载，等待...")
                    time.sleep(1)
                    continue
                bg_bytes = base64.b64decode(bg_src.split(",", 1)[1])

                # ③ 求解
                click_points = click_solver.solve(target_bytes, bg_bytes)
                if not click_points:
                    logger.warning("⚠️ 验证码求解失败，刷新重试...")
                    self._refresh_click_captcha()
                    continue

                # ④ 计算显示尺寸与实际图像的缩放
                display_w = bg_el.size["width"]
                display_h = bg_el.size["height"]
                pil_img = Image.open(BytesIO(bg_bytes))
                actual_w, actual_h = pil_img.size
                scale_x = display_w / actual_w
                scale_y = display_h / actual_h

                # ⑤ 依次点击对应位置
                for px, py in click_points:
                    offset_x = px * scale_x - display_w / 2
                    offset_y = py * scale_y - display_h / 2
                    ActionChains(self.driver).move_to_element_with_offset(
                        bg_el, offset_x, offset_y
                    ).click().perform()
                    time.sleep(0.3)

                # ⑥ 点击「确定」
                time.sleep(0.5)
                confirm_btn = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-footer .confirm-btn"
                )
                confirm_btn.click()

                # ⑦ 等待弹窗消失 → 验证通过
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
                    self._refresh_click_captcha()
                    continue

            except Exception as e:
                logger.warning("⚠️ 验证码处理异常: %s", e)
                if attempt < max_retries:
                    self._refresh_click_captcha()

        logger.error("❌ 点选验证码多次尝试均失败")
        self._save_failure_screenshot("captcha_failed")
        return False

    def _refresh_click_captcha(self):
        """点击刷新图标获取新验证码"""
        try:
            refresh_btn = self.driver.find_element(
                By.CSS_SELECTOR, ".captcha-modal-title img.refresh"
            )
            refresh_btn.click()
            time.sleep(1)
        except Exception:
            logger.warning("⚠️ 刷新验证码按钮点击失败")

    def check_result(self):
        """检查结果"""
        try:
            # 等待所有可能的弹窗/提示文本
            res_element = self.wait.until(EC.any_of(
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
        关闭座位预约弹窗（通用关闭逻辑）
        """
        logger.info("❌ 正在尝试关闭预约弹窗...")
        try:
            close_btn_xpath = '//div[contains(@class, "reserve-box")]//i[contains(@class, "el-icon-close")]'

            # 使用较短的等待时间，因为我们知道弹窗应该还在
            close_btn = WebDriverWait(self.driver, 2).until(
                EC.element_to_be_clickable((By.XPATH, close_btn_xpath))
            )
            close_btn.click()
            # 确保弹窗消失
            WebDriverWait(self.driver, 2).until(
                EC.invisibility_of_element_located((By.CLASS_NAME, "reserve-box"))
            )
            logger.info("✅ 预约弹窗已关闭。")
            return True
        except Exception:
            # 如果找不到关闭按钮或弹窗已消失，则忽略
            logger.warning("⚠️ 预约弹窗似乎已经关闭或找不到关闭按钮。")
            return False