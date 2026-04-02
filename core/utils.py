from datetime import datetime, timedelta, timezone


def get_beijing_time():
    """获取北京时间（时区感知的 datetime 对象，UTC -> UTC+8）"""
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
