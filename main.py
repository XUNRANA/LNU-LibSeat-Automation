# python
import threading
import time

# --- 模块导入（延迟导入 config，支持 GUI 动态注入） ---
import core.utils as utils
from logic.auth import Authenticator
from logic.navigator import enter_room
from logic.booker import SeatBooker
from core.logger import get_logger, register_account_log_file
from core.notifications import build_success_email, send_email

from datetime import time as dt_time
from datetime import timedelta


def _cfg(attr, default=None):
    import config
    return getattr(config, attr, default)


logger = get_logger(__name__)

PREP_LEAD_SECONDS = 30  # 6:29:30 打开浏览器：fire_at 前 30s 启动并登录+进入自习室
SEAT_LOCK_LEAD_SECONDS = 6  # fire_at 前 6s 点击座位并选好时间（锁定需 3-4s，留余量保证准时）
MAINTENANCE_RETRY_INTERVAL_SECONDS = 120  # 维护期重试间隔：每 2 分钟重启浏览器再试

_CAPTCHA_PRELOAD_THREAD = None


def _start_captcha_model_preload(reason: str = "scheduled") -> None:
    """Start one background warmup for the local YOLO4+Siamese captcha model."""
    global _CAPTCHA_PRELOAD_THREAD
    if _CAPTCHA_PRELOAD_THREAD is not None and _CAPTCHA_PRELOAD_THREAD.is_alive():
        return

    def _worker():
        try:
            from logic.booker import preload_yolo4_siamese_model

            logger.info("🧠 本地 YOLO4+Siamese 验证码模型开始预加载 (%s)...", reason)
            preload_yolo4_siamese_model("preload")
        except Exception as exc:
            logger.warning("⚠️ 本地 YOLO4+Siamese 验证码模型预加载线程异常: %s", exc)

    _CAPTCHA_PRELOAD_THREAD = threading.Thread(
        target=_worker,
        name="captcha-yolo4-siamese-preload",
        daemon=True,
    )
    _CAPTCHA_PRELOAD_THREAD.start()


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
    seat_lock_at = fire_at - timedelta(seconds=SEAT_LOCK_LEAD_SECONDS)

    return {
        "run_date": fire_at.date(),
        "prep_at": prep_at,
        "seat_lock_at": seat_lock_at,
        "fire_at": fire_at,
    }


