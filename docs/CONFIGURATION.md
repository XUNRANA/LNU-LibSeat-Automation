# ⚙️ 配置详解 (`config.py`)

> 📦 适用于 **LNU-LibSeat v5.0.0**

> [!IMPORTANT]
> **强烈推荐使用 GUI 界面配置**——双击 `LNU-LibSeat.exe`（macOS 双击 `LNU-LibSeat.app`）后填表，GUI 会自动写入 `config.py`。
> 本文档面向**高级用户 / 开发者**，用于手编 `config.py` 时查阅。

[← 返回 README](../README.md) ·
[快速上手](QUICKSTART.md) ·
[架构文档](ARCHITECTURE.md) ·
[v5.0.0 升级日志](RELEASE_NOTES_V5.md) ·
[v3→v5 升级指南](MIGRATION_V3_TO_V5.md)

---

## 📋 全字段速查表

| 字段 | 类型 | 默认值 | 由 GUI 写入？ | 说明 |
|------|------|--------|--------------|------|
| `USERS` | dict | 空 | ✅ | 学号 → 密码 + 时段 |
| `TARGET_CAMPUS` | str | `"崇山校区图书馆"` | ✅ | 校区名（与网页端完全一致） |
| `TARGET_ROOM` | str | `"三楼智慧研修空间"` | ✅ | 自习室名 |
| `PREFER_SEATS` | list | `["185"]` | ✅ | 优先座位号；⚠️ 不能留空，至少填一个座位 |
| `WAIT_FOR_0630` | bool | `False` | ✅ | True=定时模式 / False=立即模式 |
| `MAX_ACCOUNTS` | int | `2` | ✅ | **v5 新增**：多账号并发上限（超过自动截断） |
| `BROWSER` | str | 平台默认 | ✅ | `"edge"` / `"chrome"` / `"safari"`；留空=Windows→edge，macOS→chrome |
| `DRIVER_PATH` | str | `""` | ✅ | 手动指定 WebDriver 路径 |
| `WEBDRIVER_CACHE` | str | `""` | ✅ | webdriver-manager 缓存目录 |
| `RECEIVER_EMAIL` | str | `""` | ✅ | 接收成功通知的邮箱 |
| `SMTP_USER` | str | `""` | ✅ | 自定义发件邮箱（留空走作者内置） |
| `SMTP_PASS` | str | `""` | ✅ | 自定义发件密码 |
| `LOG_LEVEL` | str | `"INFO"` | ✅ | 日志级别 |
| `LOG_DIR` | str | `"logs"` | ✅ | 日志目录 |
| `SCHEDULE_HOUR` | int | `6` | ⚠️ 仅 GUI 内存注入 | 预约模式的小时 |
| `SCHEDULE_MINUTE` | int | `30` | ⚠️ 仅 GUI 内存注入 | 预约模式的分钟 |

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
> 用 GUI 时勾选「启用更多账号」即可填第二个账号。手编 `config.py` 时按上述 dict 添加即可。

---

## 二、目标场馆与座位 (`TARGET` & `PREFER`)

```python
TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["185", "186", "187", "188", "189", "190", "191", "192", "193", "194"]
```

- **校区**：`"崇山校区图书馆"` 或 `"蒲河校区图书馆"`
- **自习室**：必须与网页端显示**完全一致**。程序内置双校区全部 21 间自习室座位索引（在 `info/` 目录）。
- **`PREFER_SEATS`**：
  - ⚠️ **必须填写**：不能留空，至少指定一个座位号（否则会导致预约失败）
  - 填了多个 → 按顺序优先尝试，**失败后自动兜底扫后续座位**
  - 不存在的座位号会被自动跳过

### 双校区可选自习室列表

| 校区 | 自习室 |
|------|-------|
| **崇山（8 间）** | 二楼书库北、二楼书库南、二楼背诵长廊、三楼智慧研修空间、三楼理科书库、四楼北自习室、四楼南自习室、四楼自习室406 |
| **蒲河（13 间）** | 三楼走廊、4楼阅览室、四楼走廊、5楼阅览室、五楼走廊、6楼阅览室、六楼走廊、704、706、707、708、七楼走廊、智慧空间 |

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
> GUI 选「⏰ 定时执行」并填写时间后，会**通过内存注入**向 `config` 模块加入以下两个字段。
> 这两个字段**不会写入 `config.py` 文件**——如果你手编 `config.py`，需要自己加上。

