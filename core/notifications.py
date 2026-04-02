import smtplib
from email.mime.text import MIMEText
from email.header import Header
from core.logger import get_logger

logger = get_logger(__name__)

def _get_smtp_creds():
    """延迟读取 SMTP 配置"""
    import config as _cfg
    user = getattr(_cfg, "SMTP_USER", "") or "lnu_libseat_bot@126.com"
    pwd = getattr(_cfg, "SMTP_PASS", "") or "DGZLX38ytQqYkVB3"
    return user, pwd


def build_success_email(account: str, room: str, seat: str, start_time: str, end_time: str):
    """Build the exact success-email subject/body used by the main booking flow."""
    title = f"🎉 预约成功: {account} @ {room}"
    content = (
        f"学霸你好，你的座位已被成功锁定！\n"
        f"――――――――――――――――――――――――\n"
        f"👤 预约账号：{account}\n"
        f"🏫 目标场馆：{room}\n"
        f"💺 锁定座位：{seat}\n"
        f"⏰ 预约时段：{start_time} - {end_time}\n"
        f"――――――――――――――――――――――――\n"
        f"💡 请按时到馆签到，祝您学习愉快！"
    )
    return title, content


def send_email(title: str, content: str = "") -> bool:
    """
    发送邮件通知。
    发件人：项目内置邮箱（使用者无需配置）
    收件人：config.py 中用户设置的 RECEIVER_EMAIL
    """
    import config as _cfg
    _SMTP_USER, _SMTP_PASS = _get_smtp_creds()
    receiver = getattr(_cfg, "RECEIVER_EMAIL", "") or _SMTP_USER

    if not _SMTP_USER or not _SMTP_PASS:
        logger.warning("SMTP credentials not configured; Email disabled")
        return False

    # 根据发件邮箱后缀自动推断 SMTP 服务器
    smtp_server = "smtp.126.com" if "126.com" in _SMTP_USER else "smtp.qq.com"

    # 构建邮件内容
    message = MIMEText(content, 'plain', 'utf-8')
    message['From'] = f"LNU-LibSeat-Automation <{_SMTP_USER}>"
    message['To'] = receiver
    message['Subject'] = Header(title, 'utf-8')

    try:
        smtp_obj = smtplib.SMTP_SSL(smtp_server, 465, timeout=10)
        smtp_obj.login(_SMTP_USER, _SMTP_PASS)
        smtp_obj.sendmail(_SMTP_USER, receiver, message.as_string())
        logger.info("📧 邮件已发送至 %s", receiver)
        return True
    except smtplib.SMTPException as e:
        logger.exception("Failed to send Email (SMTP Error): %s", e)
        return False
    except Exception as e:
        logger.exception("Failed to send Email (Unknown Error): %s", e)
        return False

