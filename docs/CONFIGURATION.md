# ⚙️ 文档：配置详解 (config.py)

本文档详细说明 `config.py` 中的所有配置项。

> 推荐通过 GUI 界面进行配置（双击 EXE 或运行 `python gui.py`），GUI 会自动保存你的设置到 `config.py`。高级用户也可以手动编辑此文件。

---

## 目录

- [一、账号设置 (USERS)](#一账号设置-users)
- [二、目标场馆与座位 (TARGET & PREFER)](#二目标场馆与座位-target--prefer)
- [三、休眠控制与定时](#三休眠控制与定时)
- [四、邮件通知](#四邮件通知)
- [五、浏览器等进阶设定](#五浏览器等进阶设定)

---

## 一、账号设置 (USERS)

```python
USERS = {
    "你的学号": {
        "password": "你的密码",
        "time": {"start": "9:00", "end": "15:00"}
    },
    # 可选：添加第二个账号分时段
    "第二个学号": {
        "password": "密码",
        "time": {"start": "15:00", "end": "21:00"}
    }
}
```

发布到仓库时建议使用脱敏模板：

```python
USERS = {}
```

- **并发机制**：系统会根据字典 `keys` 自动孵化相应数量的子线程。
- **分时段占全天**：两个号抢同一个座位、不同时段，可以实现一个座位坐一整天！
- 建议每个配置不要超过 **3~5 个账号并存**，否则可能内存不足。

---

## 二、场馆与座位 (CAMPUS, TARGET & PREFER)

本程序支持**辽大双校区**所有场馆，请务必严格按照网页端显示的名称填写！

```python
TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["185", "186", "187", "188", "189", "190", "191", "192", "193", "194"]
```

### 🏫 如何正确填写校区与场馆名？
- **校区 (`TARGET_CAMPUS`)**：必须与网页下拉框中的名称完全一致，一个字不能差。
- **场馆名 (`TARGET_ROOM`)**：同理，必须与网页上的名字完全一致。

### 💺 如何正确寻找目标座位号？
打开系统网页版，进入自习室座位俯视图，看清每个位置的编号，按优先级排列填入 `PREFER_SEATS`。

---

## 三、休眠控制与定时

```python
WAIT_FOR_0630 = True
```

- **`True`（推荐）**：程序采用三阶段精确卡点策略：`prep_at` 提前启动浏览器完成登录与预热 → `pre_fire_at` 触发验证码弹窗并预分析 → `fire_at`（默认 `6:30:00`，或 GUI 自定义时间）准时点击确定并提交预约。
- **`False`**：程序立即执行所有步骤，适合白天调试。单浏览器会话，10 个优先座位逐个尝试，每个座位最多 10 次验证码机会。

> 定时目标时刻可在 GUI 中配置（严格模式默认 6:30，或切换自定义时刻）。

---

## 四、邮件通知

```python
RECEIVER_EMAIL = "你的邮箱@qq.com"

# 发件邮箱（可选，留空则使用项目内置邮箱自动发送）
SMTP_USER = ""
SMTP_PASS = ""
```

发布到仓库时建议清空为：

```python
RECEIVER_EMAIL = ""
SMTP_USER = ""
SMTP_PASS = ""
```

- **`RECEIVER_EMAIL`**：填写你想接收通知的邮箱地址。**只需填这一项即可收到邮件通知！**
- **`SMTP_USER` / `SMTP_PASS`**：留空即可。如果想用自己的邮箱发件，填入邮箱和授权码。

---

## 五、浏览器等进阶设定

```python
HEADLESS = True
BROWSER = "edge"
DRIVER_PATH = ""
WEBDRIVER_CACHE = ""
```

- **`HEADLESS`**: `True` 隐藏浏览器界面，`False` 可以看到浏览器自动操作。
- **`BROWSER`**: 支持 `"edge"` 和 `"chrome"`。
- **`DRIVER_PATH`**: 如果自动下载驱动失败，可手动下载驱动并填入绝对路径。

---

## 六、日志与调试

```python
LOG_LEVEL = "INFO"
LOG_DIR = "logs"
```

- **`LOG_LEVEL`**: 日志级别，可选 `"DEBUG"` / `"INFO"` / `"WARNING"` / `"ERROR"`。
- **`LOG_DIR`**: 日志输出目录。运行日志、失败截图和录屏视频都保存在此目录中。
  - `logs/lnu_seat.log` — 运行日志
  - `logs/screenshot_*.png` — 失败截图
  - `logs/captcha_attempts/` — 验证码点击留档
  - `logs/recordings/*.mp4` — 浏览器全程录屏视频（v2.7.0 新增）