def wait_until(target_time, account, stop_event: threading.Event, stage_name: str):
    """
    改进的绝对时间等待逻辑：
    - 如果目标时间已过，立即继续，不顺延到次日
    - 否则分段等待，降低 CPU 占用，并响应 stop_event
    """
    now = utils.get_beijing_time()
    if now >= target_time:
        # 目标时间已过 → 改 DEBUG，避免循环里反复刷屏
        logger.debug(
            "⏩ [%s] %s目标时间已过 (%s)，立即继续。",
            account,
            stage_name,
            target_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        )
        return True

    wait_seconds = (target_time - now).total_seconds()

    logger.info(
        "⏳ [%s] 当前: %s -> %s: %s",
        account,
        now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        stage_name,
        target_time.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
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


def _apply_window_layout(driver, account):
    """浏览器窗口最大化"""
    try:
        driver.maximize_window()
        time.sleep(0.3)
        size = driver.get_window_size()
        w, h = size.get('width', 0), size.get('height', 0)
        logger.info("🪟 [%s] 窗口 %dx%d", account, w, h)
    except Exception as e:
        logger.warning("⚠️ [%s] 最大化失败: %s", account, e)


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


def _notify_success(account, room, seat, start_time, end_time):
    title_str, success_msg = build_success_email(account, room, seat, start_time, end_time)
    if not send_email(title_str, success_msg):
        logger.warning("📧 [%s] 邮件发送失败！", account)


def _terminal_outcome_from_result(account, seat, result):
    """把 check_result 的 dict 映射为 run_timed_priority_attack 的终态返回值。

    终态:
      - stop / blacklist -> ("stopped", None)
      - success          -> ("success", seat)
    非终态（failed / retry_captcha 等）返回 None，交由调用方继续处理。
    """
    status = result.get("status")
    if status == "stop":
        logger.error("🛑 [%s] 收到系统可预约时间限制提示，立即停止抢座: %s", account, result.get("text", ""))
        return ("stopped", None)
    if status == "blacklist":
        logger.error("🛑 [%s] 账号已被加入黑名单！立刻停止抢座: %s", account, result.get("text", ""))
        return ("stopped", None)
    if status == "success":
        logger.info("🎉🎉🎉 [%s] 座位 %s 抢座成功！", account, seat)
        return ("success", seat)
    return None


def _attempt_seat(booker, account, seat, idx, start_time, end_time,
                  fire_at, fire_at_passed, session_stop):
    """尝试单个座位的完整流程（锁座 → 触发 → 验证码循环 → 结果检查）。

    返回 (outcome, fire_at_passed)：
      - outcome 为终态元组 ("stopped"/"success", ...) 时，调用方应直接 return 它
      - outcome 为 None 时，表示换下一个座位（外层 continue）
    fire_at_passed 可能在本次调用中被置 True（首个成功锁座后等过 fire_at），故回传。
    """
    # 0.5) 确保在座位图页面（预约失败后可能停留在错误页面）
    booker.ensure_on_seat_grid()

    # 0.6) 清除上一个座位残留的 toast，避免 page_source 误扫到旧的失败提示
    booker._dismiss_stale_messages()

    # 1) 锁定座位（弹时间选择框 + 选时间）
    if not booker.select_time_and_wait(seat, start_time, end_time):
        # 失败原因已由 booker 内部以 WARNING 单源记录，这里只换下一个座位
        logger.info("🔄 [%s] 座位 %s 锁定失败，换下一个座位。", account, seat)
        return None, fire_at_passed

    # 2) 定时模式：第一次成功锁定时，等到 fire_at+1s 再触发立即预约
    if not fire_at_passed:
        ok = wait_until(fire_at, account, session_stop,
                        f"等待 {fire_at.strftime('%H:%M:%S')} 准点触发预约")
        fire_at_passed = True
        if not ok:
            booker.close_popup()
            return ("stopped", None), fire_at_passed
        time.sleep(2)  # 延迟 2s，确保服务器已切到放座状态

    # 3) 触发"立即预约" → 弹出验证码弹窗
    if not booker.fire_submit_trigger():
        logger.warning("⚠️ [%s] 座位 %s 触发提交失败，关闭弹窗换下一个座位。", account, seat)
        booker.close_popup()
        return None, fire_at_passed

    # 4) 验证码循环：本地 YOLO4+Siamese 每个座位最多 10 次
    booker.current_priority = idx
    booker.current_seat = seat
    booker.current_retry = 0
    max_retries = booker.get_captcha_max_retries()
    captcha_passed = False
    submit_rejected = False
    booker.last_booking_result_status = ""
    booker.last_booking_result_text = ""

    for retry in range(1, max_retries + 1):
        if session_stop.is_set():
            return ("stopped", None), fire_at_passed

        # 清除上一轮残留的 toast，避免 page_source 误扫到旧的"验证码错误"
        if retry > 1:
            booker._dismiss_stale_messages()

        booker.current_seat = seat
        booker.current_retry = retry
        logger.info(
            "🔁 [%s] 座位 %s 第 %d/%d 次验证码尝试...",
            account, seat, retry, max_retries,
        )

        # 4a) 获取验证码并解析
        solve_data = booker.pre_solve_captcha()
        if solve_data.get("no_captcha"):
            logger.info("ℹ️ [%s] 未检测到验证码弹窗，直接进入结果检查。", account)
            captcha_passed = True
            break
        if solve_data.get("outside_model_window"):
            logger.warning("⚠️ [%s] 当前不在 06:30:00-06:35:00，本地模型不接入；结束当前座位尝试。", account)
            submit_rejected = True
            break
        if not solve_data.get("solved"):
            logger.warning("⚠️ [%s] 第 %d 次模型返回 False，火速刷新验证码。", account, retry)
            booker._refresh_click_captcha(previous_key=solve_data.get("captcha_key", ""), wait_timeout=1.0)
            continue

        # 4b) 直接闪电提交（不再分段等待）
        booker.last_stop_reason = ""
        confirm_ok = booker.fire_captcha_blitz(solve_data)

        # 4c) 检查结果
        if confirm_ok:
            result = booker.check_result()
            status = result.get("status")
            booker._save_screenshot(f"4_result_{status}")

            outcome = _terminal_outcome_from_result(account, seat, result)
            if outcome is not None:
                return outcome, fire_at_passed

            if status == "retry_captcha":
                logger.warning(
                    "⚠️ [%s] 第 %d 次收到可重试反馈【%s】，准备继续当前座位。",
                    account, retry, result.get("text", ""),
                )
                if not booker.is_captcha_popup_present():
                    logger.warning("⚠️ [%s] 验证码或预约界面已消失，尝试重新锁定座位 %s", account, seat)
                    if not booker.select_time_and_wait(seat, start_time, end_time):
                        submit_rejected = True
                        break
                    if not booker.fire_submit_trigger():
                        submit_rejected = True
                        break
                    continue

                if booker.last_captcha_auto_refreshed:
                    booker.last_captcha_auto_refreshed = False
                    logger.info("🔄 [%s] 系统已刷新验证码，直接重新求解", account)
                else:
                    booker._refresh_click_captcha(previous_key=solve_data.get("captcha_key", ""), wait_timeout=1.0)
                continue

            submit_rejected = True
            break

        if getattr(booker, "last_stop_reason", ""):
            logger.error("🛑 [%s] 收到系统可预约时间限制提示，立即停止抢座: %s", account, booker.last_stop_reason)
            return ("stopped", None), fire_at_passed

        logger.warning("⚠️ [%s] 第 %d 次确认未通过，准备重试。", account, retry)

        if not booker.is_captcha_popup_present():
            logger.warning("⚠️ [%s] 验证码或预约界面已消失，尝试重新锁定座位 %s", account, seat)
            if not booker.select_time_and_wait(seat, start_time, end_time):
                submit_rejected = True
                break
            if not booker.fire_submit_trigger():
                submit_rejected = True
                break
            continue

        if booker.last_captcha_auto_refreshed:
            booker.last_captcha_auto_refreshed = False
            logger.info("🔄 [%s] 系统已刷新验证码，直接重新求解", account)
        else:
            booker._refresh_click_captcha(previous_key=solve_data.get("captcha_key", ""), wait_timeout=1.0)

    if submit_rejected:
        logger.warning("💔 [%s] 座位 %s 提交后被拒绝，换下一个座位。", account, seat)
        booker._close_captcha_modal()
        booker.close_popup()
        booker.ensure_on_seat_grid()
        return None, fire_at_passed

    if captcha_passed:
        result = booker.check_result()
        booker._save_screenshot(f"4_result_{result.get('status', 'unknown')}")

        outcome = _terminal_outcome_from_result(account, seat, result)
        if outcome is not None:
            return outcome, fire_at_passed

        logger.warning("💔 [%s] 座位 %s 提交后被拒绝，换下一个座位。", account, seat)
        booker._close_captcha_modal()
        booker.close_popup()
        return None, fire_at_passed

    logger.warning(
        "💔 [%s] 座位 %s 在 %d 次重试后仍未通过验证码，换下一个座位。",
        account, seat, max_retries,
    )
    booker._close_captcha_modal()
    booker.close_popup()
    return None, fire_at_passed


def run_timed_priority_attack(
    booker,
    account,
    start_time,
    end_time,
    schedule,
    session_stop,
    stop_event,
    session_dir=None,
):
    """
    "准点抢座"主流程（单浏览器会话）：

    - 定时模式 (schedule != None)：
        6:29:50 (pre_fire_at) 触发"立即预约" + 解析验证码 + 依次点击文字
        6:30:00 (fire_at)      点击验证码"确定"按钮提交
    - 立即模式 (schedule = None)：直接触发 + 解决 + 立即点确定
    - 每个座位最多 10 次验证码机会；超过则切到下一个座位
    - 全部座位都失败 → 退出，不重启浏览器

    返回:
      ("success", seat) | ("all_failed", None) | ("stopped", None)
    """
    PREFER_SEATS = _cfg('PREFER_SEATS', []) or []

    # 加载自习室座位清单，过滤不存在的首选座位
    import random
    import os as _os
    room_name = _cfg('TARGET_ROOM', '')
    info_file = _os.path.join('info', f'{room_name}.txt') if room_name else ''
    all_room_seats = []
    if _os.path.exists(info_file):
        with open(info_file, 'r', encoding='utf-8') as _f:
            all_room_seats = [line.strip() for line in _f if line.strip()]

    def _normalize_seat(s):
        """去前导零：001→1，A-06-1 不变"""
        s = str(s).strip()
        return str(int(s)) if s.isdigit() else s

    # 标准化后建立查找集合
    norm_room_set = {_normalize_seat(s) for s in all_room_seats}

    # 用户首选座位：标准化后匹配，不存在则跳过
    extended_seats = []
    for s in PREFER_SEATS:
        ns = _normalize_seat(s)
        if norm_room_set and ns not in norm_room_set:
            logger.info("⏭️ [%s] 座位 %s 不在 %s，跳过。", account, s, room_name)
        else:
            # 用标准化后的座位号（后续 select_time_and_wait 内部也会去前导零）
            extended_seats.append(ns)

    # 兜底：剩余座位随机打乱
    tried = set(extended_seats)
    fallback = [s for s in all_room_seats if s not in tried]
    random.shuffle(fallback)
    extended_seats.extend(fallback)

    if PREFER_SEATS:
        logger.info("📋 [%s] 首选 %d 个 + 兜底 %d 个座位已就绪。", account, len(extended_seats) - len(fallback), len(fallback))
    elif extended_seats:
        logger.info("📋 [%s] 未填首选座位，随机扫描 %s 全部 %d 个座位。", account, room_name, len(extended_seats))
    else:
        logger.warning("⚠️ [%s] 无可用座位（清单=%s），无法抢座。", account, info_file)
        return ("all_failed", None)

    # 写抢座顺序到会话文件夹
    if session_dir:
        try:
            with open(_os.path.join(session_dir, '抢座顺序.txt'), 'w', encoding='utf-8') as _f:
                _f.write(f"账号: {account}\n")
                _f.write(f"校区: {_cfg('TARGET_CAMPUS', '')}\n")
                _f.write(f"自习室: {room_name}\n")
                _f.write(f"时间: {utils.get_beijing_time().strftime('%Y-%m-%d %H:%M:%S')}\n")
                _f.write(f"开始: {start_time}  结束: {end_time}\n\n")
                _f.write("=== 抢座顺序 ===\n")
                n_pref = len(extended_seats) - len(fallback)
                for i, s in enumerate(extended_seats, 1):
                    tag = "首选" if i <= n_pref else "兜底"
                    _f.write(f"{i}. [{tag}] 座位 {s}\n")
                _f.write(f"\n共 {len(extended_seats)} 个座位待尝试\n")
        except Exception:
            pass  # 写文件失败不影响主流程

    seat_lock_at = schedule["seat_lock_at"] if schedule else None
    fire_at = schedule["fire_at"] if schedule else None

    # 0) 定时模式：在进入座位循环之前，先一次性等到 seat_lock_at
    if seat_lock_at is not None:
        ok = wait_until(seat_lock_at, account, session_stop,
                        f"等待 {seat_lock_at.strftime('%H:%M:%S')} 锁定座位")
        if not ok:
            return ("stopped", None)

    # fire_at 仅在"首个成功锁住"的座位上等一次，之后直接进入提交
    fire_at_passed = (fire_at is None)

    for idx, seat in enumerate(extended_seats, start=1):
        if session_stop.is_set():
            return ("stopped", None)

        n_preferred = len(extended_seats) - len(fallback)
        in_fallback = idx > n_preferred
        if in_fallback and idx == n_preferred + 1:
            logger.info("🔀 [%s] === 首选耗尽，开始随机扫描 %s 剩余座位 ===", account, room_name)
        logger.info("🎯 [%s] === 抢座位 %s ===", account, seat)

        outcome, fire_at_passed = _attempt_seat(
            booker, account, seat, idx, start_time, end_time,
            fire_at, fire_at_passed, session_stop,
        )
        if outcome is not None:
            return outcome

    logger.error(
        "❌ [%s] 全部 %d 个座位都已尝试，停止当前会话。",
        account, len(extended_seats),
    )
    return ("all_failed", None)


def run_browser_session(
    account,
    password,
    start_time,
    end_time,
    stop_event,
    schedule=None,
    wait_for_fire=False,
    slot_index=0,
    slot_total=1,
    maintenance_mode=None,
):
    from core.driver import get_driver

    TARGET_ROOM = _cfg('TARGET_ROOM')
    driver = None
    recorder = None

    try:
        logger.info("🌐 [%s] 浏览器会话启动。", account)

        # 创建本次会话专属文件夹，记录日志起始位置（只导出本次会话的日志）
        import os as _os2
        _session_ts = utils.get_beijing_time().strftime('%Y%m%d_%H%M%S')
        _session_dir = _os2.path.join(_cfg('LOG_DIR', 'logs'), 'sessions', f'{_session_ts}_{account}')
        _session_log_start = 0
        try:
            _os2.makedirs(_session_dir, exist_ok=True)
            _log_path = _os2.path.join(_cfg('LOG_DIR', 'logs'), f'lnu_seat_{account}.log')
            if _os2.path.exists(_log_path):
                _session_log_start = _os2.path.getsize(_log_path)
        except Exception:
            _session_dir = None

        driver = get_driver()
        _enlarge_driver_pool(driver, pool_size=10)
        _apply_window_layout(driver, account)
        time.sleep(0.3)  # 等窗口最大化生效后再录屏

        try:
            from core.screen_recorder import EdgeWindowRecorder
            recorder = EdgeWindowRecorder(driver, account=account, log_dir=_session_dir or _cfg("LOG_DIR") or "logs")
            recorder.start()
        except Exception as rec_err:
            logger.warning("⚠️ [%s] 录屏启动失败,继续无录屏运行: %s", account, rec_err)
            recorder = None

        auth = Authenticator(driver)

        effective_maintenance_mode = maintenance_mode
        if effective_maintenance_mode is None:
            effective_maintenance_mode = "stop"
            if wait_for_fire and schedule and utils.get_beijing_time() < schedule["fire_at"]:
                effective_maintenance_mode = "defer_until_fire"

        if not auth.login(account, password, stop_event, maintenance_mode=effective_maintenance_mode):
            if auth.last_failure_reason == "maintenance_defer":
                return "maintenance_retry_at_fire"
            if auth.last_failure_reason == "maintenance_retry_later":
                return "maintenance_retry_later"
            if stop_event.is_set():
                return "stopped"
            logger.error("❌ [%s] 浏览器会话登录失败。", account)
            return "stopped"

        booker = SeatBooker(driver, account=account)
        booker.session_dir = _session_dir  # 截图保存到会话文件夹

        if wait_for_fire and schedule:
            target_campus = _cfg('TARGET_CAMPUS')

            if enter_room(driver, target_campus, TARGET_ROOM, account=account):
                logger.info(
                    "🎯 [%s] 已提前进入目标自习室，等待 %s 锁定座位...",
                    account,
                    schedule["seat_lock_at"].strftime("%H:%M:%S"),
                )
            else:
                logger.warning("⚠️ [%s] 预进入自习室失败，将在开抢时重试进入。", account)
                if not enter_room(driver, target_campus, TARGET_ROOM, account=account):
                    logger.error("❌ [%s] 二次进入自习室仍失败。", account)
                    return "stopped"

            outcome, target_seat = run_timed_priority_attack(
                booker, account, start_time, end_time,
                schedule, stop_event, stop_event, session_dir=_session_dir,
            )
            if outcome == "stopped":
                return "stopped"
            if outcome == "success":
                _notify_success(account, TARGET_ROOM, target_seat, start_time, end_time)
                return "success"
            if outcome == "all_failed":
                logger.info("🛑 [%s] 全部首选座位抢座失败，程序终止当前账号任务。", account)
                return "stopped"
            return "stopped"

        target_campus = _cfg('TARGET_CAMPUS')
        if not enter_room(driver, target_campus, TARGET_ROOM, account=account):
            logger.error("❌ [%s] 进入自习室失败。", account)
            return "stopped"

        outcome, target_seat = run_timed_priority_attack(
            booker, account, start_time, end_time,
            None, stop_event, stop_event, session_dir=_session_dir,
        )
        if outcome == "stopped":
            return "stopped"
        if outcome == "success":
            _notify_success(account, TARGET_ROOM, target_seat, start_time, end_time)
            return "success"
        logger.info("🛑 [%s] 立即模式全部座位都已尝试，退出。", account)
        return "stopped"

    except Exception as e:
        logger.exception("❌ [%s] 浏览器会话崩溃: %s", account, e)
        return "stopped"
    finally:
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                pass
        # 仅导出本次会话的日志到会话文件夹（从记录位置到末尾）
        if _session_dir and _session_log_start >= 0:
            try:
                import os as _os3
                log_src = _os3.path.join(_cfg('LOG_DIR', 'logs'), f'lnu_seat_{account}.log')
                if _os3.path.exists(log_src):
                    with open(log_src, 'r', encoding='utf-8', errors='replace') as _lf:
                        _lf.seek(_session_log_start)
                        _new_lines = _lf.read()
                    if _new_lines:
                        with open(_os3.path.join(_session_dir, 'session.log'), 'w', encoding='utf-8') as _sf:
                            _sf.write(_new_lines)
            except Exception:
                pass
        _close_driver_quietly(driver)


def thread_task(account, password, time_config, stop_event: threading.Event, state=True,
                slot_index=0, slot_total=1):
    """
    单个账号的执行逻辑（单浏览器会话，无重启）：
      - 定时模式：等到 prep_at(6:29:00) 启动浏览器，6:29:50 触发验证码，6:30:00 点确定
      - 立即模式：直接启动浏览器开抢
      - 首选 + 兜底座位逐个尝试，每个座位 10 次验证码机会
      - 全部失败 → 退出
    """
    start_time = time_config["start"]
    end_time = time_config["end"]

    schedule = None
    if state:
        schedule = build_custom_schedule(
            _cfg('SCHEDULE_HOUR', 6),
            _cfg('SCHEDULE_MINUTE', 30),
        )

    if schedule:
        logger.info(
            "🗓️ [%s] 日程: %s | 准备 %s → 锁定座位 %s → 触发验证码 %s",
            account,
            schedule["run_date"].isoformat(),
            schedule["prep_at"].strftime("%H:%M:%S"),
            schedule["seat_lock_at"].strftime("%H:%M:%S"),
            schedule["fire_at"].strftime("%H:%M:%S"),
        )
        logger.info("🚀 [%s] 单浏览器会话策略：首选 + 兜底座位逐个尝试，每个座位最多 10 次验证码机会。", account)

    try:
        if state and schedule:
            # 按 slot 偏移 prep_at，避免多个浏览器同时初始化争抢资源
            prep_at = schedule["prep_at"] + timedelta(seconds=slot_index * 8)
            ok = wait_until(prep_at, account, stop_event, "准备启动浏览器")
            if not ok or stop_event.is_set():
                return

            result = run_browser_session(
                account, password, start_time, end_time, stop_event,
                schedule=schedule, wait_for_fire=True,
                slot_index=slot_index, slot_total=slot_total,
            )

            if result == "maintenance_retry_at_fire" and not stop_event.is_set():
                ok = wait_until(schedule["fire_at"], account, stop_event, "系统维护结束后重启浏览器")
                if not ok or stop_event.is_set():
                    return
                logger.info("🔄 [%s] 到达预约时刻，重启浏览器并立即抢座。", account)
                result = run_browser_session(
                    account, password, start_time, end_time, stop_event,
                    schedule=None, wait_for_fire=False,
                    slot_index=slot_index, slot_total=slot_total,
                    maintenance_mode="retry_later",
                )

            while result == "maintenance_retry_later" and not stop_event.is_set():
                now = utils.get_beijing_time()
                next_retry_at = now + timedelta(seconds=MAINTENANCE_RETRY_INTERVAL_SECONDS)

                ok = wait_until(next_retry_at, account, stop_event, "系统维护重试启动浏览器")
                if not ok or stop_event.is_set():
                    return

                logger.info("🔁 [%s] 系统仍在维护，按 2 分钟间隔重试。", account)
                result = run_browser_session(
                    account, password, start_time, end_time, stop_event,
                    schedule=None, wait_for_fire=False,
                    slot_index=slot_index, slot_total=slot_total,
                    maintenance_mode="retry_later",
                )

            logger.info("🛑 [%s] 抢座任务结束（结果: %s）。", account, result)
            return

        # 立即模式：直接开抢，无重启
        logger.info("🚀 [%s] 立即模式：单浏览器会话，首选 + 兜底座位逐个尝试，每个 10 次验证码机会。", account)
        if stop_event.is_set():
            return
        result = run_browser_session(
            account, password, start_time, end_time, stop_event,
            schedule=None, wait_for_fire=False,
            slot_index=slot_index, slot_total=slot_total,
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
    MAX_ACCOUNTS = int(_cfg('MAX_ACCOUNTS', 2))
    if len(USERS) > MAX_ACCOUNTS:
        logger.warning("⚠️ 当前配置了 %d 个账号，最多支持 %d 个；本次只启动前 %d 个。", len(USERS), MAX_ACCOUNTS, MAX_ACCOUNTS)
        USERS = dict(list(USERS.items())[:MAX_ACCOUNTS])
    TARGET_ROOM = _cfg('TARGET_ROOM')
    state = _cfg('WAIT_FOR_0630', True)

    logger.info("🚀 LNU-LibSeat-Automation 启动...")
    logger.info("🎯 目标: %s", TARGET_ROOM)
    if state:
        logger.info("🕒 定时模式已启用，将在指定时间准时抢座。")
        _start_captcha_model_preload("scheduled startup")
    else:
        logger.info("🕒 立即模式: 马上启动浏览器并直接执行抢座流程。")
        _start_captcha_model_preload("immediate startup")

    threads = []
    if stop_event is None:
        stop_event = threading.Event()

    try:
        slot_total = len(USERS)
        # 为每个账号单独开一个日志文件（主账号 / 副账号 全量分流）
        for account in USERS.keys():
            register_account_log_file(account)
        for slot_index, (account, info) in enumerate(USERS.items()):
            t = threading.Thread(
                target=thread_task,
                args=(account, info["password"], info["time"], stop_event, state),
                kwargs={"slot_index": slot_index, "slot_total": slot_total},
                daemon=True,
            )
            threads.append(t)
            t.start()
            # 不在主线程 sleep——每个线程各自等待自己的 prep_at（按 slot 偏移），避免浏览器并发初始化争抢资源

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
