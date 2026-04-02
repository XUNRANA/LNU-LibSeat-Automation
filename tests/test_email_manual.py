import config
from core.notifications import build_success_email, send_email

account = "2022xxxxxxx"
TARGET_ROOM = config.TARGET_ROOM
target_seat = "185"
start_time = "9:00"
end_time = "15:00"

title_str, success_msg = build_success_email(account, TARGET_ROOM, target_seat, start_time, end_time)

print(f"📧 正在发送真实排版测试邮件至: {config.RECEIVER_EMAIL}")
if send_email(title_str, success_msg):
    print("✅ 发送成功！快去看看最新邮件的排版效果吧！")
else:
    print("❌ 发送失败。")
