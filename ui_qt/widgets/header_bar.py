"""顶部系统标题栏：居中 logo + 标题 / 右状态胶囊。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..theme import C, serif
from .seal_mark import SealMark
from .status_pill import StatusPill


class HeaderBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(132)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(48, 20, 48, 20)
        layout.setSpacing(20)

        side_w = 180

        left_spacer = QWidget()
        left_spacer.setFixedWidth(side_w)
        layout.addWidget(left_spacer)

        title_group = QWidget()
        title_group_l = QHBoxLayout(title_group)
        title_group_l.setContentsMargins(0, 0, 0, 0)
        title_group_l.setSpacing(22)
        title_group_l.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_group_l.addWidget(SealMark(size=88), alignment=Qt.AlignmentFlag.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setSpacing(10)
        title_box.setContentsMargins(0, 0, 0, 0)

        title = QLabel("LNU  LibSeat 图书馆智能抢座系统")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(serif(24, bold=True, ls=1))
        title.setStyleSheet(f"color: {C.INK}; background: transparent;")
        title_box.addWidget(title)

        sub = QLabel("LIAONING UNIVERSITY LIBRARY  ·  LIBSEAT AUTOMATION")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(serif(15, ls=2))
        sub.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        title_box.addWidget(sub)

        title_w = QWidget()
        title_w.setLayout(title_box)
        title_group_l.addWidget(title_w, alignment=Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(title_group, stretch=1)

        self.pill = StatusPill("就 绪", C.OK)
        right = QWidget()
        right.setFixedWidth(side_w)
        right_l = QHBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)
        right_l.addStretch(1)
        right_l.addWidget(self.pill, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(right)

    # ── API 转发 ──
    def set_status(self, text: str, color: str):
        self.pill.set_state(text, color)
