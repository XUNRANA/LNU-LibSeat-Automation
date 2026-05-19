<div align="center">

# 📦 LNU-LibSeat **v5.0.0**

### 🧠 自研验证码 AI · 🎨 PySide6 全新界面 · 🧊 模型预加载

**首发 2026-05-19**

[← 返回 README](../README.md) ·
[快速上手](QUICKSTART.md) ·
[v3→v5 升级指南](MIGRATION_V3_TO_V5.md) ·
[配置详解](CONFIGURATION.md) ·
[架构文档](ARCHITECTURE.md) ·
[v3.0.0 升级日志](RELEASE_NOTES.md)

</div>

---

## 🎯 一句话总结

> **3 大重构 + 6 项强化 + 1 间新自习室** — 验证码摆脱付费 API、界面焕然一新、双校区 **21 间**自习室全覆盖。

---

## 📊 v5.0.0 vs v3.0.x 一图看懂

| 维度 | v3.0.0 旧版 | **v5.0.0** ✨ |
|------|------------|---------------|
| 🖥️ **GUI 框架** | CustomTkinter（1 个 `gui.py`，1135 行单文件） | **PySide6**（`gui_qt.py` + `ui_qt/` 23 模块） |
| 🤖 **验证码引擎** | 图鉴 API（付费）+ ddddocr | **自研 YOLO4+Siamese**（本地 ONNX，免费） |
| 🧊 **模型预加载** | 无（首次验证码冷启动） | **后台异步预热**（`_start_captcha_model_preload`） |
| 📦 **关键依赖** | `customtkinter>=5.2.0` | `PySide6>=6.7.0` + `onnxruntime>=1.17.0` |
| ⚙️ **配置项** | `FORCE_API_ALWAYS` 开关 | 移除；新增 `MAX_ACCOUNTS=2` 并发上限 |
| 🏫 **自习室数** | 20 间 | **21 间**（新增「智慧空间」，281 座位） |
| 🧠 **模型权重** | 无（远程 API） | `core/checkpoints/` 4 ONNX + 2 PT + 1 PTH (~210MB) |
| 🛟 **反馈分类** | success / blacklist / retry / failed | **+ stop** 状态（系统限制 / 每日上限 / 部分读者） |

---

## 🆕 三大重构

### 🏗️ 1. PySide6 GUI 全面重构

> ❌ 删除 `gui.py`（1135 行 CustomTkinter 单文件）
> ✅ 新增 `gui_qt.py`（8 行入口）+ `ui_qt/`（23 模块化文件）

**What 改了什么**
- 入口：`python gui.py` → `python gui_qt.py`
- 框架：CustomTkinter → PySide6
- 结构：单文件 → `panels/` + `widgets/` + `workers/` + `services/` 四层拆分

**Why 为什么改**
- CustomTkinter 在高分屏 / 多显示器场景下渲染不一致
- 单文件结构难以协作和维护
- PySide6 的 Qt Designer 生态、信号槽机制更适合长期演进

**How 怎么实现**

```
ui_qt/
├── app.py                      # MainWindow 入口
├── theme.py                    # 全局颜色 / 字体常量
├── panels/
│   ├── config_panel.py         # 左侧：校区/自习室/座位/账号
│   └── dashboard_panel.py      # 右侧：Logo/倒计时环/启停/日志
├── widgets/                    # 11 个复用组件
│   ├── countdown_ring.py       # 倒计时圆环
│   ├── log_terminal.py         # 日志终端
│   ├── account_card.py         # 账号卡片
│   └── ...
├── workers/
│   └── booker_worker.py        # 后台抢座线程（信号槽与 GUI 解耦）
└── services/
    ├── config_io.py            # 配置 I/O + ROOM_DATA
    └── prevent_sleep.py        # Windows 防休眠
```

详见 [GUI_QT_ARCHITECTURE.md](GUI_QT_ARCHITECTURE.md)。

---

### 🧠 2. 自研 YOLO4+Siamese 本地验证码

