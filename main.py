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
PREP_LEAD_SECONDS = 45  # 在 fire_at 前多少秒开始准备（启动浏览器+登录+选座）


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
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": run_date,
        "prep_at": prep_at,
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
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": fire_at.date(),
        "prep_at": prep_at,
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


def attempt_seat_selection(driver, booker, account, start_time, end_time, stop_event, schedule):
    """
    进入房间 + 遍历偏好座位选座。
    优先座位全部不可用时，随机选同自习室的其他可用座位。
    成功返回座位号字符串，失败返回 None。
    """
    TARGET_CAMPUS = _cfg('TARGET_CAMPUS')
    TARGET_ROOM = _cfg('TARGET_ROOM')
    PREFER_SEATS = _cfg('PREFER_SEATS', [])

    if schedule and is_after_close(schedule["close_at"]):
        logger.info("🛑 [%s] 已超过当日系统关闭时间 %s，停止。", account, schedule["close_at"].strftime("%H:%M:%S"))
        return None

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


def thread_task(account, password, time_config, stop_event: threading.Event, state=True):
    """
    单个账号的执行逻辑。
    严格模式流程：提前登录/导航/选座 → 29分就绪 → 6:30:00 准时提交。
    """
    from core.driver import get_driver

    start_time = time_config["start"]
    end_time = time_config["end"]
    TARGET_ROOM = _cfg('TARGET_ROOM')

    # 使用完全纯净卫生的新建无痕浏览器，没有任何历史记录（就像 GitHub 原版一样）
    driver = None

    # 根据模式构建日程
    schedule = None
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
        logger.info(
            "🗓️ [%s] 定时模式日程: %s | 准备 %s → 提交 %s | 截止 %s",
            account,
            schedule["run_date"].isoformat(),
            schedule["prep_at"].strftime("%H:%M:%S"),
            schedule["fire_at"].strftime("%H:%M:%S"),
            schedule["close_at"].strftime("%H:%M:%S"),
        )

    try:
        # ───────────────────────────────────────
        # 阶段 0：等待准备时刻，然后顺序执行：浏览器→登录→选座
        # ───────────────────────────────────────
        if state and schedule:
            ok = wait_until(schedule["prep_at"], account, stop_event, "准备就绪")
            if not ok:
                return

        if stop_event.is_set():
            return

        driver = get_driver(None)
        auth = Authenticator(driver)

        if not auth.login(account, password, stop_event):
            logger.error("❌ [%s] 登录失败，线程退出", account)
            return

        booker = SeatBooker(driver)

        # ───────────────────────────────────────
        # 阶段 2：导航 & 选座（循环直到成功锁定座位）
        # ───────────────────────────────────────
        target_seat = None
        while not stop_event.is_set():
            try:
                target_seat = attempt_seat_selection(driver, booker, account, start_time, end_time, stop_event, schedule)
                if target_seat or stop_event.is_set():
                    break
            except Exception as e:
                logger.warning("⚠️ [%s] 阶段2异常: %s，正在恢复...", account, e)
                logger.exception("Traceback:")
                try:
                    driver.refresh()
                    if stop_event.wait(timeout=2):
                        break
                except Exception:
                    logger.exception("刷新失败")

        if not target_seat or stop_event.is_set():
            logger.info("✅ [%s] 线程退出（未进入确认阶段）。", account)
            return

        # ───────────────────────────────────────
        # 阶段 3：等待提交时机
        # ───────────────────────────────────────
        logger.info("🎯 [%s] 座位 %s 已锁定！准备进入提交阶段...", account, target_seat)

        if schedule and is_after_close(schedule["close_at"]):
            logger.info("🛑 [%s] 已超过当日系统关闭时间 %s，放弃提交。", account, schedule["close_at"].strftime("%H:%M:%S"))
            return

        if state and schedule:
            ok = wait_until(schedule["fire_at"], account, stop_event, "确认提交")
            if not ok:
                return

        # 开火提交
        booker.fire_submit()

        # ───────────────────────────────────────
        # 阶段 4：检查结果 & 失败后重试循环
        # ───────────────────────────────────────
        if booker.check_result():
            logger.info("🎉🎉🎉 [%s] 抢座成功！任务结束！", account)

            title_str, success_msg = build_success_email(account, TARGET_ROOM, target_seat, start_time, end_time)
            if not send_email(title_str, success_msg):
                logger.warning("📧 [%s] 邮件发送失败！", account)
            return

        # 首次提交失败，进入重试循环
        logger.info("😭 [%s] 首次提交失败（可能被抢），进入重试...", account)
        try:
            driver.find_element("class name", "close-icon").click()
        except Exception:
            pass
        try:
            driver.refresh()
        except Exception:
            logger.exception("刷新失败")

        while not stop_event.is_set():
            try:
                if stop_event.wait(timeout=0.5):
                    break

                retry_seat = attempt_seat_selection(driver, booker, account, start_time, end_time, stop_event, schedule)
                if stop_event.is_set():
                    break
                if not retry_seat:
                    continue

                booker.fire_submit()

                if booker.check_result():
                    logger.info("🎉🎉🎉 [%s] 重试抢座成功！", account)
                    title_str, success_msg = build_success_email(account, TARGET_ROOM, retry_seat, start_time, end_time)
                    if not send_email(title_str, success_msg):
                        logger.warning("📧 [%s] 邮件发送失败！", account)
                    break
                else:
                    logger.info("😭 [%s] 重试提交失败，继续...", account)
                    try:
                        driver.find_element("class name", "close-icon").click()
                    except Exception:
                        pass
                    try:
                        driver.refresh()
                    except Exception:
                        logger.exception("刷新失败")

            except Exception as e:
                logger.warning("⚠️ [%s] 重试异常: %s", account, e)
                logger.exception("Traceback:")
                try:
                    driver.refresh()
                    if stop_event.wait(timeout=2):
                        break
                except Exception:
                    logger.exception("刷新失败")

        logger.info("✅ [%s] 线程退出主循环。", account)

    except Exception as e:
        logger.exception("❌ [%s] 线程崩溃: %s", account, e)
    finally:
        try:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        except Exception:
            logger.exception("关闭 driver 时出错")

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
