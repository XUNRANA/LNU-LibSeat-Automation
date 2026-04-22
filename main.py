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

STRICT_NEXT_DAY_CUTOFF = dt_time(10, 0, 0)
SYSTEM_CLOSE_TIME = dt_time(22, 0, 0)
PREP_LEAD_SECONDS = 90  # 在 fire_at 前多少秒开始准备（启动浏览器+登录+选座）
PRE_SUBMIT_SECONDS = 10  # 在 fire_at 前多少秒点击"立即预约"（触发验证码）
CAPTCHA_CLICK_SECONDS = 2  # 在 fire_at 前多少秒点击验证码文字
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

        booker = SeatBooker(driver)
        pre_navigated = False

        if wait_for_fire and schedule:
            target_campus = _cfg('TARGET_CAMPUS')
            if enter_room(driver, target_campus, TARGET_ROOM):
                pre_navigated = True
                logger.info(
                    "🎯 [%s] 第 %d 轮已提前进入目标自习室，等待 %s 准时点座...",
                    account,
                    session_index,
                    schedule["fire_at"].strftime("%H:%M:%S"),
                )
            else:
                logger.warning("⚠️ [%s] 第 %d 轮预进入自习室失败，将在开抢时重试进入。", account, session_index)

            ok = wait_until(schedule["fire_at"], account, session_stop, "开始抢座")
            if not ok:
                if stop_event.is_set():
                    return "stopped"
                return "restart"

        target_seat = None
        first_attempt = True
        while not session_stop.is_set():
            try:
                navigate = not (wait_for_fire and first_attempt and pre_navigated)
                target_seat = attempt_seat_selection(
                    driver,
                    booker,
                    account,
                    start_time,
                    end_time,
                    session_stop,
                    schedule,
                    navigate=navigate,
                )
                first_attempt = False
                if target_seat or session_stop.is_set():
                    break
            except Exception as e:
                logger.warning("⚠️ [%s] 第 %d 轮选座异常: %s，正在恢复...", account, session_index, e)
                logger.exception("Traceback:")
                try:
                    driver.refresh()
                    if session_stop.wait(timeout=2):
                        break
                except Exception:
                    logger.exception("刷新失败")

        if not target_seat or session_stop.is_set():
            if stop_event.is_set():
                return "stopped"
            if session_stop.deadline_reached():
                logger.info(
                    "🛑 [%s] 第 %d 轮在 %s 前未锁定到可提交座位。",
                    account,
                    session_index,
                    session_deadline.strftime("%H:%M:%S"),
                )
            return "restart"

        logger.info("🎯 [%s] 座位 %s 已锁定！准备进入提交阶段...", account, target_seat)

        if schedule and is_after_close(schedule["close_at"]):
            logger.info("🛑 [%s] 已超过当日系统关闭时间 %s，放弃提交。", account, schedule["close_at"].strftime("%H:%M:%S"))
            return "restart"

        if not booker.fire_submit():
            logger.warning("⚠️ [%s] 提交流程未完成，进入结果检查与重试流程", account)

        if booker.check_result():
            logger.info("🎉🎉🎉 [%s] 抢座成功！任务结束！", account)
            _notify_success(account, TARGET_ROOM, target_seat, start_time, end_time)
            return "success"

        logger.info("😭 [%s] 第 %d 轮首次提交失败，继续在本轮浏览器会话内重试...", account, session_index)
        try:
            driver.find_element("class name", "close-icon").click()
        except Exception:
            pass
        try:
            driver.refresh()
        except Exception:
            logger.exception("刷新失败")

        while not session_stop.is_set():
            try:
                if session_stop.wait(timeout=0.5):
                    break

                retry_seat = attempt_seat_selection(
                    driver,
                    booker,
                    account,
                    start_time,
                    end_time,
                    session_stop,
                    schedule,
                )
                if session_stop.is_set():
                    break
                if not retry_seat:
                    continue

                booker.fire_submit()

                if booker.check_result():
                    logger.info("🎉🎉🎉 [%s] 第 %d 轮浏览器会话重试抢座成功！", account, session_index)
                    _notify_success(account, TARGET_ROOM, retry_seat, start_time, end_time)
                    return "success"

                logger.info("😭 [%s] 第 %d 轮重试提交失败，继续...", account, session_index)
                try:
                    driver.find_element("class name", "close-icon").click()
                except Exception:
                    pass
                try:
                    driver.refresh()
                except Exception:
                    logger.exception("刷新失败")

            except Exception as e:
                logger.warning("⚠️ [%s] 第 %d 轮重试异常: %s", account, session_index, e)
                logger.exception("Traceback:")
                try:
                    driver.refresh()
                    if session_stop.wait(timeout=2):
                        break
                except Exception:
                    logger.exception("刷新失败")

        if stop_event.is_set():
            return "stopped"
        if session_stop.deadline_reached():
            logger.info(
                "🛑 [%s] 第 %d 轮浏览器会话达到截止时间 %s，准备强制退出并重启浏览器。",
                account,
                session_index,
                session_deadline.strftime("%H:%M:%S"),
            )
        return "restart"

    except Exception as e:
        logger.exception("❌ [%s] 第 %d 轮浏览器会话崩溃: %s", account, session_index, e)
        if stop_event.is_set():
            return "stopped"
        return "restart"
    finally:
        watchdog_cancel.set()
        if watchdog_thread:
            watchdog_thread.join(timeout=1)
        _close_driver_quietly(driver)


