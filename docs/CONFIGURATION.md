# ⚙️ 配置详解 (`config.py`)

> [!IMPORTANT]
> **强烈推荐使用 GUI 界面配置**——双击 `LNU-LibSeat.exe` 后填表，GUI 会自动写入 `config.py`。
> 本文档面向**高级用户 / 开发者**，用于手编 `config.py` 时查阅。

[← 返回 README](../README.md) ·
[快速上手](QUICKSTART.md) ·
[架构文档](ARCHITECTURE.md) ·
[v3.0.0 升级日志](RELEASE_NOTES.md)

---

## 📋 全字段速查表

| 字段 | 类型 | 默认值 | 由 GUI 写入？ | 说明 |
|------|------|--------|--------------|------|
| `USERS` | dict | 空 | ✅ | 学号 → 密码 + 时段 |
| `TARGET_CAMPUS` | str | `"崇山校区图书馆"` | ✅ | 校区名（与网页端完全一致） |
| `TARGET_ROOM` | str | `"三楼智慧研修空间"` | ✅ | 自习室名 |
| `PREFER_SEATS` | list | `[]` | ✅ | 优先座位号；留空 → 全房随机扫 |
| `WAIT_FOR_0630` | bool | `False` | ✅ | True=定时模式 / False=立即模式 |
| `FORCE_API_ALWAYS` | bool | `False` | ✅ | **⚠️ 强烈建议保持 False** |
| `BROWSER` | str | `"edge"` | ✅ | `"edge"` 或 `"chrome"` |
| `DRIVER_PATH` | str | `""` | ✅ | 手动指定 WebDriver 路径 |
| `WEBDRIVER_CACHE` | str | `""` | ✅ | webdriver-manager 缓存目录 |
| `RECEIVER_EMAIL` | str | `""` | ✅ | 接收成功通知的邮箱 |
| `SMTP_USER` | str | `""` | ✅ | 自定义发件邮箱（留空走作者内置） |
| `SMTP_PASS` | str | `""` | ✅ | 自定义发件密码 |
| `LOG_LEVEL` | str | `"INFO"` | ✅ | 日志级别 |
| `LOG_DIR` | str | `"logs"` | ✅ | 日志目录 |
| `SCHEDULE_MODE` | str | `"strict"` | ⚠️ 仅 GUI 内存注入 | `"strict"`=严格 6:30 / `"custom"`=自定义时刻 |
| `SCHEDULE_HOUR` | int | `6` | ⚠️ 仅 GUI 内存注入 | 自定义模式的小时 |
| `SCHEDULE_MINUTE` | int | `30` | ⚠️ 仅 GUI 内存注入 | 自定义模式的分钟 |

---

## 一、账号设置 (`USERS`)

```python
USERS = {
    "你的学号": {
        "password": "你的密码",
        "time": {"start": "9:00", "end": "15:00"}
    },
    "第二个学号": {
        "password": "密码",
        "time": {"start": "15:00", "end": "21:00"}
    }
}
```

- **并发机制**：系统根据字典 keys 数量自动孵化对应数量的线程，**多账号同时跑**。
- **分时段全天覆盖**：两个学号抢同一座位、不同时段，9:00-21:00 无缝衔接。

> [!TIP]
> 用 GUI 时勾选「启用副账号」即可填第二个账号。手编 `config.py` 时按上述 dict 添加即可。

---

## 二、目标场馆与座位 (`TARGET` & `PREFER`)

```python
TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["185", "186", "187", "188", "189", "190", "191", "192", "193", "194"]
```

- **校区**：`"崇山校区图书馆"` 或 `"蒲河校区图书馆"`
- **自习室**：必须与网页端显示**完全一致**。程序内置双校区全部 20 间自习室座位索引（在 `info/` 目录）。
- **`PREFER_SEATS`**：
  - 留空 `[]` → 不指定首选，**直接随机扫整个自习室**
  - 填了 → 按顺序优先尝试，**失败后自动兜底扫剩余座位**
  - 不存在的座位号会被自动跳过

### 双校区可选自习室列表

| 校区 | 自习室 |
|------|-------|
| **崇山（8 间）** | 二楼书库北、二楼书库南、二楼背诵长廊、三楼智慧研修空间、三楼理科书库、四楼北自习室、四楼南自习室、四楼自习室406 |
| **蒲河（12 间）** | 三楼走廊、4楼阅览室、四楼走廊、5楼阅览室、五楼走廊、6楼阅览室、六楼走廊、704、706、707、708、七楼走廊 |

---

## 三、定时模式与抢座时刻

### 基础开关 (`WAIT_FOR_0630`)

