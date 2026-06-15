"""
Collect click-captcha images into dataset/click3.

The script opens the normal reservation captcha modal, saves target/bg/modal
images, refreshes the captcha, and repeats inside a Beijing-time window. It
does not click captcha answers or submit the final reservation confirmation.
"""

from __future__ import annotations

import argparse
import base64
import logging
import random
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Iterable

from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config
from core import utils
from core.driver import get_driver
from logic.auth import Authenticator
from logic.booker import SeatBooker
from logic.navigator import enter_room


DEFAULT_DATASET_DIR = Path("dataset") / "click3"
# 采集账号不在源码硬编码（避免泄露真实学号）：默认读取本地 config.USERS 的账号，
# 或通过 --account 显式传入。见 resolve_account_jobs()。
DEFAULT_CRAWL_ACCOUNTS: tuple[str, ...] = ()
DEFAULT_CRAWL_PASSWORD = "000000"  # 图书馆系统通用默认密码；真实密码请放 config.USERS
SAMPLE_DIR_RE = re.compile(r"^sample_(\d+)$")
TARGET_SELECTOR = ".captcha-modal-click img.captcha-text"
BG_SELECTOR = ".captcha-modal-content img"
MODAL_SELECTOR = ".captcha-modal-container"


def parse_clock(value: str) -> dt_time:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise argparse.ArgumentTypeError("Use HH:MM or HH:MM:SS")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        return dt_time(hour, minute, second)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use numeric HH:MM or HH:MM:SS") from exc


def beijing_now() -> datetime:
    return utils.get_beijing_time()


def build_window(start_clock: dt_time, end_clock: dt_time) -> tuple[datetime, datetime]:
    now = beijing_now()
    start_at = now.replace(
        hour=start_clock.hour,
        minute=start_clock.minute,
        second=start_clock.second,
        microsecond=0,
    )
    end_at = now.replace(
        hour=end_clock.hour,
        minute=end_clock.minute,
        second=end_clock.second,
        microsecond=0,
    )
    if end_at <= start_at:
        end_at += timedelta(days=1)
    if now > end_at:
        start_at += timedelta(days=1)
        end_at += timedelta(days=1)
    return start_at, end_at


def sleep_until(target: datetime, label: str) -> None:
    while True:
        remaining = (target - beijing_now()).total_seconds()
        if remaining <= 0:
            return
        if remaining > 60:
            logging.info("Waiting for %s: %.1f minutes left", label, remaining / 60)
        else:
            logging.info("Waiting for %s: %.1f seconds left", label, remaining)
        time.sleep(min(30.0, max(0.2, remaining)))


def sleep_until_or_end(target: datetime, end_at: datetime) -> bool:
    deadline = min(target, end_at)
    while True:
        remaining = (deadline - beijing_now()).total_seconds()
        if remaining <= 0:
            return beijing_now() < end_at
        time.sleep(min(0.5, max(0.05, remaining)))


