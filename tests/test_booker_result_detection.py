from selenium.webdriver.common.by import By

from logic.booker import SeatBooker, _classify_booking_result


class FakeElement:
    def __init__(self, text, displayed=True):
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


def make_booker(driver):
    booker = SeatBooker.__new__(SeatBooker)
    booker.driver = driver
    return booker


def test_booking_result_ignores_notice_blacklist_text():
    driver = FakeDriver(page_source="公告：连续或7天内累计3次违约，将被列入黑名单7天")

    assert make_booker(driver)._get_booking_result_text() == ""


def test_booking_result_reads_failure_toast_over_notice_text():
    toast = "预约失败，请尽快选择其他时段或座位"
    driver = FakeDriver(
        {
            (By.CSS_SELECTOR, ".el-message .el-message__content"): [
                FakeElement(toast),
            ],
        },
        page_source="公告：连续或7天内累计3次违约，将被列入黑名单7天",
    )

    result_text = make_booker(driver)._get_booking_result_text()

    assert result_text == toast
    assert _classify_booking_result(result_text) == "failed"


def test_booking_result_keeps_real_blacklist_feedback_as_stop_status():
    text = "对不起，您已被加入黑名单，预约权限将在2026年05月11日恢复。 原因：7天内迟到违约，超过3次，加入黑名单7天"

    assert _classify_booking_result(text) == "blacklist"


def test_booking_result_accepts_variable_blacklist_restore_date():
    text = "对不起，您已被加入黑名单，预约权限将在2027年1月2日恢复。原因：7天内迟到违约，超过3次，加入黑名单7天"

    assert _classify_booking_result(text) == "blacklist"


def test_booking_result_does_not_stop_on_generic_blacklist_rule_text():
    text = "连续或7天内累计3次违约，将被列入黑名单7天"

    assert _classify_booking_result(text) == "failed"


def test_booking_result_does_not_stop_on_incomplete_blacklist_text():
    text = "账号已被加入黑名单，暂不能预约"

    assert _classify_booking_result(text) == "failed"
