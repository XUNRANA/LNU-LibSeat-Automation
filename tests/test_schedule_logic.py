import threading
from datetime import datetime, timedelta, timezone

import main


BJ = timezone(timedelta(hours=8))


def bj_time(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=BJ)


def test_build_custom_schedule_before_target_runs_today():
    # 当前时间早于目标 6:30 → 当天触发
    schedule = main.build_custom_schedule(6, 30, bj_time(2026, 3, 26, 5, 0, 0))

    assert schedule["run_date"].isoformat() == "2026-03-26"
    assert schedule["fire_at"] == bj_time(2026, 3, 26, 6, 30, 0)
    assert schedule["prep_at"] == bj_time(2026, 3, 26, 6, 29, 30)  # fire - 30s
    assert schedule["seat_lock_at"] == bj_time(2026, 3, 26, 6, 29, 54)  # fire - 6s


def test_build_custom_schedule_at_or_after_target_rolls_to_tomorrow():
    # 当前时间已到/过目标 6:30 → 顺延到次日（now >= fire_at 即翻天）
    schedule = main.build_custom_schedule(6, 30, bj_time(2026, 3, 26, 6, 30, 0))

    assert schedule["run_date"].isoformat() == "2026-03-27"
    assert schedule["fire_at"] == bj_time(2026, 3, 27, 6, 30, 0)
    assert schedule["prep_at"] == bj_time(2026, 3, 27, 6, 29, 30)
    assert schedule["seat_lock_at"] == bj_time(2026, 3, 27, 6, 29, 54)


def test_build_custom_schedule_uses_lead_constants():
    # prep/seat_lock 偏移由模块常量驱动，避免硬编码漂移
    schedule = main.build_custom_schedule(11, 25, bj_time(2026, 3, 26, 11, 0, 0))

    fire_at = schedule["fire_at"]
    assert fire_at == bj_time(2026, 3, 26, 11, 25, 0)
    assert schedule["prep_at"] == fire_at - timedelta(seconds=main.PREP_LEAD_SECONDS)
    assert schedule["seat_lock_at"] == fire_at - timedelta(seconds=main.SEAT_LOCK_LEAD_SECONDS)


def test_wait_until_returns_immediately_when_target_has_passed(monkeypatch):
    now = bj_time(2026, 3, 26, 6, 30, 1)
    target = bj_time(2026, 3, 26, 6, 30, 0)
    monkeypatch.setattr(main.utils, "get_beijing_time", lambda: now)

    assert main.wait_until(target, "test_account", threading.Event(), "确认提交") is True


def test_wait_until_returns_false_when_stop_event_already_set(monkeypatch):
    # 目标在未来，但 stop_event 进入时已置位 → 两个等待循环都跳过，
    # 末尾 stop_event.is_set() 命中 → 返回 False（不发生真实 sleep）。
    now = bj_time(2026, 3, 26, 5, 0, 0)
    target = bj_time(2026, 3, 26, 6, 30, 0)  # 1.5h 后
    monkeypatch.setattr(main.utils, "get_beijing_time", lambda: now)

    ev = threading.Event()
    ev.set()
    assert main.wait_until(target, "test_account", ev, "确认提交") is False


class _SignalDuringWait:
    """模拟等待期间才收到停止信号：进入循环时未置位，wait() 立即返回 True。"""

    def is_set(self):
        return False

    def wait(self, timeout=None):
        return True


def test_wait_until_aborts_when_signal_arrives_during_long_sleep(monkeypatch):
    # 目标远在未来(>5s)→ 进入长睡分块循环，wait() 期间收到信号 → 返回 False。
    now = bj_time(2026, 3, 26, 5, 0, 0)
    target = bj_time(2026, 3, 26, 6, 30, 0)
    monkeypatch.setattr(main.utils, "get_beijing_time", lambda: now)

    assert main.wait_until(target, "test_account", _SignalDuringWait(), "确认提交") is False


def test_build_custom_schedule_rolls_across_year_boundary():
    # 当前已过当天目标且处于年末 → fire_at 顺延到次年
    schedule = main.build_custom_schedule(6, 30, bj_time(2026, 12, 31, 23, 0, 0))

    assert schedule["run_date"].isoformat() == "2027-01-01"
    assert schedule["fire_at"] == bj_time(2027, 1, 1, 6, 30, 0)
    assert schedule["seat_lock_at"] == bj_time(2027, 1, 1, 6, 29, 54)
