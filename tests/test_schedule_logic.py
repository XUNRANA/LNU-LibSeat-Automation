import threading
from datetime import datetime, timedelta, timezone

import main


BJ = timezone(timedelta(hours=8))


def bj_time(year, month, day, hour, minute, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=BJ)


def test_build_strict_schedule_before_10_targets_today():
    schedule = main.build_strict_schedule(bj_time(2026, 3, 26, 9, 59, 59))

    assert schedule["run_date"].isoformat() == "2026-03-26"
    assert schedule["prep_at"] == bj_time(2026, 3, 26, 6, 29, 15)
    assert schedule["fire_at"] == bj_time(2026, 3, 26, 6, 30, 0)
    assert schedule["close_at"] == bj_time(2026, 3, 26, 22, 0, 0)


def test_build_strict_schedule_at_10_targets_tomorrow():
    schedule = main.build_strict_schedule(bj_time(2026, 3, 26, 10, 0, 0))

    assert schedule["run_date"].isoformat() == "2026-03-27"
    assert schedule["prep_at"] == bj_time(2026, 3, 27, 6, 29, 15)
    assert schedule["fire_at"] == bj_time(2026, 3, 27, 6, 30, 0)
    assert schedule["close_at"] == bj_time(2026, 3, 27, 22, 0, 0)


def test_wait_until_returns_immediately_when_target_has_passed(monkeypatch):
    now = bj_time(2026, 3, 26, 6, 30, 1)
    target = bj_time(2026, 3, 26, 6, 30, 0)
    monkeypatch.setattr(main.utils, "get_beijing_time", lambda: now)

    assert main.wait_until(target, "test_account", threading.Event(), "确认提交") is True
