# logic/booker.py
import os
import time

import base64
import logging
import threading
from datetime import datetime, timezone, timedelta, time as dt_time
from io import BytesIO

from selenium.common import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
from core.logger import get_logger
from logic.result_classifier import (
    classify_booking_result as _classify_booking_result,
    is_blacklist_feedback as _is_blacklist_feedback,
)

_logger = get_logger(__name__)
_CAPTCHA_SOLVER_LOCK = threading.Lock()
_YOLO4_SIAMESE_PRELOADED = False


class _AccountLoggerAdapter(logging.LoggerAdapter):
    """自动给每条日志加 [account] 前缀（供 SeatBooker 内部统一打 tag）。"""
    def process(self, msg, kwargs):
        tag = f"[{self.extra.get('account', 'unknown')}]"
        s = str(msg)
        # 已含相同 tag 的句子；或调用方已用 [%s] 占位（args 里会注入 account）→ 都跳过，避免重复 tag
        if tag in s or "[%s]" in s:
            return msg, kwargs
        return f"{tag} {msg}", kwargs


# 本地 YOLO+Siamese 点选模型启用窗口（北京时区，含起止）
LOCAL_CAPTCHA_WINDOW_START = dt_time(6, 30, 0)
LOCAL_CAPTCHA_WINDOW_END = dt_time(6, 35, 0)
CAPTCHA_FAST_FAIL_KEYWORDS = (
    "验证码错误",
    "请重试",
    "系统繁忙",
    "请稍后",
    "操作过于频繁",
    "提交失败",
)
BOOKING_RESULT_KEYWORDS = (
    "预约成功",
    "有效预约",
    "已有预约",
    "预约失败",
    "黑名单",
    "验证码错误",
    "系统繁忙",
    "请稍后",
    "请重试",
    "操作过于频繁",
    "\u7cfb\u7edf\u53ef\u9884\u7ea6\u65f6\u95f4",
    "\u6bcf\u65e5\u9650\u5236",
    "\u90e8\u5206\u8bfb\u8005",
    "\u5df2\u88ab\u4ed6\u4eba\u9884\u7ea6",
)
BOOKING_RESULT_FEEDBACK_SELECTORS = (
    (By.CSS_SELECTOR, ".el-message .el-message__content"),
    (By.CLASS_NAME, "el-message__content"),
    (By.CLASS_NAME, "el-message-box__message"),
    (By.CSS_SELECTOR, ".el-notification__content"),
    (By.CSS_SELECTOR, ".el-dialog__wrapper:not([style*='display: none']) .el-message-box__message"),
    (By.CSS_SELECTOR, ".el-dialog__wrapper:not([style*='display: none']) .el-dialog__body"),
)


def _in_local_captcha_window() -> bool:
    now = datetime.now(timezone(timedelta(hours=8))).time()
    return LOCAL_CAPTCHA_WINDOW_START <= now <= LOCAL_CAPTCHA_WINDOW_END



def preload_yolo4_siamese_model(account: str = "system") -> bool:
    """Preload the local click captcha models (click3 + click1) so the first real captcha is not a cold start."""
    global _YOLO4_SIAMESE_PRELOADED
    if _YOLO4_SIAMESE_PRELOADED:
        return True

    started = time.monotonic()
    try:
        from core.captcha_yolo4_siamese import preload_click3_target_bg
        from core.captcha_click1_yolo4_siamese import preload_click1_target_bg

        with _CAPTCHA_SOLVER_LOCK:
            if _YOLO4_SIAMESE_PRELOADED:
                return True
            preload_click3_target_bg()
            preload_click1_target_bg()
            _YOLO4_SIAMESE_PRELOADED = True

        _logger.info(
            "✅ [%s] YOLO4+Siamese 验证码模型预加载完成 (click3+click1)，用时 %.2fs",
            account,
            time.monotonic() - started,
        )
        return True
    except Exception as exc:
        _logger.warning("⚠️ [%s] YOLO4+Siamese 验证码模型预加载失败: %s", account, exc)
        return False


