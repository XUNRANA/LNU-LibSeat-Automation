<div align="center">

# 🚀 v3 → v5 升级指南

### 5 分钟搞定老版本迁移

[← 返回 README](../README.md) ·
[v5.0.0 升级日志](RELEASE_NOTES_V5.md) ·
[快速上手](QUICKSTART.md) ·
[配置详解](CONFIGURATION.md)

</div>

---

## 📌 阅读对象

- 👤 **EXE 用户**：v3.0.0 zip 下载并双击运行的用户 → [跳到「EXE 用户升级」](#-exe-用户升级简单)
- 🧑‍💻 **源码开发者**：`git clone` 后 `python gui.py` 跑的用户 → [跳到「源码用户升级」](#-源码用户升级)
- 📦 **手编 config.py 的用户** → [跳到「配置迁移」](#-配置迁移)

---

## 🎯 为什么要升级

| 痛点（v3） | 解决（v5） |
|-----------|-----------|
| 6:30 验证码依赖付费 API，作者钱包烧不起 | **自研 YOLO4+Siamese**，本地推理零成本 |
| CustomTkinter 在高分屏渲染不一致 | **PySide6 全新界面**，Qt 原生渲染 |
| 首次验证码冷启动 3–5s | **后台异步预加载** |
| 双校区只有 20 间自习室 | **新增「智慧空间」**（+281 座位） |

完整变化清单：[RELEASE_NOTES_V5.md](RELEASE_NOTES_V5.md)。

---

## 🟢 EXE 用户升级（简单）

> 适合：你之前下载了 `LNU-LibSeat-v3.0.0.zip` 双击运行。

### 三步走

```
1. 备份你的旧 config.py（里面有学号密码）
2. 下载 LNU-LibSeat-v5.0.0.zip → 解压到新目录
3. 双击新 LNU-LibSeat.exe → GUI 自动生成新 config.py
```

### 详细步骤

**Step 1 备份**

```powershell
# 找到旧版目录，把 config.py 复制出来
Copy-Item "LNU-LibSeat-v3.0.0\config.py" "$HOME\Desktop\config_v3_backup.py"
```

**Step 2 下载并解压新版**

去 [Releases](https://github.com/XUNRANA/LNU-LibSeat-Automation/releases/latest) 下载 `LNU-LibSeat-v5.0.0.zip`，解压到任意新位置（推荐**不要覆盖旧目录**）。

**Step 3 重新填表**

双击 `LNU-LibSeat.exe` → 按之前一样填学号 / 密码 / 时段 → 「🚀 开始抢座」。

> [!TIP]
> v5 GUI 的字段和 v3 完全兼容，你不需要重学。

**可选：删除旧目录**

确认 v5 跑通后，旧 `LNU-LibSeat-v3.0.0/` 整个目录可以删除。

---

## 🧑‍💻 源码用户升级

> 适合：你之前 `git clone` 后跑 `python gui.py`。

### 完整升级命令

```powershell
# 1. 拉取最新代码
git pull

# 2. 卸载 v3 不再需要的依赖
pip uninstall customtkinter -y

# 3. 安装 v5 新增依赖
pip install -r requirements.txt

# 4. 用新入口启动
python gui_qt.py
```

### 关键变化

| 项 | v3 | v5 |
|---|---|---|
| 入口文件 | `gui.py` | **`gui_qt.py`** |
| GUI 框架 | `customtkinter` | `PySide6` |
| 验证码 | `ddddocr` + 图鉴 API | **`onnxruntime`** + 本地 ONNX |
| 新增目录 | — | **`core/checkpoints/`**（7 个权重，~210MB） |
| 新增目录 | — | **`ui_qt/`**（23 个模块） |
| 删除文件 | `gui.py`（1135 行） | — |
| 删除类 | — | `core/captcha.py:ClickCaptchaSolver` |

### 依赖 diff

```diff
- customtkinter>=5.2.0
+ PySide6>=6.7.0
+ onnxruntime>=1.17.0
```

> [!IMPORTANT]
> `core/checkpoints/` 必须存在且包含 4 个 ONNX 模型，否则 6:30–6:35 期间验证码会失败。
> 模型文件随 GitHub Release 一起发布，或通过 git LFS / 独立下载。

### 打包

```powershell
python build.py
```

> [!NOTE]
> `build.py` 当前版本号仍写 `v3.x.B`（草稿），首次打 v5 之前请手动改为 `v5.0.0`。
> 文件位置：`build.py:28` `APP_VERSION = "v3.x.B"` → `"v5.0.0"`。

---

## 📦 配置迁移

### config.py 字段对照表

| 字段 | v3 | v5 | 迁移动作 |
|------|----|----|---------|
| `USERS` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `TARGET_CAMPUS` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `TARGET_ROOM` | ✅ 保留 | ✅ 保留 | 无需改动（新增可选「智慧空间」） |
| `PREFER_SEATS` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `WAIT_FOR_0630` | ✅ 保留 | ✅ 保留 | 无需改动 |
| **`FORCE_API_ALWAYS`** | ✅ 默认 `False` | **❌ 已移除** | 可保留（不会报错），建议删除 |
| **`MAX_ACCOUNTS`** | ❌ 不存在 | ✅ 默认 `2` | 可不加（缺省 2）；想跑 ≥3 个账号则手动加 |
| `BROWSER` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `DRIVER_PATH` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `WEBDRIVER_CACHE` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `RECEIVER_EMAIL` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `SMTP_USER` / `SMTP_PASS` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `LOG_LEVEL` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `LOG_DIR` | ✅ 保留 | ✅ 保留 | 无需改动 |
| `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` | ⚠️ GUI 内存注入 | ⚠️ GUI 内存注入 | 同 v3，不持久化到文件 |

### v3 旧 config.py 示例 → v5 等价配置

```diff
USERS = {
    "20240xxxxx": {"password": "pwd", "time": {"start": "9:00", "end": "15:00"}},
}

TARGET_CAMPUS = "崇山校区图书馆"
TARGET_ROOM = "三楼智慧研修空间"
PREFER_SEATS = ["185", "186"]

WAIT_FOR_0630 = True
- FORCE_API_ALWAYS = False        # v3: 强制图鉴 API 开关
+ MAX_ACCOUNTS = 2                # v5: 并发账号上限

BROWSER = "edge"
RECEIVER_EMAIL = "you@qq.com"
LOG_LEVEL = "INFO"
LOG_DIR = "logs"
```

完整字段说明：[CONFIGURATION.md](CONFIGURATION.md)。

---

## ⏰ 行为变化

### 06:30:00–06:35:00 时间窗口

> [!IMPORTANT]
> v5 的本地 YOLO4+Siamese 模型**仅在 06:30:00 ~ 06:35:00** 5 分钟窗口内激活。
> 窗口外的提交不会自动解验证码（避免无意义的 CPU 占用 / 模型推理）。

**实际影响**：
- 如果你抢的是 06:30 放座 → 一切正常
- 如果你想用 v5 抢**其他时段**（如错峰 14:00）→ 验证码会卡住

> [!TIP]
> 想用 v5 抢非 06:30 时段，请在 [CAPTCHA_YOLO4_SIAMESE.md](CAPTCHA_YOLO4_SIAMESE.md) 查看如何修改 `LOCAL_CAPTCHA_WINDOW_*`（高级用户）。

### 模型预加载

v5 启动 GUI 后立即在后台预热 YOLO4+Siamese 模型（约 3–5s）。期间日志会显示：

```
🧠 本地 YOLO4+Siamese 验证码模型开始预加载 (scheduled startup)...
```

这是正常行为。预加载完成后，6:30 当下解一次验证码 < 1s。

---

## 🛟 FAQ

<details>
<summary><b>Q1: 我的 v3 抢座顺序.txt / session.log 还能继续看吗？</b></summary>

可以。v5 的会话目录结构与 v3 完全兼容（`logs/sessions/<timestamp>_<account>/`），旧会话目录不受影响。
</details>

<details>
<summary><b>Q2: 我之前充值的图鉴账号还能用吗？</b></summary>

v5 默认禁用图鉴 API，但 `core/captcha_api.py` 文件仍保留。如需自行重启 API 链路（高级用户），可在 `logic/booker.py` 中接入 `TTShiTuClient`——但**不推荐**，本地模型已经够用。

充值的钱图鉴不退；如果你不想浪费，建议留作小额测试或转给需要的人。
</details>

<details>
<summary><b>Q3: v3 的 logs/ 目录要清理吗？</b></summary>

不需要。v5 会继续往同一个 `logs/` 目录里追加新会话。如果磁盘紧张，可手动删除 `logs/sessions/2026010*` 等旧子目录。
</details>

<details>
<summary><b>Q4: 升级后 GUI 启动很慢，几秒钟才出窗口？</b></summary>

不正常。GUI 应**立即**出窗口，模型在后台异步加载。如果窗口要等几秒：
- 检查是否 PySide6 安装异常（重装 `pip install --force-reinstall PySide6`）
- 检查是否安装了 Anaconda 影响 venv（`build.py` 用隔离 venv 可绕过）
</details>

<details>
<summary><b>Q5: 我能继续用 v3 吗？</b></summary>

可以，但**不再维护**。v3 依赖图鉴 API，作者已停止充值后 v3 用户的 API 调用会逐渐失败。建议尽快升 v5。
</details>

<details>
<summary><b>Q6: v5 的 exe 包变大了？</b></summary>

是。v3 约 150MB，v5 约 360MB，原因是 `core/checkpoints/` 内置了 4 个 ONNX 模型（共 ~210MB）。这是**一次性**代价，换来本地推理零成本。
</details>

<details>
<summary><b>Q7: 我自己训练新模型替换默认权重可以吗？</b></summary>

可以。源码自带 `siamese_dataloader.py` 和 `siamese_model.py`（基于 MobileNetV4 + 自定义融合头）。
训练流程见 [CAPTCHA_YOLO4_SIAMESE.md §自训练流程](CAPTCHA_YOLO4_SIAMESE.md)。
</details>

---

## ✅ 升级检查清单

升级完成后，按以下步骤验证：

```
[ ] 双击 LNU-LibSeat.exe（或 python gui_qt.py）
[ ] GUI 窗口立即弹出（< 1s）
[ ] 后台日志有「本地 YOLO4+Siamese 验证码模型开始预加载」字样
[ ] 填表点开始 → 浏览器正常打开
[ ] 自习室下拉框能看到「智慧空间」选项（v5 新增）
[ ] 一次试抢非高峰时段：浏览器登录 + 进自习室成功
[ ] 06:30 真实抢座：本地验证码 1 次或 2 次内通过
```

如果以上 7 项都过，升级成功 🎉

---

## 🔗 相关文档

- 📘 [快速上手](QUICKSTART.md) — 第一次用？从这里开始
- 📦 [v5.0.0 升级日志](RELEASE_NOTES_V5.md) — 完整变化清单
- ⚙️ [配置详解](CONFIGURATION.md) — config.py 字段
- 🧠 [验证码引擎文档](CAPTCHA_YOLO4_SIAMESE.md) — 本地模型技术细节
- 🎨 [GUI 架构文档](GUI_QT_ARCHITECTURE.md) — PySide6 拆分
- 📋 [反馈消息](FEEDBACK_MESSAGES.md) — 所有系统反馈与程序行为映射