def next_sample_index(dataset_dir: Path) -> int:
    max_index = 0
    if not dataset_dir.exists():
        return 1
    for child in dataset_dir.iterdir():
        if not child.is_dir():
            continue
        match = SAMPLE_DIR_RE.match(child.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def decode_data_url(src: str) -> bytes | None:
    if not src or "base64" not in src:
        return None
    try:
        payload = src.split(",", 1)[1]
        return base64.b64decode(payload)
    except Exception:
        return None


def image_key(target_src: str, bg_src: str) -> str:
    return f"{target_src[-160:]}|{bg_src[-160:]}"


def wait_for_captcha_images(driver, timeout: float, previous_key: str = ""):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            target_el = driver.find_element(By.CSS_SELECTOR, TARGET_SELECTOR)
            bg_el = driver.find_element(By.CSS_SELECTOR, BG_SELECTOR)
            target_src = target_el.get_attribute("src") or ""
            bg_src = bg_el.get_attribute("src") or ""
            target_bytes = decode_data_url(target_src)
            bg_bytes = decode_data_url(bg_src)
            key = image_key(target_src, bg_src)
            if target_bytes and bg_bytes and key != previous_key:
                return target_bytes, bg_bytes, key
        except Exception:
            pass
        time.sleep(0.08)
    return None, None, ""


def save_sample(driver, dataset_dir: Path, sample_index: int, previous_key: str = "") -> str:
    target_bytes, bg_bytes, key = wait_for_captcha_images(driver, timeout=3.0, previous_key=previous_key)
    if not target_bytes or not bg_bytes:
        raise RuntimeError("captcha images are not ready")

    sample_name = f"sample_{sample_index:05d}"
    sample_dir = dataset_dir / sample_name
    tmp_dir = dataset_dir / f".{sample_name}_tmp_{time.time_ns()}"
    all_dir = dataset_dir / "all"
    tmp_dir.mkdir(parents=True, exist_ok=False)

    modal_path = tmp_dir / f"{sample_name}_modal.png"
    target_path = tmp_dir / f"{sample_name}_target.png"
    bg_path = tmp_dir / f"{sample_name}_bg.png"

    try:
        try:
            modal_el = driver.find_element(By.CSS_SELECTOR, MODAL_SELECTOR)
            modal_el.screenshot(str(modal_path))
        except Exception:
            driver.save_screenshot(str(modal_path))

        target_path.write_bytes(target_bytes)
        bg_path.write_bytes(bg_bytes)

        tmp_dir.rename(sample_dir)
        all_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sample_dir / modal_path.name, all_dir / modal_path.name)
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    return key


def current_captcha_key(driver) -> str:
    try:
        target_src = driver.find_element(By.CSS_SELECTOR, TARGET_SELECTOR).get_attribute("src") or ""
        bg_src = driver.find_element(By.CSS_SELECTOR, BG_SELECTOR).get_attribute("src") or ""
        return image_key(target_src, bg_src)
    except Exception:
        return ""


def refresh_captcha(booker: SeatBooker, driver, previous_key: str) -> str:
    booker._refresh_click_captcha()
    _, _, new_key = wait_for_captcha_images(driver, timeout=3.0, previous_key=previous_key)
    return new_key


def soft_refresh_captcha(booker: SeatBooker, driver, previous_key: str, attempts: int, timeout: float) -> str:
    if not booker.is_captcha_popup_present():
        return ""

    for attempt in range(1, max(1, attempts) + 1):
        try:
            booker._refresh_click_captcha()
            _, _, new_key = wait_for_captcha_images(driver, timeout=timeout, previous_key=previous_key)
            if new_key and new_key != previous_key:
                if attempt > 1:
                    logging.info("Soft captcha refresh recovered after %d attempts", attempt)
                return new_key
        except Exception as exc:
            logging.debug("Soft captcha refresh attempt %d failed: %s", attempt, exc)
        time.sleep(0.12)
    return ""


def split_seats(raw_values: Iterable[str] | None) -> list[str]:
    seats: list[str] = []
    for raw in raw_values or []:
        for item in raw.split(","):
            seat = item.strip()
            if seat:
                seats.append(seat)
    return seats


def default_time_config() -> dict:
    users = getattr(config, "USERS", {}) or {}
    for info in users.values():
        time_config = (info or {}).get("time") or {}
        if time_config.get("start") and time_config.get("end"):
            return time_config
    return {"start": "9:00", "end": "15:00"}


def resolve_account_jobs(account_args: Iterable[str] | None, password: str | None) -> list[tuple[str, str]]:
    users = getattr(config, "USERS", {}) or {}
    accounts = split_seats(account_args)
    if not accounts:
        # 默认采集本地 config.USERS 中配置的账号；DEFAULT_CRAWL_ACCOUNTS 默认为空。
        accounts = list(DEFAULT_CRAWL_ACCOUNTS) or list(users.keys())

    jobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for account in accounts:
        if account in seen:
            continue
        seen.add(account)
        info = users.get(account, {}) or {}
        account_password = password or info.get("password") or DEFAULT_CRAWL_PASSWORD
        jobs.append((account, account_password))
    return jobs


