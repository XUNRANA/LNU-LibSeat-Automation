# ===================================================================
# LNU-LibSeat-Automation 配置文件
# ===================================================================
# 注意：本文件是运行环境默认模板。
# 启动 GUI (LNU-LibSeat.exe) 后，你在界面上填写的配置会自动保存并覆盖到此文件
# ===================================================================

USERS = {
    "你的学号": {
        "password": "你的密码",
        "time": {"start": "9:00", "end": "15:00"}
    },
    "第二个学号": {
        "password": "密码(不需要可留空)",
        "time": {"start": "15:00", "end": "21:00"}
    },
}

TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["001", "002"]

WAIT_FOR_0630 = True
HEADLESS = True

BROWSER = "edge"
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""

RECEIVER_EMAIL = ""
SMTP_USER = ""
SMTP_PASS = ""

LOG_LEVEL = "INFO"
LOG_DIR = "logs"
