"""带标题装饰条的卡片容器。

用法::

    card = SectionCard("🎯", "目 标 设 置")
    card.add_widget(my_widget)
    card.add_layout(my_layout)
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QLinearGradient, QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget,
)

from ..theme import C, serif, soft_shadow


class _AccentBar(QWidget):
    """4px 宽渐变竖条。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(4, 22)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0.0, QColor(C.AMBER))
        grad.setColorAt(1.0, QColor(C.AMBER_HOT))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 2, 2)


class SectionCard(QFrame):

    def __init__(self, icon: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sectionCard")
        self.setStyleSheet(f"""
            QFrame#sectionCard {{
                background: {C.CARD};
                border: 1px solid {C.BORDER};
                border-radius: 14px;
            }}
        """)
        self.setGraphicsEffect(soft_shadow(self, blur=20, dy=4, alpha=18))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 18)
        outer.setSpacing(10)

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_AccentBar(), alignment=Qt.AlignmentFlag.AlignVCenter)

        if icon:
            ico = QLabel(icon)
            ico.setFont(serif(14))
            ico.setStyleSheet("background: transparent;")
            header.addWidget(ico, alignment=Qt.AlignmentFlag.AlignVCenter)

        ttl = QLabel(title)
        ttl.setFont(serif(13, bold=True, ls=2))
        ttl.setStyleSheet(f"color: {C.INK}; background: transparent;")
        header.addWidget(ttl, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        outer.addLayout(header)

        # 内容区
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self.content)
        self._content_layout.setContentsMargins(0, 4, 0, 0)
        self._content_layout.setSpacing(10)
        outer.addWidget(self.content)

    # ── 便捷 API ──
    def add_widget(self, widget):
        self._content_layout.addWidget(widget)

    def add_layout(self, layout):
        self._content_layout.addLayout(layout)