def seat_candidates(booker: SeatBooker, explicit_seats: list[str], shuffle: bool) -> list[str]:
    if explicit_seats:
        seats = explicit_seats[:]
    else:
        seats = [str(seat).strip() for seat in (getattr(config, "PREFER_SEATS", []) or []) if str(seat).strip()]
        if not seats:
            seats = booker.get_available_seats()

    deduped = list(dict.fromkeys(str(seat).strip() for seat in seats if str(seat).strip()))
    if shuffle:
        random.shuffle(deduped)
    return deduped


def open_captcha_modal(
    driver,
    booker: SeatBooker,
    seats: list[str],
    start_time: str,
    end_time: str,
    end_at: datetime,
    retry_sleep: float,
) -> tuple[bool, str | None]:
    if booker.is_captcha_popup_present():
        return True, None

    while beijing_now() < end_at:
        for seat in seats:
            if beijing_now() >= end_at:
                return False, None

            logging.info("Trying seat %s to open captcha modal", seat)
            if not booker.select_time_and_wait(seat, start_time, end_time):
                continue

            booker.current_seat = seat
            if booker.fire_submit_trigger():
                try:
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, MODAL_SELECTOR))
                    )
                    wait_for_captcha_images(driver, timeout=3.0)
                    return True, seat
                except TimeoutException:
                    logging.warning("Submit trigger did not open captcha modal for seat %s", seat)

            try:
                booker.close_popup()
            except Exception:
                pass

        logging.info("No captcha modal yet; retrying in %.1fs", retry_sleep)
        if not sleep_until_or_end(beijing_now() + timedelta(seconds=retry_sleep), end_at):
            return False, None

    return False, None


def close_driver_quietly(driver) -> None:
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


def reset_captcha_flow(driver, booker: SeatBooker) -> None:
    try:
        booker._close_captcha_modal()
    except Exception:
        pass
    try:
        driver.execute_script(
            "var buttons = document.querySelectorAll('.captcha-modal-footer button');"
            "if (buttons && buttons.length) { buttons[0].click(); }"
        )
    except Exception:
        pass
    time.sleep(0.2)
    try:
        booker.close_popup()
    except Exception:
        pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect click3 captcha dataset samples.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET_DIR), help="Dataset directory to append to.")
    parser.add_argument("--window-start", type=parse_clock, default=parse_clock("06:28"), help="Beijing time HH:MM.")
    parser.add_argument("--window-end", type=parse_clock, default=parse_clock("06:37"), help="Beijing time HH:MM.")
    parser.add_argument("--target-count", type=int, default=0, help="Stop after N new samples; 0 means until window end.")
    parser.add_argument("--interval", type=float, default=0.35, help="Seconds to wait after each refresh.")
    parser.add_argument("--retry-sleep", type=float, default=1.0, help="Seconds between seat/modal retry rounds.")
    parser.add_argument("--reopen-after-failures", type=int, default=10, help="Hard-reopen captcha modal after N consecutive image-read failures.")
    parser.add_argument("--refresh-attempts", type=int, default=4, help="Soft refresh attempts before giving up on the current captcha modal.")
    parser.add_argument("--refresh-timeout", type=float, default=1.2, help="Seconds to wait for each soft captcha refresh.")
    parser.add_argument("--prep-seconds", type=float, default=120.0, help="Start browser/login this many seconds before the window.")
    parser.add_argument("--account", action="append", help="Account(s), comma separated. Can be repeated. Defaults to the built-in 8 accounts.")
    parser.add_argument("--password", default=None, help="Password for all accounts. Defaults to 000000.")
    parser.add_argument("--max-workers", type=int, default=len(DEFAULT_CRAWL_ACCOUNTS), help="Maximum concurrent browser sessions.")
    parser.add_argument("--stagger-start", type=float, default=0.0, help="Seconds to stagger browser session startup.")
    parser.add_argument("--campus", default=None, help="Override config.TARGET_CAMPUS.")
    parser.add_argument("--room", default=None, help="Override config.TARGET_ROOM.")
    parser.add_argument("--seat", action="append", help="Seat number(s), comma separated. Can be repeated.")
    parser.add_argument("--start-time", default=None, help="Reservation start time. Defaults to account config.")
    parser.add_argument("--end-time", default=None, help="Reservation end time. Defaults to account config.")
    parser.add_argument("--shuffle-seats", action="store_true", help="Shuffle candidate seats before retrying.")
    parser.add_argument("--no-wait", action="store_true", help="Start immediately if before the configured window.")
    return parser.parse_args(argv)