def thread_task(account, password, time_config, stop_event: threading.Event, state=True):
    """
    单个账号的执行逻辑。
    严格模式流程：提前登录/预进入房间 → 6:30:00 准时点座并立即提交流程。
    """
    start_time = time_config["start"]
    end_time = time_config["end"]

    # 根据模式构建日程
    schedule = None
    schedule_mode = 'strict'
    if state:
        schedule_mode = _cfg('SCHEDULE_MODE', 'strict')  # strict / custom
        if schedule_mode == 'custom':
            schedule = build_custom_schedule(
                _cfg('SCHEDULE_HOUR', 6),
                _cfg('SCHEDULE_MINUTE', 30),
            )
        else:
            schedule = build_strict_schedule()

    if schedule:
        session_plan = build_browser_session_plan(schedule, schedule_mode)
        deadline_preview = ", ".join(ts.strftime("%H:%M:%S") for ts in session_plan["session_deadlines"])
        logger.info(
            "🗓️ [%s] 日程: %s | 准备 %s → 开抢(点座+验证码+确定) %s | 截止 %s",
            account,
            schedule["run_date"].isoformat(),
            schedule["prep_at"].strftime("%H:%M:%S"),
            schedule["fire_at"].strftime("%H:%M:%S"),
            schedule["close_at"].strftime("%H:%M:%S"),
        )
        logger.info(
            "🔁 [%s] 浏览器重启策略: 每轮 %d 分钟，最多 %d 轮，整体抢到 %s 为止。",
            account,
            BROWSER_SESSION_WINDOW_MINUTES,
            len(session_plan["session_deadlines"]),
            session_plan["overall_end"].strftime("%H:%M:%S"),
        )
        logger.info("🔁 [%s] 浏览器强制重启时间点: %s", account, deadline_preview)
    else:
        session_plan = None

    try:
        if state and schedule:
            session_deadlines = session_plan["session_deadlines"]
            for session_index, session_deadline in enumerate(session_deadlines, start=1):
                session_start = schedule["prep_at"] if session_index == 1 else session_deadlines[session_index - 2]
                stage_name = "准备第1轮浏览器会话" if session_index == 1 else f"启动第{session_index}轮浏览器会话"

                ok = wait_until(session_start, account, stop_event, stage_name)
                if not ok:
                    return
                if stop_event.is_set():
                    return

                result = run_browser_session(
                    account,
                    password,
                    start_time,
                    end_time,
                    stop_event,
                    schedule=schedule,
                    session_deadline=session_deadline,
                    wait_for_fire=(session_index == 1),
                    session_index=session_index,
                )
                if result in ("success", "stopped"):
                    return

                if session_index < len(session_deadlines):
                    logger.info(
                        "🔄 [%s] 第 %d 轮浏览器会话结束，将在 %s 从头重启浏览器继续抢座。",
                        account,
                        session_index,
                        session_deadline.strftime("%H:%M:%S"),
                    )

            logger.info(
                "🛑 [%s] 已到整体截止时间 %s，且最多只重启 %d 轮浏览器，任务结束。",
                account,
                session_plan["overall_end"].strftime("%H:%M:%S"),
                len(session_deadlines),
            )
            return

        logger.info(
            "🔁 [%s] 立即模式浏览器重启策略: 每轮 %d 分钟，最多 %d 轮；到点无论卡在哪一步都强制退出浏览器并重启。",
            account,
            BROWSER_SESSION_WINDOW_MINUTES,
            BROWSER_SESSION_MAX_ATTEMPTS,
        )
        for session_index in range(1, BROWSER_SESSION_MAX_ATTEMPTS + 1):
            if stop_event.is_set():
                return

            session_deadline = utils.get_beijing_time() + timedelta(minutes=BROWSER_SESSION_WINDOW_MINUTES)
            logger.info(
                "🔁 [%s] 立即模式第 %d/%d 轮开始，本轮硬截止 %s。",
                account,
                session_index,
                BROWSER_SESSION_MAX_ATTEMPTS,
                session_deadline.strftime("%H:%M:%S"),
            )

            result = run_browser_session(
                account,
                password,
                start_time,
                end_time,
                stop_event,
                schedule=None,
                session_deadline=session_deadline,
                wait_for_fire=False,
                session_index=session_index,
            )
            if result in ("success", "stopped"):
                return

            if session_index < BROWSER_SESSION_MAX_ATTEMPTS:
                logger.info(
                    "🔄 [%s] 立即模式第 %d 轮结束，立刻重启浏览器进入下一轮。",
                    account,
                    session_index,
                )

        logger.info(
            "🛑 [%s] 立即模式已达到最多 %d 轮浏览器会话，任务结束。",
            account,
            BROWSER_SESSION_MAX_ATTEMPTS,
        )
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
        for account, info in USERS.items():
            t = threading.Thread(
                target=thread_task,
                args=(account, info["password"], info["time"], stop_event, state),
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