```python
SCHEDULE_HOUR = 6          # 预约模式的小时（0-23）
SCHEDULE_MINUTE = 30       # 预约模式的分钟（0-59）
```

| 场景 | 配置 |
|------|------|
| 默认 06:30 抢 | `SCHEDULE_HOUR = 6` + `SCHEDULE_MINUTE = 30` |
| 自定义时刻（如错峰 14:00） | `SCHEDULE_HOUR = 14` + `SCHEDULE_MINUTE = 0` |

> [!TIP]
> 如果当前已过该时间，程序会自动排到次日同时间。

---

## 四、并发控制 (`MAX_ACCOUNTS`)

> 🆕 v5.0.0 新增字段。

```python
MAX_ACCOUNTS = 2
```

- **默认值 `2`**：最多并发启动 2 个账号的浏览器实例
- **如果 `USERS` 中字段数 > MAX_ACCOUNTS**：程序在 `main.py:732-735` 自动截断，只启动前 N 个
- **多账号通过 slot 偏移启动**：每个账号的 `prep_at` 增加 `slot_index × 8` 秒，避免浏览器初始化资源争抢

> [!TIP]
> 想跑 3 个或更多账号？把 `MAX_ACCOUNTS = 3` 写进 config.py 即可。但 CPU/RAM 消耗会线性增长，建议设备至少 8GB RAM。

> [!NOTE]
> **v5 已默认禁用图鉴 API**。`FORCE_API_ALWAYS` 字段在 v5 中已**移除**，旧 config.py 中保留也不会报错。
> v5 的验证码识别走自研 YOLO4+Siamese 本地模型，详见 [CAPTCHA_YOLO4_SIAMESE.md](CAPTCHA_YOLO4_SIAMESE.md)。

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
BROWSER = "edge"          # Windows 默认 edge；macOS/Linux 默认 chrome；可填 chrome / edge / safari
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""
LOG_LEVEL = "INFO"
LOG_DIR = "logs"
```

| 字段 | 取值 | 说明 |
|------|-----|------|
| `BROWSER` | `"edge"` / `"chrome"` / `"safari"` | 留空按平台默认：Windows→`edge`，macOS/Linux→`chrome`（见 `core/driver.py`） |
| `DRIVER_PATH` | 路径字符串 | 手动指定 WebDriver 位置（自动下载失败时使用） |
| `WEBDRIVER_CACHE` | 路径字符串 | webdriver-manager 缓存目录（默认 `~/.wdm`） |
| `LOG_LEVEL` | `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"` | 日志等级 |
| `LOG_DIR` | 路径字符串 | 日志根目录 |

> [!NOTE]
> **macOS 浏览器选择**：
> - **Chrome**（推荐）：支持双账号并行，体验与 Windows 一致。
> - **Safari**：需先开启 Safari ▸ 设置 ▸ 高级 ▸「在菜单栏显示开发菜单」→ 开发 ▸「允许远程自动化」。Safari **不支持 `--user-data-dir`**，因此**仅支持单账号**（多账号只能串行、共享登录态）。
> - **Edge**：仅 Windows。

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
- 🚀 [v3→v5 升级指南](MIGRATION_V3_TO_V5.md) — 老用户必读
- 📦 [v5.0.0 升级日志](RELEASE_NOTES_V5.md) — 3 大重构 + 6 项强化
- 🧠 [验证码引擎文档](CAPTCHA_YOLO4_SIAMESE.md) — YOLO4+Siamese 技术细节
- 🎨 [GUI 架构文档](GUI_QT_ARCHITECTURE.md) — PySide6 模块拆分
- 🏗️ [架构文档](ARCHITECTURE.md) — 想了解内部实现？
- 📋 [反馈消息处理参考](FEEDBACK_MESSAGES.md) — 所有系统反馈消息与程序行为映射
- 🔢 [数字参数](NUMERIC_PARAMETERS.md) — 所有超时/延迟/阈值清单
- 📜 [v3.0.0 历史日志](RELEASE_NOTES.md)
