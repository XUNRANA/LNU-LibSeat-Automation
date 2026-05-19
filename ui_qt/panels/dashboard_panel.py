"""右侧仪表盘：上方 logo + 倒计时英雄区，启停按钮，下方日志终端。"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from ..widgets.buttons import GhostButton, PrimaryButton
from ..widgets.countdown_ring import CountdownRing
from ..widgets.log_terminal import LogTerminal


HERO_CIRCLE_SIZE = 360


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class LogoImage(QLabel):
    """Scales the root logo image while preserving aspect ratio."""

    def __init__(self, parent=None):
        super().__init__(parent)
        logo_path = os.path.join(_base_dir(), "logo1.png")
        self._pixmap = QPixmap(logo_path)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(HERO_CIRCLE_SIZE, HERO_CIRCLE_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setStyleSheet("background: transparent;")
        self._refresh_pixmap()

    def resizeEvent(self, event):  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._refresh_pixmap()

    def sizeHint(self):  # noqa: N802 - Qt override
        return QSize(HERO_CIRCLE_SIZE, HERO_CIRCLE_SIZE)

    def _refresh_pixmap(self):
        if self._pixmap.isNull():
            self.clear()
            return
        self.setPixmap(
            self._pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )


class DashboardPanel(QWidget):

    start_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(18)

        # ── 英雄区 ──
        hero = QWidget()
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(0, 0, 0, 0)
        hero_l.setSpacing(18)
        hero_l.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        visual_row = QHBoxLayout()
        visual_row.setContentsMargins(0, 0, 0, 0)
        visual_row.setSpacing(36)
        visual_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.logo = LogoImage()
        visual_row.addWidget(self.logo, alignment=Qt.AlignmentFlag.AlignCenter)

        self.ring = CountdownRing()
        self.ring.setFixedSize(HERO_CIRCLE_SIZE, HERO_CIRCLE_SIZE)
        visual_row.addWidget(self.ring, alignment=Qt.AlignmentFlag.AlignCenter)

        hero_l.addLayout(visual_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(14)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_start = PrimaryButton("立  即  抢  座    →")
        self.btn_start.clicked.connect(self.start_clicked.emit)
        btn_row.addWidget(self.btn_start)

        self.btn_stop = GhostButton("中  止", danger=True)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_clicked.emit)
        btn_row.addWidget(self.btn_stop)

        hero_l.addLayout(btn_row)
        outer.addWidget(hero, stretch=0)

        # ── 日志终端 ──
        self.log = LogTerminal()
        outer.addWidget(self.log, stretch=1)

    # ── 状态切换辅助 ──
    def set_running_state(self, running: bool):
        self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
