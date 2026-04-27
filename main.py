# python
import os
import threading
import shutil
import tempfile
import time

# --- 模块导入（延迟导入 config，支持 GUI 动态注入） ---
import core.utils as utils
from logic.auth import Authenticator
from logic.navigator import enter_room
from logic.booker import SeatBooker
from core.logger import get_logger
from core.notifications import build_success_email, send_email

from datetime import time as dt_time
from datetime import timedelta


def _cfg(attr, default=None):
    import config
    return getattr(config, attr, default)


logger = get_logger(__name__)

# =================== 全局开关 ===================
# True = 任何时间段抢座都强制走 ttshitu API（忽略 6:30:00-6:35:00 时间窗口）
# False = 仅 6:30:00-6:35:00 抢座窗口使用 API，其余时段使用本地 ddddocr
FORCE_API_ALWAYS = True
# ================================================

STRICT_NEXT_DAY_CUTOFF = dt_time(10, 0, 0)
SYSTEM_CLOSE_TIME = dt_time(22, 0, 0)
PREP_LEAD_SECONDS = 60  # 6:29:00 打开浏览器：fire_at 前 60s 启动并登录+进入自习室
PRE_SUBMIT_SECONDS = 10  # 6:29:50 触发验证码并点击文字：fire_at 前 10s
CAPTCHA_CLICK_SECONDS = 10  # 与 PRE_SUBMIT_SECONDS 同步：触发后立即开始点击文字
CAPTCHA_RETRIES_PER_SEAT = 10  # 每个优先座位最多给 10 次点选验证码机会
FIRE_LEAD_MS = 30  # 抢座 RTT 补偿:提前 30ms 醒来,让 click 请求大致在 fire_at 整点到达服务端
BROWSER_SESSION_WINDOW_MINUTES = 5
BROWSER_SESSION_MAX_ATTEMPTS = 6
STRICT_RESTART_END_TIME = dt_time(7, 0, 0)


def build_strict_schedule(now=None):
    """
    严格模式日程：
    - 10:00-24:00 启动：排到次日
    - 其他时间启动：抢当天
    返回 prep_at（准备时刻）和 fire_at（提交时刻），中间无空等。
    """
    now = now or utils.get_beijing_time()
    current_clock = now.timetz().replace(tzinfo=None)

    run_date = now.date()
    if current_clock >= STRICT_NEXT_DAY_CUTOFF:
        run_date = run_date + timedelta(days=1)

    fire_at = now.replace(
        year=run_date.year,
        month=run_date.month,
        day=run_date.day,
        hour=6,
        minute=30,
        second=0,
        microsecond=0,
    )
    prep_at = fire_at - timedelta(seconds=PREP_LEAD_SECONDS)
    pre_fire_at = fire_at - timedelta(seconds=PRE_SUBMIT_SECONDS)
    captcha_click_at = fire_at - timedelta(seconds=CAPTCHA_CLICK_SECONDS)
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": run_date,
        "prep_at": prep_at,
        "pre_fire_at": pre_fire_at,
        "captcha_click_at": captcha_click_at,
        "fire_at": fire_at,
        "close_at": close_at,
    }


def build_custom_schedule(target_hour, target_minute, now=None):
    """
    自定义定时模式日程：用户指定准点提交时间。
    如果当前已过该时间，则排到次日。
    """
    now = now or utils.get_beijing_time()
    fire_at = now.replace(
        hour=target_hour,
        minute=target_minute,
        second=0,
        microsecond=0,
    )
    if now >= fire_at:
        fire_at = fire_at + timedelta(days=1)

    prep_at = fire_at - timedelta(seconds=PREP_LEAD_SECONDS)
    pre_fire_at = fire_at - timedelta(seconds=PRE_SUBMIT_SECONDS)
    captcha_click_at = fire_at - timedelta(seconds=CAPTCHA_CLICK_SECONDS)
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": fire_at.date(),
        "prep_at": prep_at,
        "pre_fire_at": pre_fire_at,
        "captcha_click_at": captcha_click_at,
        "fire_at": fire_at,
        "close_at": close_at,
    }


