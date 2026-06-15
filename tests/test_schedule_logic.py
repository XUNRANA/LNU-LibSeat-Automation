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