```python
WAIT_FOR_0630 = True
```

- **`True`**（定时模式）：程序提前 30s 启动浏览器 → 提前 6s 锁定座位 → 整点准时提交
- **`False`**（立即模式）：双击 exe 后立即开抢，锁住就提交

### 自定义抢座时刻（v3.0.0 新增）

> [!NOTE]
> GUI 选「⏰ 定时执行」并填写时间后，会**通过内存注入**向 `config` 模块加入以下三个字段。
> 这三个字段**不会写入 `config.py` 文件**——如果你手编 `config.py`，需要自己加上。

```python
SCHEDULE_MODE = "custom"   # "strict"=严格 6:30 (默认) | "custom"=自定义时刻
SCHEDULE_HOUR = 6          # 自定义模式的小时（0-23）
SCHEDULE_MINUTE = 30       # 自定义模式的分钟（0-59）
```

| 场景 | 配置 |
|------|------|
| 严格 6:30 抢（默认） | `SCHEDULE_MODE = "strict"` |
| 自定义时刻（如错峰 14:00） | `SCHEDULE_MODE = "custom"` + `SCHEDULE_HOUR = 14` + `SCHEDULE_MINUTE = 0` |

> [!TIP]
> 如果当前已过该时间，程序会自动排到次日同时间。

---

## 四、图鉴 API 设置 (`FORCE_API_ALWAYS`)

```python
FORCE_API_ALWAYS = False
```

- **`False`**（默认，**强烈推荐**）：
  - 仅 **06:30:00 - 06:35:00** 高峰期使用图鉴 API
  - 其他时段使用免费本地 ddddocr
  - 每个座位本地最多 **10 次**重试 / API 最多 **5 次**重试
- **`True`**：
  - **全天**强制使用图鉴 API
  - 每个座位最多 **5 次**重试（API 慢，避免堆积）

> [!WARNING]
> 💸 **强烈建议保持 `False`！**
> 图鉴 API 是**付费**服务，**0.016 元/次**，目前由作者自掏腰包。
> 详见 [README §「关于图鉴 API 抢座」](../README.md#-关于图鉴-api-抢座开关) 和 [☕ 赞助页](../README.md#-求赞助--让免费持续)。

---

## 五、邮件通知

```python
RECEIVER_EMAIL = "你的邮箱@qq.com"
SMTP_USER = ""
SMTP_PASS = ""
```

- **`RECEIVER_EMAIL`**：接收通知的邮箱。**填这一项即可收到邮件**！
- **`SMTP_USER` / `SMTP_PASS`**：
  - **留空**（推荐）→ 使用作者内置发件邮箱
  - 填入 → 使用自定义邮箱（如不想暴露给作者）

---

## 六、浏览器 / 驱动 / 日志

```python
BROWSER = "edge"
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""
LOG_LEVEL = "INFO"
LOG_DIR = "logs"
```

| 字段 | 取值 | 说明 |
|------|-----|------|
| `BROWSER` | `"edge"` / `"chrome"` | 主流浏览器二选一 |
| `DRIVER_PATH` | 路径字符串 | 手动指定 WebDriver 位置（自动下载失败时使用） |
| `WEBDRIVER_CACHE` | 路径字符串 | webdriver-manager 缓存目录（默认 `~/.wdm`） |
| `LOG_LEVEL` | `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"` | 日志等级 |
| `LOG_DIR` | 路径字符串 | 日志根目录 |

### 日志输出位置

```
logs/
├── lnu_seat.log              ← 全量主日志
├── lnu_seat_<学号>.log        ← 各账号独立日志
└── sessions/
    └── <时间戳>_<学号>/       ← 每次抢座专属文件夹
        ├── session.log       ← 仅当次会话
        ├── 抢座顺序.txt
        ├── *_1_captcha_popup_*.png
        ├── *_2_text_clicked_*.png
        ├── *_3_confirm_clicked_*.png
        ├── *_4_result_*.png
        └── recordings/*.mp4
```

> [!TIP]
> 出问题时，把对应的 `sessions/<时间戳>_<学号>/` 文件夹打包发给作者就行——比口头描述清楚 100 倍。

---

## 🔗 相关文档

- 📘 [快速上手](QUICKSTART.md) — 第一次用？从这里开始
- 🏗️ [架构文档](ARCHITECTURE.md) — 想了解内部实现？
- 📦 [v3.0.0 升级日志](RELEASE_NOTES.md) — 看这次更新带来什么变化
- ☕ [README — 关于图鉴 API 抢座](../README.md#-关于图鉴-api-抢座开关)
