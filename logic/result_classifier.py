"""预约结果文本分类（纯函数，无浏览器依赖）。

从 ``logic.booker`` 抽出，便于独立单测与复用。``booker`` 仍以
``_classify_booking_result`` / ``_is_blacklist_feedback`` 别名导入这些函数，
原调用点无需改动。
"""
import re

# 黑名单提示固定文案（需整段长文本匹配，故用正则）
BLACKLIST_FEEDBACK_RE = re.compile(
    r"对不起[，,]?您已被加入黑名单[，,]?"
    r"预约权限将在\d{4}年\d{1,2}月\d{1,2}日恢复[。.!！]?"
    r"原因[:：]7天内迟到违约[，,]超过3次[，,]加入黑名单7天"
)


def is_blacklist_feedback(result_text):
    text = re.sub(r"\s+", "", result_text or "")
    if not text:
        return False
    return bool(BLACKLIST_FEEDBACK_RE.search(text))


def is_stop_booking_feedback(result_text):
    text = re.sub(r"\s+", "", result_text or "")
    if not text:
        return False
    text = text.replace("～", "~").replace("〜", "~").replace("-", "~")
    return (
        "系统可预约时间" in text
        and "06:30" in text
        and "22:30" in text
    )


def classify_booking_result(result_text):
    if is_stop_booking_feedback(result_text):
        return "stop"

    if "预约成功" in result_text:
        return "success"
    if "有效预约" in result_text:
        return "stop"
    if "每日限制" in result_text:
        return "stop"
    if "部分读者" in result_text:
        return "stop"

    if is_blacklist_feedback(result_text):
        return "blacklist"

    if (
        "验证码错误" in result_text
        or "系统繁忙" in result_text
        or "请稍后" in result_text
        or "请重试" in result_text
        or "操作过于频繁" in result_text
    ):
        return "retry_captcha"

    if "已被他人预约" in result_text:
        return "failed"
    if "已有预约" in result_text or "预约失败" in result_text:
        return "failed"

    return "failed"