> ❌ 删除 `core/captcha.py:ClickCaptchaSolver`（200+ 行 OCR 字符匹配）
> ❌ 默认弃用图鉴 API（保留 `core/captcha_api.py` 备份）
> ✅ 新增 YOLO4 检测 + Siamese 相似度的双阶段管线

**What 改了什么**

| 验证码类型 | 模型 | 准确率 |
|-----------|------|--------|
| **Click1**（单字定位） | `click1_yolo_plan_bg_char40_best.onnx` + `click1_siamese_yolo4_best.onnx` | **83.48%**（端到端） |
| **Click3**（3 点连击） | `click3_yolo_plan_bg_char60_best.onnx` + `click3_siamese_yolo4_posw3_best.onnx` | 待回测 |

**Why 为什么改**
- 图鉴 API 0.016 元/次，作者钱包烧不起
- 商业 API 延迟波动大（3.5–17.8s）
- 自研模型本地推理 < 1s，离线可用

**How 怎么实现**

```
DOM 抓图 → base64 解码
        ↓
   YOLO4 检测层（core/yolo_onnx.py）
        ↓ 输出 4 个候选框
   Siamese 相似度层
        ↓ 与目标字符 crop 对比
   Top-K 排序 → 点击坐标
        ↓
   ActionChains 点击 + JS 兜底
```

详见 [CAPTCHA_YOLO4_SIAMESE.md](CAPTCHA_YOLO4_SIAMESE.md)。

---

### 🧊 3. 模型预加载 + 时间窗口

> ✅ 新增 `_start_captcha_model_preload()`（`main.py:31-51`）
> ✅ 新增 `LOCAL_CAPTCHA_WINDOW_START/END` 时间窗口（`logic/booker.py`）

**What 改了什么**
- 程序启动后立即在后台异步线程加载 ONNX 模型，避免第一次验证码冷启动
- 本地识别仅在 **06:30:00–06:35:00** 启用，其他时段直接走 ActionChains 不解析

**Why 为什么改**
- 模型加载耗时 3–5s，落在抢座关键时刻会错过提交窗口
- 抢座时刻才是 OCR 的真实战场；其他时段没必要消耗 CPU

**How 怎么实现**

```python
# main.py
def _start_captcha_model_preload(reason: str = "scheduled"):
    """Start one background warmup for YOLO4+Siamese."""
    def _worker():
        from logic.booker import preload_yolo4_siamese_model
        preload_yolo4_siamese_model("preload")
    threading.Thread(target=_worker, daemon=True).start()
```

`logic/booker.py` 内有线程安全锁 `_CAPTCHA_SOLVER_LOCK` 与全局标志 `_YOLO4_SIAMESE_PRELOADED`，多账号并发安全。

---

## 💪 六项强化

### ① 新增「智慧空间」自习室

`info/智慧空间.txt` 收录蒲河校区智慧空间 **281** 个座位号。GUI 自习室下拉框新增此项。

### ② 线程安全设计

`logic/booker.py` 新增模块级锁 `_CAPTCHA_SOLVER_LOCK` 与标志 `_YOLO4_SIAMESE_PRELOADED`，保证多账号同时调用 YOLO4+Siamese 推理时不出现状态竞争。

### ③ 配置精简

- ❌ 移除 `FORCE_API_ALWAYS`（API 已默认禁用，开关无意义）
- ✅ 新增 `MAX_ACCOUNTS = 2`（多账号并发上限，超过自动截断；见 `main.py:732-735`）

### ④ 调度逻辑简化

- 移除 `build_strict_schedule()` 中的次日排队分支
- 统一走 `build_custom_schedule()`：用户填的 hh:mm 已过则自动排次日（`main.py:60-77`）

### ⑤ 模型权重打包

`build.py` 新增 `core/checkpoints/` 整目录拷贝到 `dist/.../_internal/core/checkpoints/`；exe 用户无感知。

### ⑥ 反馈分类精细化

`_classify_booking_result()` 新增 `"stop"` 类型，区分以下三类系统强制中止：
- 系统可预约时间限制（06:30–22:30 凌晨触发）
- 已有有效预约（每日 ≤ 3 次）
- 教室仅对部分读者开放

