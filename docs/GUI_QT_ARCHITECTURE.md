<div align="center">

# 🎨 GUI 架构文档

### LNU-LibSeat v5.0.0 — PySide6 模块化界面

[← 返回 README](../README.md) ·
[架构文档](ARCHITECTURE.md) ·
[v5.0.0 升级日志](RELEASE_NOTES_V5.md) ·
[数字参数](NUMERIC_PARAMETERS.md)

</div>

---

## 📑 目录

- [为什么从 CustomTkinter → PySide6](#-为什么从-customtkinter--pyside6)
- [整体目录结构](#-整体目录结构)
- [主题系统](#-主题系统)
- [Panel 拆分](#-panel-拆分)
- [Widgets 清单](#-widgets-清单)
- [Worker 线程模型](#-worker-线程模型)
- [Config I/O 服务](#-config-io-服务)
- [防休眠服务](#-防休眠服务)
- [打包注意事项](#-打包注意事项)
- [自定义贡献指南](#-自定义贡献指南)

---

## 🔄 为什么从 CustomTkinter → PySide6

| 痛点（v3 CustomTkinter） | v5 PySide6 解决 |
|---|---|
| 高分屏 / 多显示器渲染不一致 | Qt 原生 HiDPI 支持 |
| 1135 行单文件难维护 | 模块化拆成 23 个 .py 文件 |
| 自定义控件能力有限 | QPainter 自绘 + QSS 样式 |
| 信号传递靠回调链 | Qt 信号槽机制 |
| 任务栏图标 / 系统集成弱 | Qt 原生支持 |

> v3 时代 `gui.py`（1135 行）已经成为单点维护瓶颈。v5 重构后单文件最多 ~300 行，分层清晰。

---

## 🗂️ 整体目录结构

```
ui_qt/                          # 23 个 .py 文件
├── __init__.py
├── app.py                       # 🏠 MainWindow 主窗口
├── theme.py                     # 🎨 全局颜色 / 字体 / 间距常量
│
├── panels/                      # 📋 左 + 右两大面板
│   ├── __init__.py
│   ├── config_panel.py          #   左：校区/自习室/座位/账号配置
│   └── dashboard_panel.py       #   右：Logo/倒计时/启停/日志终端
│
├── widgets/                     # 🧱 11 个复用组件
│   ├── __init__.py
│   ├── header_bar.py            #   顶部标题栏
│   ├── title_bar.py             #   无边框窗口的自定义标题栏
│   ├── account_card.py          #   账号卡片（学号+密码+时段）
│   ├── section_card.py          #   通用分组卡片
│   ├── mode_toggle.py           #   立即/定时模式切换
│   ├── seat_grid.py             #   座位号网格选择
│   ├── status_pill.py           #   状态指示丸
│   ├── countdown_ring.py        #   倒计时圆环（QPainter 自绘）
│   ├── log_terminal.py          #   日志终端（彩色文本流）
│   ├── buttons.py               #   主/次按钮
│   └── seal_mark.py             #   学校封印装饰
│
├── workers/                     # 🧵 后台线程
│   ├── __init__.py
│   └── booker_worker.py         #   后台抢座 Worker（信号槽与 GUI 解耦）
│
└── services/                    # ⚙️ 系统服务封装
    ├── __init__.py
    ├── config_io.py             #   config.py 读写 + 数据模型
    └── prevent_sleep.py         #   防休眠：Windows ExecutionState / macOS caffeinate
```

入口：`gui_qt.py` 仅 8 行，委托 `ui_qt.app:main()`：

```python
# gui_qt.py
from ui_qt.app import main
if __name__ == "__main__":
    main()
```

---

## 🎨 主题系统

> 源码：`ui_qt/theme.py`

集中定义所有颜色、字体、间距，避免散落在各组件里。

### 颜色常量（节选）

```python
class C:
    # 纸感背景
    BG          = "#f5f1e8"   # 米白
    BG_PAPER    = "#faf6ec"   # 略亮纸

    # 卡片
    CARD        = "#fdfcf8"   # 蛋壳白
    CARD_SUNK   = "#f0ead9"   # 内嵌区域底色
    BORDER      = "#e8e2d3"   # 浅琥珀边

    # 主色 LNU 海军蓝
    INK         = "#003876"
    INK_LIGHT   = "#1e5599"
    INK_DARK    = "#002654"
    INK_TINT    = "#e2eaf3"   # 极浅蓝（hover/selected 背景）

    # 强调 琥珀
    AMBER       = "#d4a574"
    AMBER_HOT   = "#b8854a"
    AMBER_LIGHT = "#e8c896"
    AMBER_GLOW  = "#f5e2c4"

    # 文字
    TEXT        = "#1a1a1a"
    TEXT_MUTED  = "#5a5a5a"
    TEXT_DIM    = "#9a9a9a"
    TEXT_INVERT = "#fdfcf8"

    # 状态
    OK          = "#5b8c5a"
    WARN        = "#c8923c"
    ERR         = "#9b3838"
    ERR_LIGHT   = "#f0d8d8"
```

### 字体函数

```python
def serif(size: int) -> QFont:    # 衬线（标题）
def sans(size: int) -> QFont:     # 无衬线（正文）
def mono(size: int) -> QFont:     # 等宽（日志/代码）
```

### 修改主题

想换主题色？修改 `theme.py` 中的常量即可——所有组件都引用 `C.AMBER` 等，不直接硬编码。

---

## 📋 Panel 拆分

主窗口（`ui_qt/app.py:MainWindow`）使用左右布局：

```
┌─────────────────────────────────────┐
│  HeaderBar (顶部)                    │
├──────────────┬──────────────────────┤
│              │                      │
│ ConfigPanel  │  DashboardPanel      │
│  (左 ~40%)   │   (右 ~60%)          │
│              │                      │
│ - 校区       │  - Logo + 圆环        │
│ - 自习室     │  - 启停按钮           │
│ - 座位       │  - 日志终端           │
│ - 账号       │                      │
│ - 模式       │                      │
│              │                      │
└──────────────┴──────────────────────┘
```

### ConfigPanel（`ui_qt/panels/config_panel.py`）

左侧配置面板，包含：

| 区域 | 控件 |
|------|------|
| 校区选择 | `QComboBox` |
| 自习室选择 | `QComboBox`（联动校区） |
| 首选座位 | `SeatGrid` |
| 主账号 | `AccountCard` |
| 更多账号（可选） | `AccountCard` + 启用开关 |
| 模式切换 | `ModeToggle`（立即/定时） |
| 定时时间 | 时分输入框（仅定时模式可见） |
| 邮件 | 邮箱输入框 |
| 浏览器选择 | `QComboBox`（Chrome / Edge / Safari；macOS 默认 Chrome，Windows 默认 Edge） |

### DashboardPanel（`ui_qt/panels/dashboard_panel.py`）

右侧仪表盘：

| 区域 | 控件 |
|------|------|
| Logo | `LogoImage`（圆形 logo） |
| 倒计时 | `CountdownRing`（QPainter 自绘 360×360） |
| 主按钮 | `PrimaryButton`（开始） |
| 次按钮 | `GhostButton`（停止） |
| 日志终端 | `LogTerminal`（实时滚动） |

---

## 🧱 Widgets 清单

| 组件 | 文件 | 关键技术 |
|------|------|---------|
| **HeaderBar** | `widgets/header_bar.py` | 顶部标题栏 + 应用名 |
| **TitleBar** | `widgets/title_bar.py` | 无边框窗口的最小化/最大化/关闭按钮 |
| **AccountCard** | `widgets/account_card.py` | 账号卡片（学号 + 密码 + 时段） |
| **SectionCard** | `widgets/section_card.py` | 通用分组卡片（带标题） |
| **ModeToggle** | `widgets/mode_toggle.py` | 立即 / 定时模式切换开关 |
| **SeatGrid** | `widgets/seat_grid.py` | 座位号网格 + 多选 |
| **StatusPill** | `widgets/status_pill.py` | 状态指示丸（待启动 / 运行中 / 已停止 / 已成功） |
| **CountdownRing** | `widgets/countdown_ring.py` | QPainter 自绘倒计时圆环（30fps 动画） |
| **LogTerminal** | `widgets/log_terminal.py` | 终端样式日志输出（支持彩色 ANSI） |
| **PrimaryButton / GhostButton** | `widgets/buttons.py` | 主 / 次按钮 |
| **SealMark** | `widgets/seal_mark.py` | 学校封印装饰（仅视觉） |

### CountdownRing 关键参数

| 参数 | 值 | 位置 |
|------|---|------|
| 最小尺寸 | 360×360 | `countdown_ring.py:38` |
| 渲染帧率 | 33 ms（~30fps） | `countdown_ring.py:52` |
| 旋转相位增量 | 0.04 rad/tick | `countdown_ring.py:130` |
| 脉冲相位增量 | 0.025 rad/tick | `countdown_ring.py:132` |
| 外环半径比例 | 0.40 | `countdown_ring.py:145` |
| 内环半径比例 | 0.32 | `countdown_ring.py:146` |
| 大号字体 | 54pt | `countdown_ring.py:227` |
| 小号字体 | 38pt | `countdown_ring.py:227` |

完整参数清单见 [NUMERIC_PARAMETERS.md §十七、GUI 界面](NUMERIC_PARAMETERS.md)。

---

## 🧵 Worker 线程模型

> 源码：`ui_qt/workers/booker_worker.py`

### 设计目标

- GUI 线程**绝不阻塞**（Qt 规则）
- 抢座主流程在后台 Worker 线程运行
- Worker 通过**信号**向 GUI 推日志/状态

### 信号槽

```python
class BookerWorker(QObject):
    log_emitted   = Signal(str, str)  # (level, message)
    status_changed = Signal(str)       # "idle" / "running" / "done"
    finished      = Signal(int)        # 退出码

    def run(self):
        # 调用 main.main(stop_event=self._stop_event)
        # 通过 logger handler 把日志 emit 到 GUI
```

### Worker 生命周期

```
GUI 点「开始」
    ↓
QThread + BookerWorker
    ↓
worker.run() → main.main() → 浏览器开抢
    ↓ 各种 log_emitted / status_changed
GUI 实时刷新
    ↓
抢成功 / Ctrl+C / 用户点停止
    ↓
worker.finished → GUI 收尾
```

### 停止机制

GUI 点「停止」按钮 → 设置 `worker._stop_event.set()` → `main.py` 内所有 `wait_until()` / `stop_event.wait()` 立即返回 → 浏览器关闭。

延迟刷新设计：`app.py:235` worker 结束后延迟 **1200ms** 刷新倒计时圆环（让用户看清最终状态）。

---

## ⚙️ Config I/O 服务

> 源码：`ui_qt/services/config_io.py`

### 职责

1. 读写 `config.py`（用户外部覆盖文件）
2. 定义数据模型：`AccountState`, `GuiState`
3. 维护双校区自习室列表：`ROOM_DATA`

### ROOM_DATA 结构

```python
ROOM_DATA = {
    "崇山校区图书馆": [
        "二楼书库北", "二楼书库南", "二楼背诵长廊",
        "三楼智慧研修空间", "三楼理科书库",
        "四楼北自习室", "四楼南自习室", "四楼自习室406",
    ],  # 8 间
    "蒲河校区图书馆": [
        "三楼走廊", "4楼阅览室", "四楼走廊",
        "5楼阅览室", "五楼走廊", "6楼阅览室", "六楼走廊",
        "704", "706", "707", "708", "七楼走廊",
        "智慧空间",  # ← v5 新增
    ],  # 13 间
}
```

### 写入策略

- 用户点「开始」时，把 GUI 状态序列化为 Python 代码写入 `config.py`
- `SCHEDULE_HOUR` / `SCHEDULE_MINUTE` 仅注入内存的 `config` 模块，**不写文件**（避免污染下次启动）

---

## 🛡️ 防休眠服务

> 源码：`ui_qt/services/prevent_sleep.py`

### Windows API 调用

```python
from ctypes import windll
ES_CONTINUOUS       = 0x80000000
ES_SYSTEM_REQUIRED  = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

windll.kernel32.SetThreadExecutionState(
    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
)
```

### 心跳与鼠标抖动

| 参数 | 值 | 位置 | 说明 |
|------|---|------|------|
| 心跳间隔 | 30 秒 | `prevent_sleep.py:25` | 每 30s 重新申请防休眠 |
| 空闲阈值 | 60 秒 | `prevent_sleep.py:26` | 用户空闲超过 60s 触发 |
| 鼠标抖动距离 | 1 px | `prevent_sleep.py:85` | 水平移动 1px 后立即恢复 |

### 退出时还原

GUI 关闭时调用 `SetThreadExecutionState(ES_CONTINUOUS)` 恢复默认休眠策略。

### macOS（caffeinate）

macOS 不用 `SetThreadExecutionState`，而是启动系统自带的 `caffeinate -dimsu` 子进程，阻止显示器 / 系统 / 磁盘休眠并保持用户活跃（`_enable_macos()`）；GUI 关闭时 `terminate()` 该子进程恢复常规休眠（`_disable_macos()`）。上面的**心跳定时器与鼠标抖动是 Windows 专属**，macOS 不需要。其它平台（Linux 等）`enable()` 直接返回 `False`（no-op）。

---

## 📦 打包注意事项

> 源码：`build.py`

### PyInstaller 关键参数

```python
"--collect-all", "PySide6",      # 必须！否则 Qt plugins 丢失
"--collect-all", "cv2",          # OpenCV 原生库
"--collect-all", "numpy",        # numpy 原生库
"--collect-all", "onnxruntime",  # ONNX runtime
"--collect-all", "selenium",
"--collect-all", "ddddocr",
"--windowed",                    # GUI 模式无黑框
"--icon", "logo.ico",
"--runtime-hook", "_runtime_hook.py",  # 设 cwd 让相对路径生效
```

### 排除大依赖

```python
"--exclude-module", "torch",         # 训练用，运行时不需要
"--exclude-module", "torchvision",
"--exclude-module", "timm",
"--exclude-module", "tensorflow",
# ...
```

### 模型权重拷贝

```python
# build.py:154-161
shutil.copytree(
    "core/checkpoints",
    "dist/LNU-LibSeat-v5.0.0/_internal/core/checkpoints"
)
```

这一步保证 ONNX 模型与 exe 一起分发。

---

## 🛠️ 自定义贡献指南

### 添加新组件

1. 在 `ui_qt/widgets/` 下新建 `my_widget.py`
2. 继承 `QWidget` 或现有组件
3. 颜色 / 字体 / 间距统一引用 `theme.C` / `theme.serif()` 等
4. 在 `panels/config_panel.py` 或 `dashboard_panel.py` 中实例化

### 添加新面板

1. 在 `ui_qt/panels/` 下新建 `my_panel.py`
2. 实现一个 QWidget 子类
3. 在 `ui_qt/app.py:MainWindow.__init__` 中加入主布局

### 添加新服务

1. 在 `ui_qt/services/` 下新建 `my_service.py`
2. 在 `MainWindow` 或 `BookerWorker` 中注入

### 主题魔改

只改 `theme.py` 一个文件即可。

> [!TIP]
> 强烈建议保留现有主题色（琥珀 + 海军蓝 + 米白纸感）的对比度——这是经过设计师调整的高可读组合。

---

## 🔗 相关文档

- 📦 [v5.0.0 升级日志](RELEASE_NOTES_V5.md) — 三大重构整体概述
- 🚀 [v3→v5 升级指南](MIGRATION_V3_TO_V5.md)
- 🏗️ [架构文档](ARCHITECTURE.md) — 整体模块分层
- 🧠 [验证码引擎](CAPTCHA_YOLO4_SIAMESE.md) — Worker 调用的核心
- 🔢 [数字参数](NUMERIC_PARAMETERS.md) — GUI 尺寸 / 字体 / 帧率参数清单
- ⚙️ [配置详解](CONFIGURATION.md) — Worker 读写的字段
