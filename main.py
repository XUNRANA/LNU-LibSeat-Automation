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

# =================== 全局开关 ===================
FORCE_API_ALWAYS = False  # True=全天图鉴API / False=仅6:30-6:35用API
CHECK_RESERVATION = True  # True=登录后检查已预约/履约中/当天3次 / False=跳过检查
# ================================================

STRICT_NEXT_DAY_CUTOFF = dt_time(10, 0, 0)
SYSTEM_CLOSE_TIME = dt_time(22, 0, 0)
PREP_LEAD_SECONDS = 30  # 6:29:30 打开浏览器：fire_at 前 30s 启动并登录+进入自习室
SEAT_LOCK_LEAD_SECONDS = 6  # fire_at 前 6s 点击座位并选好时间（锁定需 3-4s，留余量保证准时）
FIRE_LEAD_MS = 150  # 抢座 RTT 补偿:提前 150ms 醒来,让 click 请求在 59.920 左右到达浏览器，确保早于 00.000
MAINTENANCE_RETRY_INTERVAL_SECONDS = 120  # 维护期重试间隔：每 2 分钟重启浏览器再试


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
    seat_lock_at = fire_at - timedelta(seconds=SEAT_LOCK_LEAD_SECONDS)
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": run_date,
        "prep_at": prep_at,
        "seat_lock_at": seat_lock_at,
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
    seat_lock_at = fire_at - timedelta(seconds=SEAT_LOCK_LEAD_SECONDS)
    close_at = fire_at.replace(hour=SYSTEM_CLOSE_TIME.hour, minute=SYSTEM_CLOSE_TIME.minute)

    return {
        "run_date": fire_at.date(),
        "prep_at": prep_at,
        "seat_lock_at": seat_lock_at,
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


def _apply_window_layout(driver, account, slot_index, slot_total):
    """浏览器窗口最大化"""
    try:
        driver.maximize_window()
        time.sleep(0.3)
        size = driver.get_window_size()
        w, h = size.get('width', 0), size.get('height', 0)
        logger.info("🪟 [%s] 窗口 %dx%d", account, w, h)
    except Exception as e:
        logger.warning("⚠️ [%s] 最大化失败: %s", account, e)
    except Exception as e:
        logger.warning("⚠️ [%s] 窗口设置失败: %s", account, e)


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


def run_timed_priority_attack(
    driver,
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
      ("success", seat) | ("all_failed", None) | ("stopped", None) | ("restart", None)
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
    raw_room_set = set(all_room_seats)
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
            if stop_event.is_set():
                return ("stopped", None)
            return ("restart", None)

    # fire_at 仅在"首个成功锁住"的座位上等一次，之后直接进入提交
    fire_at_passed = (fire_at is None)

    for idx, seat in enumerate(extended_seats, start=1):
        if session_stop.is_set():
            return ("stopped", None) if stop_event.is_set() else ("restart", None)

        n_preferred = len(extended_seats) - len(fallback)
        in_fallback = idx > n_preferred
        if in_fallback and idx == n_preferred + 1:
            logger.info("🔀 [%s] === 首选耗尽，开始随机扫描 %s 剩余座位 ===", account, room_name)
        logger.info("🎯 [%s] === 抢座位 %s ===", account, seat)

        # 1) 锁定座位（弹时间选择框 + 选时间）
        if not booker.select_time_and_wait(seat, start_time, end_time):
            # 失败原因已由 booker 内部以 WARNING 单源记录，这里只换下一个座位
            logger.info("🔄 [%s] 座位 %s 锁定失败，换下一个座位。", account, seat)
            continue

        # 2) 定时模式：第一次成功锁定时，再准点等到 fire_at 触发立即预约
        if not fire_at_passed:
            ok = wait_until(fire_at, account, session_stop,
                            f"等待 {fire_at.strftime('%H:%M:%S')} 准点触发预约")
            fire_at_passed = True
            if not ok:
                booker.close_popup()
                if stop_event.is_set():
                    return ("stopped", None)
                return ("restart", None)

        # 3) 触发"立即预约" → 弹出验证码弹窗
        if not booker.fire_submit_trigger():
            logger.warning("⚠️ [%s] 座位 %s 触发提交失败，关闭弹窗换下一个座位。", account, seat)
            booker.close_popup()
            continue

        # 4) 验证码循环：API 最多 5 次，本地 OCR 最多 10 次
        booker.current_priority = idx
        booker.current_seat = seat
        booker.current_retry = 0
        max_retries = booker.get_captcha_max_retries()
        captcha_passed = False
        submit_rejected = False

        for retry in range(1, max_retries + 1):
            if session_stop.is_set():
                if stop_event.is_set():
                    return ("stopped", None)
                return ("restart", None)

            booker.current_seat = seat
            booker.current_retry = retry
            logger.info(
                "🔁 [%s] 座位 %s 第 %d/%d 次验证码尝试...",
                account, seat, retry, max_retries,
            )

            # 4a) 获取验证码并解析
            solve_data = booker.pre_solve_captcha(max_retries=1)
            if solve_data.get("no_captcha"):
                logger.info("ℹ️ [%s] 未检测到验证码弹窗，直接进入结果检查。", account)
                captcha_passed = True
                break
            if not solve_data.get("solved"):
                logger.warning("⚠️ [%s] 第 %d 次解析失败，刷新验证码。", account, retry)
                booker._refresh_click_captcha()
                continue

            # 4b) 直接闪电提交（不再分段等待）
            confirm_ok = booker.fire_captcha_blitz(solve_data)

            # 4c) 检查结果
            if confirm_ok:
                result = booker.check_result()
                status = result.get("status")
                booker._save_screenshot(f"4_result_{status}")
                if status == "success":
                    logger.info("🎉🎉🎉 [%s] 座位 %s 抢座成功！", account, seat)
                    return ("success", seat)

                if status == "retry_captcha":
                    logger.warning(
                        "⚠️ [%s] 第 %d 次收到可重试反馈【%s】，准备继续当前座位。",
                        account, retry, result.get("text", ""),
                    )
                    if result.get("report_api_error"):
                        booker._report_api_error_safe(solve_data.get("api_id"))
                    
                    if not booker.is_captcha_popup_present():
                        logger.warning("⚠️ [%s] 验证码或预约界面已消失，尝试重新锁定座位 %s", account, seat)
                        if not booker.select_time_and_wait(seat, start_time, end_time):
                            submit_rejected = True
                            break
                        if not booker.fire_submit_trigger():
                            submit_rejected = True
                            break
                        continue

                    booker._refresh_click_captcha()
                    continue

                submit_rejected = True
                break
            
            logger.warning("⚠️ [%s] 第 %d 次确认未通过，准备重试。", account, retry)
            # API 识别错了 → 自动上报，5 分钟内退费
            booker._report_api_error_safe(solve_data.get("api_id"))
            
            if not booker.is_captcha_popup_present():
                logger.warning("⚠️ [%s] 验证码或预约界面已消失，尝试重新锁定座位 %s", account, seat)
                if not booker.select_time_and_wait(seat, start_time, end_time):
                    submit_rejected = True
                    break
                if not booker.fire_submit_trigger():
                    submit_rejected = True
                    break
                continue
            
            booker._refresh_click_captcha()

        if submit_rejected:
            logger.warning("💔 [%s] 座位 %s 提交后被拒绝，换下一个座位。", account, seat)
            booker._close_captcha_modal()
            booker.close_popup()
            continue

        if captcha_passed:
            result = booker.check_result()
            booker._save_screenshot(f"4_result_{result.get('status', 'unknown')}")
            if result.get("status") == "success":
                logger.info("🎉🎉🎉 [%s] 座位 %s 抢座成功！", account, seat)
                return ("success", seat)
            logger.warning("💔 [%s] 座位 %s 提交后被拒绝，换下一个座位。", account, seat)
            booker._close_captcha_modal()
            booker.close_popup()
            continue

        if not captcha_passed:
            logger.warning(
                "💔 [%s] 座位 %s 在 %d 次重试后仍未通过验证码，换下一个座位。",
                account, seat, max_retries,
            )
            booker._close_captcha_modal()
            booker.close_popup()
            continue

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

        # 创建本次会话专属文件夹
        import os as _os2
        _session_ts = utils.get_beijing_time().strftime('%Y%m%d_%H%M%S')
        _session_dir = _os2.path.join(_cfg('LOG_DIR', 'logs'), 'sessions', f'{_session_ts}_{account}')
        try:
            _os2.makedirs(_session_dir, exist_ok=True)
        except Exception:
            _session_dir = None

        driver = get_driver(None)
        _enlarge_driver_pool(driver, pool_size=10)
        _apply_window_layout(driver, account, slot_index, slot_total)
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
            return "restart"

        booker = SeatBooker(driver, account=account)
        booker.session_dir = _session_dir  # 截图保存到会话文件夹

        if wait_for_fire and schedule:
            target_campus = _cfg('TARGET_CAMPUS')

            if CHECK_RESERVATION and booker.has_active_reservation():
                logger.info("🛑 [%s] 账号已有有效预约，直接退出当前抢座会话！", account)
                return "stopped"

            if enter_room(driver, target_campus, TARGET_ROOM, account=account):
                logger.info(
                    "🎯 [%s] 已提前进入目标自习室，等待 %s 锁定座位...",
                    account,
                    schedule["seat_lock_at"].strftime("%H:%M:%S"),
                )
            else:
                logger.warning("⚠️ [%s] 预进入自习室失败，将在开抢时重试进入。", account)
                if not enter_room(driver, target_campus, TARGET_ROOM, account=account):
                    logger.error("❌ [%s] 二次进入自习室仍失败，重启。", account)
                    return "restart"

            outcome, target_seat = run_timed_priority_attack(
                driver, booker, account, start_time, end_time,
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
            return "restart"

        # 立即模式：先检查是否已有预约 → 进入自习室 → 直接抢座
        if CHECK_RESERVATION and booker.has_active_reservation():
            logger.info("🛑 [%s] 账号已有有效预约，直接退出当前抢座会话！", account)
            return "stopped"

        target_campus = _cfg('TARGET_CAMPUS')
        if not enter_room(driver, target_campus, TARGET_ROOM, account=account):
            logger.error("❌ [%s] 进入自习室失败。", account)
            return "restart"

        outcome, target_seat = run_timed_priority_attack(
            driver, booker, account, start_time, end_time,
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
        if stop_event.is_set():
            return "stopped"
        return "restart"
    finally:
        if recorder is not None:
            try:
                recorder.stop()
            except Exception:
                pass
        # 把本次会话的账号日志复制到会话文件夹
        if _session_dir:
            try:
                import shutil, os as _os3
                log_src = _os3.path.join(_cfg('LOG_DIR', 'logs'), f'lnu_seat_{account}.log')
                if _os3.path.exists(log_src):
                    shutil.copy2(log_src, _os3.path.join(_session_dir, 'session.log'))
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
            "🗓️ [%s] 日程: %s | 准备 %s → 锁定座位 %s → 触发验证码 %s | 截止 %s",
            account,
            schedule["run_date"].isoformat(),
            schedule["prep_at"].strftime("%H:%M:%S"),
            schedule["seat_lock_at"].strftime("%H:%M:%S"),
            schedule["fire_at"].strftime("%H:%M:%S"),
            schedule["close_at"].strftime("%H:%M:%S"),
        )
        logger.info("🚀 [%s] 单浏览器会话策略：首选 + 兜底座位逐个尝试，每个座位最多 10 次验证码机会。", account)

    try:
        if state and schedule:
            ok = wait_until(schedule["prep_at"], account, stop_event, "准备启动浏览器")
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
                close_at = schedule["close_at"]
                if now >= close_at:
                    logger.warning("🛑 [%s] 已到当日截止时间 %s，停止维护重试。", account, close_at.strftime("%H:%M:%S"))
                    result = "stopped"
                    break

                next_retry_at = now + timedelta(seconds=MAINTENANCE_RETRY_INTERVAL_SECONDS)
                if next_retry_at > close_at:
                    next_retry_at = close_at

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