class SeatBooker:
    def __init__(self, driver, account: str = ""):
        self.driver = driver
        self.account = account or "unknown"
        self.wait = WebDriverWait(driver, 5)
        # 最近一次 select_time_and_wait 失败的原因（供外层日志冒泡）
        self.last_lock_failure_reason = ""
        self.last_stop_reason = ""
        self.last_booking_result_status = ""
        self.last_booking_result_text = ""
        self.last_captcha_auto_refreshed = False
        # 账号专属日志适配器：所有日志自动带上 [account] 前缀，供按账号拆分日志路由使用
        self.log = _AccountLoggerAdapter(_logger, {"account": self.account})

    def get_captcha_max_retries(self) -> int:
        """本地 YOLO 模型每个座位最多 10 次重试。"""
        return 10

    def _cache_terminal_booking_result(self, msg):
        """缓存提交后可见的终态提示，避免 toast 消失后 check_result 误判。"""
        if not msg:
            return ""
        status = _classify_booking_result(msg)
        if status in ("success", "stop", "blacklist", "failed"):
            self.last_booking_result_status = status
            self.last_booking_result_text = msg
            self.log.info("📝 结果反馈: %s", msg)
        return status

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

    def _get_booking_result_text(self):
        """只从真实反馈组件读取预约结果，避免公告/说明文字误判。"""
        for by, selector in BOOKING_RESULT_FEEDBACK_SELECTORS:
            try:
                elements = self.driver.find_elements(by, selector)
            except Exception:
                continue
            for el in reversed(elements):
                try:
                    if not el.is_displayed():
                        continue
                    msg = (el.text or "").strip()
                except Exception:
                    continue
                if msg and any(keyword in msg for keyword in BOOKING_RESULT_KEYWORDS):
                    return msg
        return ""

    def _detect_result_in_page_source(self, ps=None):
        """扫 page_source 检测预约结果（toast 已消失时的兜底）。

        返回 (status, text)：
          - 黑名单（正则全文匹配，优先）-> ("blacklist", "")
          - 命中结果关键词 -> (classify(kw), kw)
          - 无命中 -> (None, "")
        """
        if ps is None:
            ps = self.driver.page_source or ""
        if _is_blacklist_feedback(ps):
            return "blacklist", ""
        for kw in BOOKING_RESULT_KEYWORDS:
            if kw in ps:
                return _classify_booking_result(kw), kw
        return None, ""

    def _wait_captcha_result(self, timeout=3.2, poll_interval=0.06):
        """
        等待验证码提交反馈：
        - 弹窗消失 => 通过
        - 出现系统失败提示（验证码错误/系统繁忙等）=> 立即失败，避免傻等超时
        """
        start_wait = time.time()
        last_msg = ""
        last_ps_scan = 0.0
        while time.time() - start_wait < timeout:
            if not self.driver.find_elements(By.CSS_SELECTOR, ".captcha-modal-container"):
                return True, ""

            msg = self._get_latest_ui_message()
            if msg:
                last_msg = msg
                status = self._cache_terminal_booking_result(msg)
                if status == "success":
                    return True, ""
                if status == "stop":
                    self.last_stop_reason = msg
                    return False, msg
                if status in ("blacklist", "failed"):
                    return False, msg
                if any(keyword in msg for keyword in CAPTCHA_FAST_FAIL_KEYWORDS):
                    return False, msg
            else:
                # UI 选择器未匹配到 toast，每 0.5s 扫一次 page_source 兜底
                now = time.time()
                if now - last_ps_scan >= 0.5:
                    last_ps_scan = now
                    ps = self.driver.page_source or ""
                    for kw in CAPTCHA_FAST_FAIL_KEYWORDS:
                        if kw in ps:
                            detail = self._get_latest_ui_message() or kw
                            return False, detail

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

            # 关键词 → 用户友好的提示文案
            _kw_display = {
                "不可用": "该座位不可用，请选择其他座位",
                "没有可用时间": "当前的座位已经没有可用时间啦",
            }

            # 2. 闪电检测：先查 page_source 看有没有失败提示（比等 UI 元素快）
            page_fail_kw = ("没有可用时间", "没有可约时间", "约满", "不可预约", "当前不可用",
                            "无法预约", "已满", "已被", "不可用", "没有可用")
            ps = self.driver.page_source or ""
            fast_fail_hit = next((kw for kw in page_fail_kw if kw in ps), None)
            if fast_fail_hit:
                display_msg = _kw_display.get(fast_fail_hit, fast_fail_hit)
                self.last_lock_failure_reason = f"座位 {seat_num} 被系统拒绝：{display_msg}"
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
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
                        display_msg = _kw_display.get(hit_kw, hit_kw)
                        self.last_lock_failure_reason = f"座位 {seat_num} 被系统拒绝：{display_msg}"
                        self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
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
            # 缩短超时时间，实现"闪电失败" (fail-fast)，如果 1.5 秒内找不到就开始找下一个座位
            if not self.click_time_label(1, start_time, timeout=1.5):
                self.last_lock_failure_reason = (
                    f"座位 {seat_num} 的【开始时间 {start_time}】不存在/不可选"
                )
                self.log.warning("⚠️ [%s] %s", self.account, self.last_lock_failure_reason)
                self.close_popup()
                return False

            # 🔴 增加极短的强制等待，确保右侧时间轴渲染出来
            time.sleep(0.3)

            # 5. 选择结束时间 (Column 2)
            # 缩短超时时间到 1.5 秒，如果不可选立即失败
            if not self.click_time_label(2, end_time, timeout=1.5):
                self.last_lock_failure_reason = (
                    f"座位 {seat_num} 的【结束时间 {end_time}】不存在/不可选"
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

    @staticmethod
    def _decode_data_url(src: str) -> bytes | None:
        if not src or "base64" not in src:
            return None
        try:
            return base64.b64decode(src.split(",", 1)[1])
        except Exception:
            return None

    @staticmethod
    def _captcha_image_key(target_src: str, bg_src: str) -> str:
        return f"{target_src[-160:]}|{bg_src[-160:]}"

    def _read_captcha_images(self, previous_key: str = "", timeout: float = 1.0):
        """提取 target+bg bytes；previous_key 非空时等待刷新后的新图。"""
        deadline = time.monotonic() + max(0.05, timeout)
        while time.monotonic() < deadline:
            try:
                target_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-click img.captcha-text"
                )
                bg_el = self.driver.find_element(
                    By.CSS_SELECTOR, ".captcha-modal-content img"
                )
                target_src = target_el.get_attribute("src") or ""
                bg_src = bg_el.get_attribute("src") or ""
                target_bytes = self._decode_data_url(target_src)
                bg_bytes = self._decode_data_url(bg_src)
                key = self._captcha_image_key(target_src, bg_src)
                if target_bytes and bg_bytes and key != previous_key:
                    return target_bytes, bg_bytes, bg_el, key
            except Exception:
                pass
            time.sleep(0.05)
        return None, None, None, ""

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
            "click_points_in_bg": [(int(px), int(py)) for px, py in click_points_in_bg],
            "click_offsets": offsets,
            "bg_el": bg_el,
        }

    def _solve_captcha_points(self, target_bytes, bg_bytes):
        """本地模型接口：target+bg bytes -> 1 或 3 个 bg 坐标；失败返回 False。

        时间路由：
        - 06:30:00-06:35:00 (rush window) → click3 模型（3 个目标字符）
        - 其他时间 → click1 模型（1 个目标字符）
        """
        try:
            if _in_local_captcha_window():
                # Rush window (06:30-06:35): click3 — 3 个目标字符
                from core.captcha_yolo4_siamese import solve_click3_target_bg

                with _CAPTCHA_SOLVER_LOCK:
                    points = solve_click3_target_bg(target_bytes, bg_bytes)
                if points is not False and len(points) == 3:
                    self.log.info("✅ [rush] click3 模型识别成功: %d 个点", len(points))
                    return points
                self.log.warning("⚠️ [rush] click3 模型未命中")
                return False
            else:
                # Non-rush: click1 — 1 个目标字符
                from core.captcha_click1_yolo4_siamese import solve_click1_target_bg

                with _CAPTCHA_SOLVER_LOCK:
                    point = solve_click1_target_bg(target_bytes, bg_bytes)
                if point is not False:
                    self.log.info("✅ [non-rush] click1 模型识别成功: 1 个点")
                    return [point]
                self.log.warning("⚠️ [non-rush] click1 模型未命中")
                return False

        except Exception as exc:
            self.log.warning("⚠️ YOLO4+Siamese 模型推理异常: %s", exc)
            return False

    def _solve_captcha_locally(self, target_bytes, bg_bytes, bg_el):
        """本地 YOLO4 + Siamese 求解。返回 solve_data dict 或 None。"""
        click_points = self._solve_captcha_points(target_bytes, bg_bytes)
        if click_points is False:
            return None
        bg_pil = Image.open(BytesIO(bg_bytes))
        solve_data = self._build_solve_data(click_points, bg_el, bg_pil)
        if solve_data:
            self.log.info("✅ 本地 YOLO4+Siamese 输出坐标: %s", solve_data["click_points_in_bg"])
        return solve_data

    def pre_solve_captcha(self):
        """
        读取当前 target+bg，调用本地 YOLO4+Siamese。
        这里不刷新验证码；调用方负责在 False 后立刻刷新并进入下一次尝试。
        """
        try:
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".captcha-modal-container"))
            )
        except TimeoutException:
            self.log.info("ℹ️ 未检测到验证码弹窗")
            return {"solved": False, "no_captcha": True}

        self._save_screenshot("1_captcha_popup")
        captcha_type = "click3" if _in_local_captcha_window() else "click1"
        self.log.info("🔐 检测到点选验证码，solver=YOLO4+Siamese (%s)", captcha_type)

        try:
            target_bytes, bg_bytes, bg_el, key = self._read_captcha_images(timeout=1.2)
            if target_bytes is None or bg_bytes is None:
                self.log.warning("⚠️ 验证码图片未加载完成")
                return {"solved": False, "no_captcha": False}

            solve_data = self._solve_captcha_locally(target_bytes, bg_bytes, bg_el)
            if not solve_data:
                self.log.warning("⚠️ 本地模型返回 False，准备刷新验证码")
                return {"solved": False, "no_captcha": False, "captcha_key": key}

            solve_data["captcha_key"] = key
            self.log.info("✅ 本地模型返回 %d 个点击点，立即点击", len(solve_data.get("click_points_in_bg", [])))
            return solve_data
        except Exception as e:
            self.log.warning("⚠️ 验证码识别异常: %s", e)
        return {"solved": False, "no_captcha": False}

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
                # 0.5 秒后按钮仍不存在 → JS 兜底：用精确坐标派发 MouseEvent 到图片上
                if i == 10 and not btn_exists:
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

            # 3) 闪电检测：扫 page_source（比等 UI 元素更快更全）
            #    注意：不要在此处 _dismiss_stale_messages()，否则会清掉刚弹出的"验证码错误"
            ps = self.driver.page_source or ""
            captcha_wrong = any(kw in ps for kw in ("验证码错误", "请重试"))
            if captcha_wrong:
                self.log.warning("⚡ [%s] 闪电检测到验证码错误，本地模型本次识别失败", self.account)
                captcha_still_there = self.is_captcha_popup_present()
                if captcha_still_there:
                    self.log.info("🔄 [%s] 验证码已自动刷新 → 将重新求解并提交", self.account)
                    self.last_captcha_auto_refreshed = True
                return False

            # 先检查黑名单（正则需要长文本匹配，必须在关键词循环前）
            if _is_blacklist_feedback(ps):
                self._save_screenshot("blacklist")
                self.last_stop_reason = "黑名单"
                return False

            # 扫预约结果关键词
            for kw in BOOKING_RESULT_KEYWORDS:
                if kw in ps:
                    flash_status = self._cache_terminal_booking_result(kw)
                    if flash_status == "success":
                        return True
                    if flash_status == "stop":
                        self.last_stop_reason = kw
                        return False
                    if flash_status == "blacklist":
                        return False
                    if flash_status == "failed":
                        return True  # 交给外层 check_result 处理

            # 4) 检查验证码是否通过（优先监听系统提示，避免无谓等待）
            captcha_ok, fail_msg = self._wait_captcha_result(timeout=3.0)
            if captcha_ok:
                self.log.info("✅ 验证码确认通过！")
            else:
                if fail_msg:
                    self.log.warning("⚠️ 验证码未通过: %s", fail_msg)
                else:
                    self.log.warning("⚠️ 验证码可能未通过（弹窗未消失）")
                    self._save_screenshot("captcha_confirm_timeout")
                return False

            # 5) 尝试再次点击「立即预约」（部分场景需要二次确认）
            try:
                submit_btn = WebDriverWait(self.driver, 0.3).until(
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
                ".forEach(function(el) { el.style.display = 'none'; });"
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

    def _dismiss_stale_messages(self):
        """移除页面上所有残留的 .el-message 提示，避免 page_source 误扫到旧的'验证码错误'。"""
        self.driver.execute_script(
            "document.querySelectorAll('.el-message').forEach(function(el) { el.remove(); });"
        )

    def _refresh_click_captcha(self, previous_key: str = "", wait_timeout: float = 1.0):
        """点击刷新图标获取新验证码，多选择器兜底；返回新验证码 key 或空字符串。"""
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
                # 清掉旧的 toast/message，避免 page_source 残留 "验证码错误" 误判
                self._dismiss_stale_messages()
                _target, _bg, _bg_el, key = self._read_captcha_images(
                    previous_key=previous_key,
                    timeout=wait_timeout,
                )
                return key
            except Exception:
                continue
        self.log.warning("⚠️ 刷新验证码按钮点击失败")
        return ""

    def _dispatch_check_result(self, status, text):
        """把分类结果映射为 check_result 的返回 dict，并执行对应副作用（截图/关弹窗）。

        覆盖 _classify_booking_result 的全部返回值（success/stop/blacklist/retry_captcha/failed），
        供 check_result 的正常路径与 page_source 兜底路径复用，避免两处分发逻辑重复。
        """
        if status == "success":
            self.close_popup()
            return {"status": "success", "text": text}
        if status == "stop":
            self._save_screenshot("booking_stop")
            self._close_captcha_modal()
            self.close_popup()
            return {"status": "stop", "text": text}
        if status == "blacklist":
            self._save_screenshot("blacklist")
            self.close_popup()
            return {"status": "blacklist", "text": text}
        if status == "retry_captcha":
            return {"status": "retry_captcha", "text": text}
        # failed（及任何未预期状态）：换下一个座位
        self._save_screenshot("booking_failed")
        self.close_popup()
        return {"status": "failed", "text": text}

    def check_result(self):
        """
        检查提交结果。
        返回:
          - {"status":"success", ...}
          - {"status":"retry_captcha", ...}  # 验证码错误/系统繁忙，可继续当前座位重试
          - {"status":"failed", ...}
        """
        try:
            cached_status = self.last_booking_result_status
            cached_text = self.last_booking_result_text
            if cached_status in ("success", "stop", "blacklist"):
                self.log.info("📝 使用已缓存结果反馈: %s", cached_text)
                if cached_status == "success":
                    self.close_popup()
                    return {"status": "success", "text": cached_text}
                if cached_status == "stop":
                    self._save_screenshot("booking_stop")
                    self._close_captcha_modal()
                    self.close_popup()
                    return {"status": "stop", "text": cached_text}
                if cached_status == "blacklist":
                    self._save_screenshot("blacklist")
                    self.close_popup()
                    return {"status": "blacklist", "text": cached_text}

            # 抢座窗口期 3s 超时。只监听 toast/dialog 等真实结果反馈，避免命中页面公告里的规则说明。
            result_text = WebDriverWait(self.driver, 3, poll_frequency=0.1).until(
                lambda _: self._get_booking_result_text() or False
            )
            self.log.info("📝 结果反馈: %s", result_text)
            status = _classify_booking_result(result_text)
            return self._dispatch_check_result(status, result_text)
        except Exception:
            # WebDriverWait 超时：toast 可能已消失，用 page_source 兜底
            self._dismiss_stale_messages()
            ps = self.driver.page_source or ""
            status, matched_kw = self._detect_result_in_page_source(ps)
            # 黑名单全文匹配（matched_kw 为空）保留专属兜底文案
            if status == "blacklist" and not matched_kw:
                self._save_screenshot("blacklist")
                self.close_popup()
                return {"status": "blacklist", "text": "黑名单（page_source 兜底）"}
            if status is not None:
                self.log.info("📝 page_source 兜底检测到: %s", matched_kw)
                return self._dispatch_check_result(status, matched_kw)
            self._save_screenshot("check_timeout")
            return {"status": "failed", "text": "check_timeout"}

    def ensure_on_seat_grid(self, timeout=5.0):
        """确认当前在座位图页面，不在则点击「自选座位」返回。"""
        if self.driver.find_elements(By.CLASS_NAME, "seat-name"):
            return True
        self.log.info("🔙 [%s] 当前不在座位图，尝试返回...", self.account)
        try:
            btn = WebDriverWait(self.driver, 3).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), '自选座位')]")))
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(0.3)
        except Exception:
            pass
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.CLASS_NAME, "seat-name")))
            return True
        except Exception:
            self.log.warning("⚠️ [%s] 无法返回座位图！", self.account)
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
