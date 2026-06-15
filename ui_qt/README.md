# ui_qt/ — PySide6 图形界面

GUI 入口是仓库根的 [`gui_qt.py`](../gui_qt.py)（仅启动 `app.py`）。界面按职责模块化拆分。

| 路径 | 职责 |
|------|------|
| `app.py` | `MainWindow`：装配各面板、加载/保存配置、注入 config、启动 Worker |
| `theme.py` | 全局主题 / 配色 |
| `panels/` | `config_panel.py`（参数表单）、`dashboard_panel.py`（运行面板） |
| `widgets/` | 11 个复用组件：账号卡、倒计时环、日志终端、座位网格、状态药丸、标题栏等 |
| `workers/` | `booker_worker.py`：后台线程跑 `main.main()`，通过信号回传日志/结束 |
| `services/` | `config_io.py`（配置读写 + 校区/自习室数据）、`prevent_sleep.py`（防系统休眠） |

> 详细拆分与信号流见 [`docs/GUI_QT_ARCHITECTURE.md`](../docs/GUI_QT_ARCHITECTURE.md)。
> 本地无 PySide6 时这些模块无法导入，但不影响 `pytest -m "not smoke"`（单测不依赖 GUI）。
