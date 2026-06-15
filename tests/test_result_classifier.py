"""logic.result_classifier 纯函数的分支覆盖。

现有 test_booker_result_detection.py 已覆盖 blacklist / failed 路径，
这里补 classify_booking_result 的 success / stop / retry_captcha 分支，
以及 is_stop_booking_feedback 的时段匹配与分隔符归一化。
"""
import pytest

from logic.result_classifier import (
    classify_booking_result,
    is_blacklist_feedback,
    is_stop_booking_feedback,
)


def test_success_branch():
    assert classify_booking_result("预约成功！座位已锁定") == "success"


@pytest.mark.parametrize("text", [
    "系统可预约时间 06:30～22:30，请在此时段操作",   # 全角波浪号
    "系统可预约时间 06:30〜22:30",                    # 另一种波浪号
    "系统可预约时间 06:30-22:30",                     # 连字符
])
def test_stop_branch_via_booking_window(text):
    # is_stop_booking_feedback 命中：非可预约时段提示 → stop
    assert is_stop_booking_feedback(text) is True
    assert classify_booking_result(text) == "stop"


@pytest.mark.parametrize("text", [
    "您今日已有有效预约",
    "已达每日限制",
    "部分读者暂不可预约",
])
def test_stop_branch_via_keywords(text):
    assert classify_booking_result(text) == "stop"


@pytest.mark.parametrize("text", [
    "验证码错误，请重新输入",
    "系统繁忙，请稍后",
    "请稍后再试",
    "请重试",
    "操作过于频繁",
])
def test_retry_captcha_branch(text):
    assert classify_booking_result(text) == "retry_captcha"


@pytest.mark.parametrize("text", [
    "该座位已被他人预约",
    "您已有预约",
    "预约失败，请重新选择",
    "未知的奇怪提示",   # 兜底分支
    "",                  # 空串：无关键字 → failed
])
def test_failed_branch_and_fallback(text):
    assert classify_booking_result(text) == "failed"


def test_is_stop_booking_feedback_requires_all_markers():
    # 只有时段词、缺 06:30/22:30 → 不算停止
    assert is_stop_booking_feedback("系统可预约时间另行通知") is False


@pytest.mark.parametrize("value", ["", None])
def test_helpers_handle_empty_input(value):
    assert is_stop_booking_feedback(value) is False
    assert is_blacklist_feedback(value) is False
