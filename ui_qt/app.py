"""主窗口：HeaderBar + 左 ConfigPanel / 右 DashboardPanel + 启停控制。"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from core import paths

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QVBoxLayout, QWidget,
)

from .panels.config_panel import ConfigPanel
from .panels.dashboard_panel import DashboardPanel
from .services import config_io, prevent_sleep
from .theme import C, serif
from .widgets.header_bar import HeaderBar
from .widgets.title_bar import TitleBar
from .workers.booker_worker import BookerWorker


def _bj_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def _logo_path() -> str:
    base = paths.resource_root()
    logo = base / "logo1.png"
    if not logo.exists():
        logo = base / "logo.ico"
    return str(logo)


def _double_separator():
    box = QWidget()
    box.setFixedHeight(7)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    line1 = QFrame()
    line1.setFixedHeight(1)
    line1.setStyleSheet(f"background: {C.BORDER_DARK};")
    layout.addWidget(line1)
    layout.addSpacing(3)
    line2 = QFrame()
    line2.setFixedHeight(1)
    line2.setStyleSheet(f"background: {C.BORDER};")
    layout.addWidget(line2)
    return box


def _app_icon():
    return QIcon(_logo_path())


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LNU  LibSeat 图书馆智能抢座系统")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.resize(1400, 920)
        self.setMinimumSize(1100, 760)

        self._config_path = str(paths.app_data_dir() / "config.py")
        self._anti_sleep_enabled = False

        # 中央容器
        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 自定义系统标题栏
        self.title_bar = TitleBar(self.windowTitle(), _logo_path())
        outer.addWidget(self.title_bar)

        # 顶栏
        self.header = HeaderBar()
        outer.addWidget(self.header)
        outer.addWidget(_double_separator())

        # 主体
        body = QWidget()
        body_l = QHBoxLayout(body)
        body_l.setContentsMargins(40, 22, 40, 22)
        body_l.setSpacing(28)

        self.config_panel = ConfigPanel()
        self.config_panel.setMinimumWidth(420)
        self.config_panel.setMaximumWidth(600)
        body_l.addWidget(self.config_panel, stretch=45)

        self.dashboard = DashboardPanel()
        body_l.addWidget(self.dashboard, stretch=55)

        outer.addWidget(body, stretch=1)

        # 底部 footer
        footer = QLabel("·   EST. 1948   ·   辽 宁 大 学 图 书 馆   ·   LIBSEAT   ·")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(serif(8, ls=4))
        footer.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; padding: 12px 0 14px 0;"
        )
        outer.addWidget(footer)

        # ── Worker ──
        self.worker = BookerWorker(self)
        self.worker.log_line.connect(self._on_log_line)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.error.connect(self._on_worker_error)

        # ── 信号连接 ──
        self.config_panel.mode_changed.connect(self._refresh_ring_target)
        self.config_panel.sched_time_changed.connect(self._refresh_ring_target)
        self.dashboard.start_clicked.connect(self._on_start)
        self.dashboard.stop_clicked.connect(self._on_stop)

        # ── 加载配置 ──
        try:
            state = config_io.load_state(self._config_path)
            self.config_panel.apply_state(state)
        except Exception as exc:  # noqa: BLE001
            self.dashboard.log.append_raw(f"⚠️ 配置载入失败: {exc}\n", color=C.WARN)

        self._refresh_ring_target()

    # ────────── 倒计时刷新 ──────────
    def _refresh_ring_target(self):
        s = self.config_panel.collect_state()
        if s.mode == "scheduled":
            now = _bj_now()
            target = now.replace(
                hour=s.sched_hour, minute=s.sched_min,
                second=0, microsecond=0,
            )
            if target <= now:
                target += timedelta(days=1)
            total = max(1, int((target - now).total_seconds()))
            self.dashboard.ring.set_scheduled(target, total_seconds=total)
        else:
            self.dashboard.ring.set_now()

    # ────────── 启动 ──────────
    def _on_start(self):
        state = self.config_panel.collect_state()
        ok, msg = config_io.validate(state)
        if not ok:
            QMessageBox.warning(self, "请检查配置", msg)
            return

        try:
            config_io.save_state_to_file(state, self._config_path)
        except Exception as exc:  # noqa: BLE001
            self.dashboard.log.append_raw(f"⚠️ 配置保存失败（继续运行）: {exc}\n", color=C.WARN)

        try:
            config_io.inject_into_sys_modules(state)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "启动失败", f"配置注入失败: {exc}")
            return

        accounts = [entry.account for entry in config_io.account_entries(state) if entry.account]

        # 配置 LogTerminal 的账号路由
        self.dashboard.log.set_accounts(accounts=accounts)
        self.dashboard.log.clear_all()

        n_acc = f"{len(accounts)} 个账号"
        mode_label = "立即执行" if state.mode == "now" else f"定时 {state.sched_hour:02d}:{state.sched_min:02d}"
        self.dashboard.log.append_raw(
            f">>> {n_acc} | {mode_label} | 启动中...\n",
            color=C.AMBER_LIGHT,
        )

        # 防休眠
        if prevent_sleep.enable():
            self._anti_sleep_enabled = True
            self.dashboard.log.append_raw(">>> 🟢 已开启防休眠\n", color=C.AMBER_LIGHT)

        # 状态切换
        self.config_panel.set_form_enabled(False)
        self.dashboard.set_running_state(True)
        if state.mode == "scheduled":
            now = _bj_now()
            target = now.replace(
                hour=state.sched_hour, minute=state.sched_min,
                second=0, microsecond=0,
            )
            if target <= now:
                target += timedelta(days=1)
            total = max(1, int((target - now).total_seconds()))
            self.dashboard.ring.set_waiting(target, total_seconds=total)
            self.header.set_status("等 待 中", C.AMBER)
        else:
            self.dashboard.ring.set_running()
            self.header.set_status("运 行 中", C.OK)

        self.worker.start_booking()

    # ────────── 停止 ──────────
    def _on_stop(self):
        self.dashboard.log.append_raw("\n>>> 正在停止...\n", color=C.AMBER_LIGHT)
        self.header.set_status("停 止 中", C.ERR)
        self.worker.stop()

    # ────────── Worker 回调 ──────────
    def _on_log_line(self, line: str):
        self.dashboard.log.append_line(line)

    def _on_worker_finished(self):
        self.dashboard.log.append_raw("\n>>> 程序已结束\n", color=C.AMBER_LIGHT)
        self.config_panel.set_form_enabled(True)
        self.dashboard.set_running_state(False)
        self.dashboard.ring.set_done(success=True)
        self.header.set_status("已 完 成", C.INK)

        if self._anti_sleep_enabled:
            prevent_sleep.disable()
            self._anti_sleep_enabled = False
            self.dashboard.log.append_raw(">>> 🔴 已恢复系统常规休眠策略\n", color=C.AMBER_LIGHT)

        # 倒计时面板回到对应模式
        QTimer.singleShot(1200, self._refresh_ring_target)

    def _on_worker_error(self, exc_text: str):
        self.dashboard.log.append_raw(f"\n❌ {exc_text}\n", color=C.ERR_LIGHT)

    def changeEvent(self, event):  # noqa: N802 - Qt override
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.sync_window_state()

    # ────────── 关闭 ──────────
    def closeEvent(self, event):
        if self.worker.is_running():
            ans = QMessageBox.question(
                self, "确认退出", "抢座任务正在运行，确定退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.stop()
        if self._anti_sleep_enabled:
            prevent_sleep.disable()
        event.accept()


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("Fusion")

    pal = app.palette()
    pal.setColor(QPalette.ColorRole.Window, QColor(C.BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(C.TEXT))
    app.setPalette(pal)

    icon = _app_icon()
    app.setWindowIcon(icon)

    win = MainWindow()
    win.setWindowIcon(icon)
    win.showMaximized()

    sys.exit(app.exec())