def run_account(
    args: argparse.Namespace,
    account: str,
    password: str,
    dataset_root: Path,
    start_at: datetime,
    end_at: datetime,
    campus: str,
    room: str,
    start_time: str,
    end_time: str,
) -> tuple[str, int, int]:
    dataset_dir = dataset_root / account
    dataset_dir.mkdir(parents=True, exist_ok=True)

    driver = None
    saved_count = 0
    sample_index = next_sample_index(dataset_dir)
    last_saved_key = ""
    fail_streak = 0

    try:
        logging.info("[%s] Existing samples: %d", account, sample_index - 1)
        driver = get_driver(None)
        driver.maximize_window()

        auth = Authenticator(driver)
        if not auth.login(account, password, maintenance_mode="retry_later"):
            raise RuntimeError(f"Login failed: {auth.last_failure_reason or 'unknown'}")

        if not enter_room(driver, campus, room, account=account):
            raise RuntimeError("Failed to enter target room")

        booker = SeatBooker(driver, account=account)
        seats = seat_candidates(booker, split_seats(args.seat), args.shuffle_seats)
        if not seats:
            raise RuntimeError("No candidate seats found")
        logging.info("[%s] Seat candidates: %s", account, ", ".join(seats[:20]) + (" ..." if len(seats) > 20 else ""))

        if beijing_now() < start_at:
            sleep_until(start_at, f"{account} collection window")

        while beijing_now() < end_at:
            if args.target_count and saved_count >= args.target_count:
                break

            opened, active_seat = open_captcha_modal(
                driver,
                booker,
                seats,
                start_time,
                end_time,
                end_at,
                retry_sleep=max(0.1, args.retry_sleep),
            )
            if not opened:
                break
            if active_seat:
                logging.info("[%s] Captcha modal opened from seat %s", account, active_seat)

            try:
                saved_key = save_sample(driver, dataset_dir, sample_index, previous_key=last_saved_key)
            except Exception as exc:
                fail_streak += 1
                logging.warning("[%s] Save sample_%05d failed: %s", account, sample_index, exc)
                if (dataset_dir / f"sample_{sample_index:05d}").exists():
                    sample_index = next_sample_index(dataset_dir)

                if booker.is_captcha_popup_present() and fail_streak < max(1, args.reopen_after_failures):
                    refreshed_key = soft_refresh_captcha(
                        booker,
                        driver,
                        last_saved_key,
                        attempts=max(1, args.refresh_attempts),
                        timeout=max(0.2, args.refresh_timeout),
                    )
                    if refreshed_key:
                        logging.info("[%s] Recovered current captcha modal with soft refresh", account)
                    else:
                        logging.warning(
                            "[%s] Soft refresh did not produce ready captcha images; keeping current modal open",
                            account,
                        )
                    time.sleep(0.15)
                    continue

                if fail_streak >= max(1, args.reopen_after_failures) or not booker.is_captcha_popup_present():
                    logging.warning(
                        "[%s] Hard-reopening captcha modal after %d consecutive image-read failures",
                        account,
                        fail_streak,
                    )
                    reset_captcha_flow(driver, booker)
                    last_saved_key = ""
                    fail_streak = 0
                    time.sleep(0.3)
                    continue

                time.sleep(0.2)
                continue

            last_saved_key = saved_key
            fail_streak = 0
            saved_count += 1
            logging.info("[%s] Saved sample_%05d (%d new)", account, sample_index, saved_count)
            sample_index += 1

            if args.target_count and saved_count >= args.target_count:
                break
            if beijing_now() >= end_at:
                break

            refreshed_key = soft_refresh_captcha(
                booker,
                driver,
                last_saved_key,
                attempts=max(1, args.refresh_attempts),
                timeout=max(0.2, args.refresh_timeout),
            )
            if not refreshed_key:
                logging.warning("[%s] Refresh after save did not produce a new captcha image", account)
            time.sleep(max(0.0, args.interval))

        logging.info(
            "[%s] Finished. Saved %d new samples. Total samples now: %d",
            account,
            saved_count,
            next_sample_index(dataset_dir) - 1,
        )
        return account, saved_count, 0

    except KeyboardInterrupt:
        logging.warning("[%s] Interrupted by user. Saved %d new samples.", account, saved_count)
        return account, saved_count, 130
    except Exception as exc:
        logging.exception("[%s] Crawler failed: %s", account, exc)
        return account, saved_count, 1
    finally:
        close_driver_quietly(driver)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    dataset_root = Path(args.dataset)
    dataset_root.mkdir(parents=True, exist_ok=True)

    time_config = default_time_config()
    start_time = args.start_time or time_config.get("start")
    end_time = args.end_time or time_config.get("end")
    if not start_time or not end_time:
        raise SystemExit("Reservation start/end time is required via config.USERS or --start-time/--end-time")

    campus = args.campus or getattr(config, "TARGET_CAMPUS", "")
    room = args.room or getattr(config, "TARGET_ROOM", "")
    if not campus or not room:
        raise SystemExit("Target campus/room is required in config.py or via --campus/--room")

    account_jobs = resolve_account_jobs(args.account, args.password)
    if not account_jobs:
        raise SystemExit("No accounts configured for crawling")
    if args.max_workers <= 0:
        raise SystemExit("--max-workers must be greater than 0")

    start_at, end_at = build_window(args.window_start, args.window_end)
    if args.no_wait and beijing_now() < start_at:
        start_at = beijing_now()

    logging.info("Accounts: %s", ", ".join(account for account, _ in account_jobs))
    logging.info("Room: %s -> %s", campus, room)
    logging.info("Dataset root: %s", dataset_root.resolve())
    logging.info(
        "Window: %s -> %s Beijing time",
        start_at.strftime("%Y-%m-%d %H:%M:%S"),
        end_at.strftime("%Y-%m-%d %H:%M:%S"),
    )

    prep_at = start_at - timedelta(seconds=max(0.0, args.prep_seconds))
    if beijing_now() < prep_at:
        sleep_until(prep_at, "browser prep")

    max_workers = min(args.max_workers, len(account_jobs))
    failures = 0
    total_saved = 0
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for account, password in account_jobs:
                future = executor.submit(
                    run_account,
                    args,
                    account,
                    password,
                    dataset_root,
                    start_at,
                    end_at,
                    campus,
                    room,
                    start_time,
                    end_time,
                )
                futures[future] = account
                if args.stagger_start > 0:
                    time.sleep(args.stagger_start)

            for future in as_completed(futures):
                account = futures[future]
                try:
                    _, saved_count, code = future.result()
                except Exception as exc:
                    logging.exception("[%s] Worker crashed: %s", account, exc)
                    failures += 1
                    continue
                total_saved += saved_count
                if code != 0:
                    failures += 1

    except KeyboardInterrupt:
        logging.warning("Interrupted by user. Worker threads will close their browsers when they exit.")
        return 130

    logging.info("All workers finished. Saved %d new samples across %d accounts.", total_saved, len(account_jobs))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