def wait_until(target_time, account, stop_event: threading.Event, stage_name: str):
    """
    改进的绝对时间等待逻辑：
    - 如果目标时间已过，立即继续，不顺延到次日
    - 否则分段等待，降低 CPU 占用，并响应 stop_event
    """
    now = utils.get_beijing_time()
    if now >= target_time:
        logger.info(
            "⏩ [%s] %s目标时间已过 (%s)，立即继续。",
            account,
            stage_name,
            target_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return True

    wait_seconds = (target_time - now).total_seconds()

    logger.info(
        "⏳ [%s] 当前: %s -> %s: %s",
        account,
        now.strftime("%Y-%m-%d %H:%M:%S"),
        stage_name,
        target_time.strftime("%Y-%m-%d %H:%M:%S"),
    )

    if wait_seconds > 0:
        logger.info("💤 [%s] %s前准备休眠 %.3f 秒...", account, stage_name, wait_seconds)

        # 先做较长时间的 sleep，提前小幅唤醒，每 30 分钟输出心跳
        if wait_seconds > 5:
            to_sleep = wait_seconds - 3
            HEARTBEAT_INTERVAL = 1800  # 30 分钟

            while to_sleep > 0 and not stop_event.is_set():
                chunk = min(HEARTBEAT_INTERVAL, to_sleep)
                if stop_event.wait(timeout=chunk):
                    logger.info("🛑 [%s] 等待期间收到停止信号，退出等待", account)
                    return False
                to_sleep -= chunk
                if to_sleep > 0:
                    now_hb = utils.get_beijing_time()
                    logger.info(
                        "💓 [%s] 心跳: %s | %s还剩 %.0f 分钟",
                        account,
                        now_hb.strftime("%H:%M:%S"),
                        stage_name,
                        to_sleep / 60,
                    )

        # 精确等待阶段：分段 sleep，最后极短时间允许忙等
        while not stop_event.is_set():
            now = utils.get_beijing_time()
            remaining = (target_time - now).total_seconds()
            if remaining <= 0:
                break
            # 如果剩余 > 0.5s，使用较短 sleep
            if remaining > 0.5:
                # sleep 不超过 0.2s，避免跨过目标时间
                if stop_event.wait(timeout=min(0.2, remaining - 0.4 if remaining - 0.4 > 0 else 0.05)):
                    logger.info("🛑 [%s] 等待期间收到停止信号，退出等待", account)
                    return False
            elif remaining > 0.02:
                # 最后 20ms 以内用较短 sleep，减少忙等时间
                if stop_event.wait(timeout=0.01):
                    logger.info("🛑 [%s] 等待期间收到停止信号，退出等待", account)
                    return False
            else:
                # 极短时间 (<20ms) 小范围忙等以提高精度
                pass

    if stop_event.is_set():
        logger.info("🛑 [%s] 等待被取消", account)
        return False

    logger.info("\n🔥 [%s] %s时间到！目标时刻 %s 已触发。", account, stage_name, target_time.strftime('%H:%M:%S'))
    return True


def is_after_close(close_time) -> bool:
    return utils.get_beijing_time() >= close_time


class DeadlineStopEvent:
    """Wrap a stop event with an optional absolute deadline."""

    def __init__(self, base_event: threading.Event, deadline=None):
        self.base_event = base_event
        self.deadline = deadline

    def deadline_reached(self) -> bool:
        return self.deadline is not None and utils.get_beijing_time() >= self.deadline

    def is_set(self) -> bool:
        return self.base_event.is_set() or self.deadline_reached()

    def wait(self, timeout=None) -> bool:
        if self.base_event.is_set():
            return True

        if self.deadline is None:
            return self.base_event.wait(timeout=timeout)

        remaining = (self.deadline - utils.get_beijing_time()).total_seconds()
        if remaining <= 0:
            return True

        effective_timeout = remaining if timeout is None else max(0.0, min(timeout, remaining))
        if self.base_event.wait(timeout=effective_timeout):
            return True
        return self.deadline_reached()


def build_browser_session_plan(schedule, schedule_mode="strict"):
    """
    为预约模式生成浏览器重启时间窗。

    - 每轮浏览器只运行 5 分钟
    - 最多重启 6 轮
    - strict 模式默认抢到 7:00 为止
    - custom 模式默认抢 fire_at 后 30 分钟为止
    - 最终不会超过系统 close_at
    """
    window = timedelta(minutes=BROWSER_SESSION_WINDOW_MINUTES)

    if schedule_mode == "strict":
        raw_end = schedule["fire_at"].replace(
            hour=STRICT_RESTART_END_TIME.hour,
            minute=STRICT_RESTART_END_TIME.minute,
            second=0,
            microsecond=0,
        )
    else:
        raw_end = schedule["fire_at"] + window * BROWSER_SESSION_MAX_ATTEMPTS

    overall_end = min(raw_end, schedule["close_at"])
    if overall_end <= schedule["fire_at"]:
        overall_end = min(schedule["close_at"], schedule["fire_at"] + window)

    session_deadlines = []
    deadline = schedule["fire_at"] + window
    while len(session_deadlines) < BROWSER_SESSION_MAX_ATTEMPTS and deadline <= overall_end:
        session_deadlines.append(deadline)
        deadline += window

    if not session_deadlines and overall_end > schedule["fire_at"]:
        session_deadlines.append(overall_end)

    return {
        "overall_end": overall_end,
        "session_deadlines": session_deadlines,
    }


def _enlarge_driver_pool(driver, pool_size: int = 10):
    """
    把 Selenium 的 urllib3 连接池放大到 pool_size。
    默认 maxsize=1 时,录屏线程和主线程同时调 driver 会触发
    "Connection pool is full, discarding connection" 警告。
    """
    try:
        import urllib3
        driver.command_executor._conn = urllib3.PoolManager(
            num_pools=pool_size, maxsize=pool_size, timeout=120,
        )
    except Exception as e:
        logger.debug("放大连接池失败 (可忽略): %s", e)


def _apply_window_layout(driver, account, slot_index, slot_total):
    """
    根据是否 headless 决定窗口布局:
      - headless: 不可见,两个浏览器都铺满主屏(viewport 越大,内部截图越清晰)
      - 非 headless: 等分主屏槽位 (2 个账号 → 左右半屏)
    """
    if slot_total <= 0 or slot_index < 0 or slot_index >= slot_total:
        return
    try:
        import mss as _mss
        with _mss.mss() as sct:
            mon = sct.monitors[1]
            screen_x = int(mon.get("left", 0))
            screen_y = int(mon.get("top", 0))
            screen_w = int(mon.get("width", 1920))
            screen_h = int(mon.get("height", 1080))
        is_headless = bool(_cfg("HEADLESS", True))
        if is_headless:
            x, y, w, h = screen_x, screen_y, screen_w, screen_h
        else:
            taskbar_margin = 60
            usable_h = max(400, screen_h - taskbar_margin)
            slot_w = screen_w // slot_total
            x = screen_x + slot_w * slot_index
            y = screen_y
            w = slot_w
            h = usable_h
        driver.set_window_position(x, y)
        driver.set_window_size(w, h)
        mode = "headless 全屏" if is_headless else f"slot {slot_index + 1}/{slot_total}"
        logger.info("🪟 [%s] 浏览器窗口布局 (%s): (%d,%d) %dx%d",
                    account, mode, x, y, w, h)
    except Exception as e:
        logger.warning("⚠️ [%s] 窗口布局失败,保持默认位置: %s", account, e)


def _close_driver_quietly(driver):
    if not driver:
        return
    try:
        driver.quit()
    except Exception:
        pass
    try:
        service = getattr(driver, "service", None)
        process = getattr(service, "process", None)
        if process and process.poll() is None:
            process.kill()
    except Exception:
        pass


def _watch_session_deadline(driver, account, session_index, session_deadline, stop_event, cancel_event):
    """
    Independent watchdog that force-closes the browser the moment a session hits
    its hard deadline, even if the main flow is blocked inside Selenium calls.
    """
    while not stop_event.is_set():
        remaining = (session_deadline - utils.get_beijing_time()).total_seconds()
        if remaining <= 0:
            break
        if cancel_event.wait(timeout=min(0.2, remaining)):
            return

    if stop_event.is_set() or cancel_event.is_set():
        return

    logger.warning(
        "⛔ [%s] 第 %d 轮已到硬截止 %s，不管当前卡在哪一步，强制关闭浏览器。",
        account,
        session_index,
        session_deadline.strftime("%H:%M:%S"),
    )
    _close_driver_quietly(driver)


def _notify_success(account, room, seat, start_time, end_time):
    title_str, success_msg = build_success_email(account, room, seat, start_time, end_time)
    if not send_email(title_str, success_msg):
        logger.warning("📧 [%s] 邮件发送失败！", account)


def attempt_seat_selection(driver, booker, account, start_time, end_time, stop_event, schedule, navigate=True):
    """
    （可选）进入房间 + 遍历偏好座位选座。
    优先座位全部不可用时，随机选同自习室的其他可用座位。
    成功返回座位号字符串，失败返回 None。
    """
    TARGET_CAMPUS = _cfg('TARGET_CAMPUS')
    TARGET_ROOM = _cfg('TARGET_ROOM')
    PREFER_SEATS = _cfg('PREFER_SEATS', [])

    if schedule and is_after_close(schedule["close_at"]):
        logger.info("🛑 [%s] 已超过当日系统关闭时间 %s，停止。", account, schedule["close_at"].strftime("%H:%M:%S"))
        return None

    if navigate:
        if not enter_room(driver, TARGET_CAMPUS, TARGET_ROOM):
            logger.warning("😭 [%s] 找不到自习室 %s，准备重试...", account, TARGET_ROOM)
            try:
                driver.refresh()
            except Exception:
                logger.exception("刷新失败")
            stop_event.wait(timeout=2)
            return None

    # 阶段 1：尝试优先座位
    for seat in PREFER_SEATS:
        if stop_event.is_set():
            return None
        if booker.select_time_and_wait(seat, start_time, end_time):
            return seat

    # 阶段 2：优先座位全部不可用 → 随机回退
    logger.info("💔 [%s] 所有优先座位不可用，启动随机回退...", account)
    if not stop_event.is_set():
        random_seat = booker.select_random_available(start_time, end_time, stop_event=stop_event, exclude_seats=PREFER_SEATS)
        if random_seat:
            return random_seat

    logger.info("💔 [%s] 随机回退也未找到可用座位，刷新重来！", account)
    try:
        driver.refresh()
    except Exception:
        logger.exception("刷新失败")
    stop_event.wait(timeout=1)
    return None


def run_timed_priority_attack(
    driver,
    booker,
    account,
    start_time,
    end_time,
    schedule,
    session_stop,
    stop_event,
):
    """
    "准点抢座"主流程（单浏览器会话）：

    - 定时模式 (schedule != None)：
        6:29:50 (pre_fire_at) 触发"立即预约" + 解析验证码 + 依次点击文字
        6:30:00 (fire_at)      点击验证码"确定"按钮提交
    - 立即模式 (schedule = None)：直接触发 + 解决 + 立即点确定
    - 每个优先座位最多 10 次验证码机会；超过则切到下一优先级
    - 10 个优先级全失败 → 退出，不重启浏览器

    返回:
      ("success", seat) | ("all_failed", None) | ("stopped", None) | ("restart", None)
    """
    PREFER_SEATS = _cfg('PREFER_SEATS', []) or []
    if not PREFER_SEATS:
        logger.warning("⚠️ [%s] 未配置 PREFER_SEATS，无法执行优先级抢座。", account)
        return ("all_failed", None)

    fire_at = schedule["fire_at"] if schedule else None
    pre_fire_at = schedule["pre_fire_at"] if schedule else None

    # 用于"第一个成功锁住的座位才走 pre_fire_at / fire_at 同步等待"。
    # 优先级 1、2 锁不到时，自动让位给优先级 3 等定时点触发。
    timed_window_consumed = False

    for priority, seat in enumerate(PREFER_SEATS, start=1):
        if session_stop.is_set():
            return ("stopped", None) if stop_event.is_set() else ("restart", None)

        logger.info("🎯 [%s] === 开始尝试优先级 %d 座位 %s ===", account, priority, seat)

        # 1) 锁定座位（弹时间选择框 + 选时间）
        if not booker.select_time_and_wait(seat, start_time, end_time):
            logger.warning("⚠️ [%s] 优先级 %d 座位 %s 锁定失败，继续下一优先级。", account, priority, seat)
            continue

        # 2) 定时模式 + 还没消费过定时窗口 → 等到 pre_fire_at 再触发；其余立刻触发
        is_first_locked_seat = not timed_window_consumed
        if is_first_locked_seat and pre_fire_at is not None:
            ok = wait_until(pre_fire_at, account, session_stop, f"等待 {pre_fire_at.strftime('%H:%M:%S')} 触发验证码")
            if not ok:
                booker.close_popup()
                if stop_event.is_set():
                    return ("stopped", None)
                return ("restart", None)

        # 3) 触发"立即预约" → 弹出验证码弹窗
        if not booker.fire_submit_trigger():
            logger.warning("⚠️ [%s] 优先级 %d 触发提交失败，关闭弹窗换下一优先级", account, priority)
            booker.close_popup()
            continue

        # 4) 验证码循环：最多 CAPTCHA_RETRIES_PER_SEAT 次机会
        captcha_passed = False
        first_round_for_priority = True

        for retry in range(1, CAPTCHA_RETRIES_PER_SEAT + 1):
            if session_stop.is_set():
                if stop_event.is_set():
                    return ("stopped", None)
                return ("restart", None)

            logger.info(
                "🔁 [%s] 优先级 %d 第 %d/%d 次验证码尝试...",
                account, priority, retry, CAPTCHA_RETRIES_PER_SEAT,
            )

            # 4a) 解析 + 点击文字（pre_solve_captcha 内部已做单次的图片就绪等待）
            solve_data = booker.pre_solve_captcha(max_retries=1)
            if solve_data.get("no_captcha"):
                logger.info("ℹ️ [%s] 未检测到验证码弹窗，直接进入结果检查。", account)
                captcha_passed = True
                break
            if not solve_data.get("solved"):
                logger.warning("⚠️ [%s] 第 %d 次解析失败，刷新验证码。", account, retry)
                booker._refresh_click_captcha()
                continue
            if not booker.execute_captcha_clicks(solve_data):
                booker._refresh_click_captcha()
                continue

            # 4b) 第一个成功锁住的座位 + 第 1 次重试 + 定时模式：等到 fire_at 再点确定
            if is_first_locked_seat and first_round_for_priority and fire_at is not None:
                first_round_for_priority = False
                timed_window_consumed = True  # 定时窗口已消费，后续座位走立即模式
                # RTT 补偿:提前 FIRE_LEAD_MS 醒来,让 click 的 HTTP 请求大致在 fire_at 整点抵达服务端
                early_fire_at = fire_at - timedelta(milliseconds=FIRE_LEAD_MS)
                ok = wait_until(early_fire_at, account, session_stop,
                                f"等待 {fire_at.strftime('%H:%M:%S')} 提交确定 (提前 {FIRE_LEAD_MS}ms)")
                if not ok:
                    if stop_event.is_set():
                        return ("stopped", None)
                    return ("restart", None)
            else:
                first_round_for_priority = False
                if is_first_locked_seat:
                    timed_window_consumed = True

            # 4c) 点击确定
            if booker.click_captcha_confirm():
                captcha_passed = True
                break
            logger.warning("⚠️ [%s] 第 %d 次确认未通过，准备刷新验证码重试。", account, retry)
            # API 识别错了 → 自动上报，5 分钟内退费
            booker._report_api_error_safe(solve_data.get("api_id"))
            booker._refresh_click_captcha()

        if not captcha_passed:
            logger.warning(
                "💔 [%s] 优先级 %d 座位 %s 在 %d 次重试后仍未通过验证码，切下一优先级。",
                account, priority, seat, CAPTCHA_RETRIES_PER_SEAT,
            )
            booker.close_popup()
            continue

        # 5) 验证码通过 → 检查最终结果
        if booker.check_result():
            logger.info("🎉🎉🎉 [%s] 优先级 %d 座位 %s 抢座成功！", account, priority, seat)
            return ("success", seat)

        logger.warning("💔 [%s] 优先级 %d 座位 %s 提交后被拒绝，尝试下一优先级。", account, priority, seat)
        try:
            driver.find_element("class name", "close-icon").click()
        except Exception:
            pass

    logger.error(
        "❌ [%s] 全部 %d 个优先级座位都失败，按用户要求停止当前会话。",
        account, len(PREFER_SEATS),
    )
    return ("all_failed", None)


def run_browser_session(
    account,
    password,
    start_time,
    end_time,
    stop_event,
    schedule=None,
    session_deadline=None,
    wait_for_fire=False,
    session_index=1,
    slot_index=0,
    slot_total=1,
):
    """
    执行单轮浏览器会话。

    返回值：
    - "success": 本轮成功抢到座位并完成提交通知
    - "restart": 本轮未成功，交给外层决定是否重启浏览器
    - "stopped": 收到全局停止信号
    """
    from core.driver import get_driver

    TARGET_ROOM = _cfg('TARGET_ROOM')
    driver = None
    recorder = None
    session_stop = DeadlineStopEvent(stop_event, session_deadline)
    watchdog_cancel = threading.Event()
    watchdog_thread = None

    try:
        if session_deadline:
            logger.info(
                "🌐 [%s] 第 %d 轮浏览器会话启动，本轮最晚运行到 %s。",
                account,
                session_index,
                session_deadline.strftime("%H:%M:%S"),
            )
        else:
            logger.info("🌐 [%s] 浏览器会话启动。", account)

        driver = get_driver(None)

        # 录屏线程会跟主线程并发调 driver,放大连接池避免 urllib3 刷"pool full"警告
        _enlarge_driver_pool(driver, pool_size=10)

        # 先把窗口摆到指定槽位(双账号: 左半屏 / 右半屏),录屏才能录到正确区域
        _apply_window_layout(driver, account, slot_index, slot_total)

        # 浏览器一开,立刻全程录屏 Edge 窗口区域,直到 finally 关闭浏览器
        try:
            from core.screen_recorder import EdgeWindowRecorder
            recorder = EdgeWindowRecorder(driver, account=account, log_dir=_cfg("LOG_DIR") or "logs")
            recorder.start()
        except Exception as rec_err:
            logger.warning("⚠️ [%s] 录屏启动失败,继续无录屏运行: %s", account, rec_err)
            recorder = None

        if session_deadline:
            watchdog_thread = threading.Thread(
                target=_watch_session_deadline,
                args=(driver, account, session_index, session_deadline, stop_event, watchdog_cancel),
                daemon=True,
            )
            watchdog_thread.start()
        auth = Authenticator(driver)

        if not auth.login(account, password, session_stop):
            if stop_event.is_set():
                return "stopped"
            if session_stop.deadline_reached():
                logger.info(
                    "🛑 [%s] 第 %d 轮浏览器会话已到截止时间 %s，准备重启浏览器。",
                    account,
                    session_index,
                    session_deadline.strftime("%H:%M:%S"),
                )
            else:
                logger.error("❌ [%s] 第 %d 轮浏览器会话登录失败。", account, session_index)
            return "restart"

        booker = SeatBooker(driver, account=account)
        pre_navigated = False

        if wait_for_fire and schedule:
            target_campus = _cfg('TARGET_CAMPUS')
            if enter_room(driver, target_campus, TARGET_ROOM):
                pre_navigated = True
                logger.info(
                    "🎯 [%s] 第 %d 轮已提前进入目标自习室，等待 %s 准时锁座...",
                    account,
                    session_index,
                    schedule["pre_fire_at"].strftime("%H:%M:%S"),
                )
            else:
                logger.warning("⚠️ [%s] 第 %d 轮预进入自习室失败，将在开抢时重试进入。", account, session_index)
                if not enter_room(driver, target_campus, TARGET_ROOM):
                    logger.error("❌ [%s] 第 %d 轮二次进入自习室仍失败，重启。", account, session_index)
                    return "restart"

            # === 定时模式核心：6:29:50 触发验证码 / 6:30:00 点确定 / 10 优先级回退 ===
            start_time_cfg = start_time
            end_time_cfg = end_time
            outcome, target_seat = run_timed_priority_attack(
                driver,
                booker,
                account,
                start_time_cfg,
                end_time_cfg,
                schedule,
                session_stop,
                stop_event,
            )
            if outcome == "stopped":
                return "stopped"
            if outcome == "success":
                _notify_success(account, TARGET_ROOM, target_seat, start_time_cfg, end_time_cfg)
                return "success"
            if outcome == "all_failed":
                # 用户要求：第 10 优先级也失败 → 程序停止
                logger.info("🛑 [%s] 全部 10 个优先级抢座失败，程序终止当前账号任务。", account)
                stop_event.set()
                return "stopped"
            # outcome == "restart"
            return "restart"

        # 立即模式：进入自习室 → 直接走优先级抢座
        target_campus = _cfg('TARGET_CAMPUS')
        if not enter_room(driver, target_campus, TARGET_ROOM):
            logger.error("❌ [%s] 进入自习室失败。", account)
            return "restart"

        outcome, target_seat = run_timed_priority_attack(
            driver,
            booker,
            account,
            start_time,
            end_time,
            None,  # 无 schedule，直接抢
            session_stop,
            stop_event,
        )
        if outcome == "stopped":
            return "stopped"
        if outcome == "success":
            _notify_success(account, TARGET_ROOM, target_seat, start_time, end_time)
            return "success"
        # all_failed 或 restart 都按"全部失败"对待 → 不再重启
        logger.info("🛑 [%s] 立即模式 10 个优先级座位全部失败，退出。", account)
        stop_event.set()
        return "stopped"

    except Exception as e:
        logger.exception("❌ [%s] 第 %d 轮浏览器会话崩溃: %s", account, session_index, e)
        if stop_event.is_set():
            return "stopped"
        return "restart"
    finally:
        watchdog_cancel.set()
        if watchdog_thread:
            watchdog_thread.join(timeout=1)
        # 关浏览器之前先停录屏(否则窗口已经被销毁,最后几帧会取到桌面)
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                pass
        _close_driver_quietly(driver)


def thread_task(account, password, time_config, stop_event: threading.Event, state=True,
                slot_index=0, slot_total=1):
    """
    单个账号的执行逻辑（单浏览器会话，无重启）：
      - 定时模式：等到 prep_at(6:29:00) 启动浏览器，6:29:50 触发验证码，6:30:00 点确定
      - 立即模式：直接启动浏览器开抢
      - 10 个优先级座位逐个尝试，每个座位 10 次验证码机会
      - 全部失败 → 退出
    """
    start_time = time_config["start"]
    end_time = time_config["end"]

    schedule = None
    if state:
        schedule_mode = _cfg('SCHEDULE_MODE', 'strict')
        if schedule_mode == 'custom':
            schedule = build_custom_schedule(
                _cfg('SCHEDULE_HOUR', 6),
                _cfg('SCHEDULE_MINUTE', 30),
            )
        else:
            schedule = build_strict_schedule()

    if schedule:
        logger.info(
            "🗓️ [%s] 日程: %s | 准备 %s → 触发验证码 %s → 点确定 %s | 截止 %s",
            account,
            schedule["run_date"].isoformat(),
            schedule["prep_at"].strftime("%H:%M:%S"),
            schedule["pre_fire_at"].strftime("%H:%M:%S"),
            schedule["fire_at"].strftime("%H:%M:%S"),
            schedule["close_at"].strftime("%H:%M:%S"),
        )
        logger.info("🚀 [%s] 单浏览器会话策略：10 个优先级座位逐个尝试，每个座位最多 10 次验证码机会。", account)

    try:
        if state and schedule:
            ok = wait_until(schedule["prep_at"], account, stop_event, "准备启动浏览器")
            if not ok or stop_event.is_set():
                return

            result = run_browser_session(
                account,
                password,
                start_time,
                end_time,
                stop_event,
                schedule=schedule,
                session_deadline=None,
                wait_for_fire=True,
                session_index=1,
                slot_index=slot_index,
                slot_total=slot_total,
            )
            logger.info("🛑 [%s] 抢座任务结束（结果: %s）。", account, result)
            return

        # 立即模式：直接开抢，无重启
        logger.info("🚀 [%s] 立即模式：单浏览器会话，10 个优先级座位逐个尝试，每个 10 次验证码机会。", account)
        if stop_event.is_set():
            return
        result = run_browser_session(
            account,
            password,
            start_time,
            end_time,
            stop_event,
            schedule=None,
            session_deadline=None,
            wait_for_fire=False,
            session_index=1,
            slot_index=slot_index,
            slot_total=slot_total,
        )
        logger.info("🛑 [%s] 抢座任务结束（结果: %s）。", account, result)
        return

    except Exception as e:
        logger.exception("❌ [%s] 线程崩溃: %s", account, e)

def main(stop_event: threading.Event = None):
    """
    主入口。支持从外部传入 stop_event 以实现优雅停止。
    """
    USERS = _cfg('USERS', {})
    TARGET_ROOM = _cfg('TARGET_ROOM')
    state = _cfg('WAIT_FOR_0630', True)

    logger.info("🚀 LNU-LibSeat-Automation 启动...")
    logger.info("🎯 目标: %s", TARGET_ROOM)
    if state:
        logger.info("🕒 定时模式已启用，将在指定时间准时抢座。")
    else:
        logger.info("🕒 立即模式: 马上启动浏览器并直接执行抢座流程。")

    threads = []
    if stop_event is None:
        stop_event = threading.Event()

    try:
        slot_total = len(USERS)
        for slot_index, (account, info) in enumerate(USERS.items()):
            t = threading.Thread(
                target=thread_task,
                args=(account, info["password"], info["time"], stop_event, state),
                kwargs={"slot_index": slot_index, "slot_total": slot_total},
                daemon=True,
            )
            threads.append(t)
            t.start()
            time.sleep(5)  # 错开 5 秒启动，避免并发请求触发反爬

        # 主线程阻塞等待，支持 Ctrl+C 优雅退出
        while any(t.is_alive() for t in threads):
            try:
                time.sleep(0.5)
            except KeyboardInterrupt:
                logger.info("🛑 收到中断信号，通知所有线程停止...")
                stop_event.set()
                break

    finally:
        stop_event.set()
        for t in threads:
            t.join(timeout=5)
        logger.info("✅ 所有线程已结束，主进程退出。")


if __name__ == "__main__":
    main()
