# ===================================================================
# LNU-LibSeat-Automation 配置模板
# -------------------------------------------------------------------
# 用法：复制本文件为 config.py 后填写；或直接打开 GUI，由它自动生成 config.py。
# ⚠️ 安全：config.py 含学号 / 密码等敏感信息，已被 .gitignore 忽略，请勿提交到 git。
# ===================================================================

USERS = {
    # "你的学号": {
    #     "password": "你的密码",
    #     "time": {"start": "08:00", "end": "12:00"},
    # },
    "": {
        "password": "",
        "time": {"start": "", "end": ""},
    },
}

TARGET_CAMPUS = "崇山校区图书馆"     # 校区，可选值见 ui_qt/services/config_io.py: ROOM_DATA
TARGET_ROOM = "三楼智慧研修空间"     # 自习室名称
PREFER_SEATS = []                    # 首选座位号，如 ["1", "2", "10"]；留空 = 随机扫描该自习室全部座位

WAIT_FOR_0630 = False                # True = 定时模式（每天定点抢座），False = 立即模式
MAX_ACCOUNTS = 2                     # 最多并发账号数

BROWSER = "edge"                     # "edge" | "chrome" | "safari"；留空按平台默认（Win→edge，其它→chrome）
DRIVER_PATH = ""                     # 可选：手动指定 webdriver 可执行文件完整路径
WEBDRIVER_CACHE = ""                 # 可选：webdriver-manager 缓存目录

RECEIVER_EMAIL = ""                  # 抢座成功通知的收件邮箱
SMTP_USER = ""                       # 可选：自定义发件邮箱（留空使用内置发件箱）
SMTP_PASS = ""                       # 可选：自定义发件邮箱的 SMTP 授权码

LOG_LEVEL = "INFO"                   # 日志级别：DEBUG / INFO / WARNING / ERROR
LOG_DIR = "logs"                     # 日志输出目录

# 仅在定时模式（WAIT_FOR_0630 = True）下生效：每天的准点提交时刻
SCHEDULE_HOUR = 6
SCHEDULE_MINUTE = 30