具体映射详见 [FEEDBACK_MESSAGES.md](FEEDBACK_MESSAGES.md)。

---

## ⚠️ 破坏性变更

| 变更 | 影响 | 迁移动作 |
|-----|------|---------|
| `gui.py` 删除 | 用源码跑的开发者 | `python gui.py` → `python gui_qt.py` |
| `FORCE_API_ALWAYS` 移除 | 手编 config.py 的用户 | 删除该字段即可（保留也不报错） |
| `customtkinter` 依赖移除 | venv 用户 | `pip uninstall customtkinter -y` |
| `PySide6` + `onnxruntime` 新增 | venv 用户 | `pip install -r requirements.txt` |
| `ClickCaptchaSolver` 类删除 | 外部脚本导入此类 | 改用 `Yolo4SiameseSolver` / `Click1Yolo4SiameseSolver` |
| `core/checkpoints/` 新增必备 | 源码用户 | 模型文件随仓库或独立发布；exe 包内自带 |

完整迁移指南：[MIGRATION_V3_TO_V5.md](MIGRATION_V3_TO_V5.md)。

---

## 🚫 已知限制

- **模型权重 210MB**：exe 包从 ~150MB 增加到 ~360MB
- **本地识别仅 06:30:00–06:35:00**：其他时段不解析验证码（设计如此，详见 [CAPTCHA_YOLO4_SIAMESE.md §时间窗口](CAPTCHA_YOLO4_SIAMESE.md)）
- **首次启动需 3–5s 预加载**：后台线程进行，不阻塞 GUI
- **Click3 准确率待回测**：当前仅有 Click1 的端到端 83.48% 数据

---

## 📊 实测性能基准

完整数据请见 [V5_PERFORMANCE.md](V5_PERFORMANCE.md)。

| 指标 | v3.0.0 图鉴 API | v3.0.0 ddddocr | **v5.0.0 YOLO4+Siamese** |
|------|-----------------|----------------|--------------------------|
| 单次识别延迟 | 7.21s（平均） | 0.51s | 待回测（预计 < 1s） |
| 单次准确率 | 100% | 61.2% | Click1 **83.48%** |
| 联网依赖 | ✅ 强 | ❌ 无 | ❌ 无 |
| 单次成本 | 0.016 元 | 0 元 | 0 元 |

---

## ☕ 顺便说一句

> v5.0.0 让 LNU-LibSeat 彻底摆脱了商业 API 的成本压力，但作者仍在为大家维护、训练新模型、修 bug。
> 如果工具帮到了你，**随手扫码赞助**就是最大的鼓励 ❤️
>
> 👉 二维码在 [README 底部 ☕ 赞助章节](../README.md#-求赞助--让免费持续)

---

## 🔗 相关文档

- 📘 [快速上手](QUICKSTART.md) — 第一次用？从这里开始
- 🚀 [v3→v5 升级指南](MIGRATION_V3_TO_V5.md) — 老用户必读
- 🧠 [验证码引擎文档](CAPTCHA_YOLO4_SIAMESE.md) — YOLO4+Siamese 技术细节
- 🎨 [GUI 架构文档](GUI_QT_ARCHITECTURE.md) — PySide6 模块拆分
- 📊 [v5 性能基准](V5_PERFORMANCE.md) — 实测数据
- ⚙️ [配置详解](CONFIGURATION.md) — config.py 字段
- 🏗️ [架构文档](ARCHITECTURE.md) — 整体设计
- 📦 [v3.0.0 升级日志](RELEASE_NOTES.md) — 历史 release notes

---

<div align="center">

**喜欢这次更新？**

[⭐ Star 一下](https://github.com/XUNRANA/LNU-LibSeat-Automation) · [☕ 赞助一杯奶茶](../README.md#-求赞助--让免费持续) · [🐛 反馈 Bug](https://github.com/XUNRANA/LNU-LibSeat-Automation/issues)

</div>
