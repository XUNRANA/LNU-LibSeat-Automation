"""抢座引擎核心 helper 单测。

覆盖本轮"4 个超长方法行为等价拆分"抽出的 helper，给抢座主链路补上回归网：
  - logic.booker.SeatBooker._flash_detect_after_submit  (Commit 4)
  - logic.booker.SeatBooker._scan_fast_fail_page         (Commit 2)
  - main._relock_if_popup_gone / _refresh_or_note_autorefresh (Commit 3)
  - main._setup_session_dir / _export_session_log        (Commit 1)
  - main._terminal_outcome_from_result                   (既有纯映射)

全部用轻量 fake（无真实浏览器），与 tests/test_booker_result_detection.py 同风格。
"""
import logging
import os

from selenium.webdriver.common.by import By

import main
from logic.booker import SeatBooker

# 真实黑名单文案（与 test_booker_result_detection.py 中一致，命中整段正则）
BLACKLIST_TEXT = (
    "对不起，您已被加入黑名单，预约权限将在2026年05月11日恢复。"
    " 原因：7天内迟到违约，超过3次，加入黑名单7天"
)


class FakeElement:
    def __init__(self, text="", displayed=True):
        self.text = text
        self._displayed = displayed

    def is_displayed(self):
        return self._displayed


class FakeDriver:
    def __init__(self, elements_by_selector=None, page_source=""):
        self.elements_by_selector = elements_by_selector or {}
        self.page_source = page_source

    def find_elements(self, by, selector):
        return self.elements_by_selector.get((by, selector), [])


def make_booker(driver=None, *, popup_present=False):
    """构造一个仅含被测方法所需状态的 SeatBooker（绕过 __init__）。"""
    booker = SeatBooker.__new__(SeatBooker)
    booker.driver = driver
    booker.account = "testacc"
    booker.log = logging.getLogger("test_booker_engine")
    booker.last_lock_failure_reason = ""
    booker.last_stop_reason = ""
    booker.last_booking_result_status = ""
    booker.last_booking_result_text = ""
    booker.last_captcha_auto_refreshed = False
    # 隔离副作用：截图设为 no-op，弹窗探测/关闭可控
    booker._save_screenshot = lambda tag="step": None
    booker.is_captcha_popup_present = lambda: popup_present
    booker.close_popup_calls = []
    booker.close_popup = lambda: booker.close_popup_calls.append(True)
    return booker


# ───────────────── _flash_detect_after_submit (Commit 4) ─────────────────

def test_flash_detect_captcha_wrong_with_popup_marks_autorefresh():
    booker = make_booker(popup_present=True)
    assert booker._flash_detect_after_submit("提示：验证码错误，请重试") is False
    assert booker.last_captcha_auto_refreshed is True


def test_flash_detect_captcha_wrong_without_popup_no_autorefresh():
    booker = make_booker(popup_present=False)
    assert booker._flash_detect_after_submit("验证码错误") is False
    assert booker.last_captcha_auto_refreshed is False


def test_flash_detect_blacklist_sets_stop_reason():
    booker = make_booker()
    assert booker._flash_detect_after_submit(BLACKLIST_TEXT) is False
    assert booker.last_stop_reason == "黑名单"


def test_flash_detect_success_returns_true():
    booker = make_booker()
    assert booker._flash_detect_after_submit("预约成功！座位已锁定") is True
    assert booker.last_booking_result_status == "success"


def test_flash_detect_stop_keyword_returns_false():
    # "有效预约" 经 classify → stop
    booker = make_booker()
    assert booker._flash_detect_after_submit("您已有有效预约") is False
    assert booker.last_stop_reason == "有效预约"


def test_flash_detect_no_terminal_returns_none():
    booker = make_booker()
    assert booker._flash_detect_after_submit("") is None
    assert booker._flash_detect_after_submit("页面加载中…") is None


# ───────────────── _scan_fast_fail_page (Commit 2) ─────────────────

def test_scan_fast_fail_hit_sets_reason_and_closes_box():
    driver = FakeDriver(
        {(By.CLASS_NAME, "reserve-box"): [FakeElement()]},
        page_source="该座位当前不可用",
    )
    booker = make_booker(driver)
    assert booker._scan_fast_fail_page("12", {"不可用": "该座位不可用，请选择其他座位"}) is True
    assert "被系统拒绝" in booker.last_lock_failure_reason
    assert booker.close_popup_calls == [True]  # 有 reserve-box → 关掉


def test_scan_fast_fail_hit_without_reserve_box_keeps_popup_closed():
    driver = FakeDriver(page_source="约满")
    booker = make_booker(driver)
    assert booker._scan_fast_fail_page("12", {}) is True
    assert booker.close_popup_calls == []  # 无 reserve-box → 不调用 close_popup


def test_scan_fast_fail_miss_returns_false():
    driver = FakeDriver(page_source="座位空闲，可预约")
    booker = make_booker(driver)
    assert booker._scan_fast_fail_page("12", {}) is False
    assert booker.last_lock_failure_reason == ""


# ───────────────── _relock_if_popup_gone (Commit 3) ─────────────────

class FakeBooker:
    def __init__(self, *, popup_present=True, select_ok=True, fire_ok=True,
                 auto_refreshed=False):
        self._popup = popup_present
        self._select_ok = select_ok
        self._fire_ok = fire_ok
        self.last_captcha_auto_refreshed = auto_refreshed
        self.select_calls = []
        self.fire_calls = 0
        self.refresh_calls = []

    def is_captcha_popup_present(self):
        return self._popup

    def select_time_and_wait(self, seat, start, end):
        self.select_calls.append((seat, start, end))
        return self._select_ok

    def fire_submit_trigger(self):
        self.fire_calls += 1
        return self._fire_ok

    def _refresh_click_captcha(self, previous_key="", wait_timeout=1.0):
        self.refresh_calls.append((previous_key, wait_timeout))


def test_relock_popup_still_present_returns_present_without_relocking():
    fb = FakeBooker(popup_present=True)
    assert main._relock_if_popup_gone(fb, "acc", "5", "21:00", "22:00") == "present"
    assert fb.select_calls == []  # 弹窗还在，不该重锁


def test_relock_gone_relock_success_returns_continue():
    fb = FakeBooker(popup_present=False, select_ok=True, fire_ok=True)
    assert main._relock_if_popup_gone(fb, "acc", "5", "21:00", "22:00") == "continue"
    assert fb.select_calls == [("5", "21:00", "22:00")]
    assert fb.fire_calls == 1


def test_relock_gone_select_fail_returns_break():
    fb = FakeBooker(popup_present=False, select_ok=False)
    assert main._relock_if_popup_gone(fb, "acc", "5", "21:00", "22:00") == "break"
    assert fb.fire_calls == 0  # 选座失败就不该触发提交


def test_relock_gone_fire_fail_returns_break():
    fb = FakeBooker(popup_present=False, select_ok=True, fire_ok=False)
    assert main._relock_if_popup_gone(fb, "acc", "5", "21:00", "22:00") == "break"


# ───────────────── _refresh_or_note_autorefresh (Commit 3) ─────────────────

def test_refresh_when_autorefreshed_resets_flag_without_manual_refresh():
    fb = FakeBooker(auto_refreshed=True)
    main._refresh_or_note_autorefresh(fb, "acc", {"captcha_key": "k1"})
    assert fb.last_captcha_auto_refreshed is False
    assert fb.refresh_calls == []  # 系统已刷新 → 不手动刷新


def test_refresh_when_not_autorefreshed_calls_manual_refresh():
    fb = FakeBooker(auto_refreshed=False)
    main._refresh_or_note_autorefresh(fb, "acc", {"captcha_key": "k9"})
    assert fb.refresh_calls == [("k9", 1.0)]


# ───────────────── _terminal_outcome_from_result (既有纯映射) ─────────────────

def test_terminal_outcome_stop():
    assert main._terminal_outcome_from_result("acc", "5", {"status": "stop"}) == ("stopped", None)


def test_terminal_outcome_blacklist():
    assert main._terminal_outcome_from_result("acc", "5", {"status": "blacklist"}) == ("stopped", None)


def test_terminal_outcome_success_carries_seat():
    assert main._terminal_outcome_from_result("acc", "42", {"status": "success"}) == ("success", "42")


def test_terminal_outcome_non_terminal_returns_none():
    assert main._terminal_outcome_from_result("acc", "5", {"status": "failed"}) is None
    assert main._terminal_outcome_from_result("acc", "5", {"status": "retry_captcha"}) is None
    assert main._terminal_outcome_from_result("acc", "5", {}) is None


# ───────────────── _setup_session_dir / _export_session_log (Commit 1) ─────────────────

def test_setup_session_dir_no_prior_log(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path), raising=False)
    session_dir, log_start = main._setup_session_dir("accA")
    assert session_dir is not None and os.path.isdir(session_dir)
    assert "sessions" in session_dir and "accA" in session_dir
    assert log_start == 0


def test_setup_session_dir_records_prior_log_size(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path), raising=False)
    logf = tmp_path / "lnu_seat_accB.log"
    logf.write_text("previous content\n", encoding="utf-8")
    _, log_start = main._setup_session_dir("accB")
    assert log_start == logf.stat().st_size > 0


def test_export_session_log_writes_slice_from_offset(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path), raising=False)
    logf = tmp_path / "lnu_seat_accC.log"
    # 写精确字节(避免 Windows text 模式把 \n 翻成 \r\n 错位偏移)
    logf.write_bytes(b"OLD\nNEW LINE\n")
    session_dir = tmp_path / "sess"
    session_dir.mkdir()
    main._export_session_log(str(session_dir), len(b"OLD\n"), "accC")
    assert (session_dir / "session.log").read_text(encoding="utf-8") == "NEW LINE\n"


def test_export_session_log_guard_skips_on_none_dir(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "LOG_DIR", str(tmp_path), raising=False)
    (tmp_path / "lnu_seat_accD.log").write_text("data\n", encoding="utf-8")
    # session_dir 为 None（建目录失败场景）→ 应直接跳过，不抛异常
    main._export_session_log(None, 0, "accD")
