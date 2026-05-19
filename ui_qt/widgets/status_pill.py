"""状态胶囊：脉冲圆点 + 文字标签。"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QWidget

from ..theme import C, sans


class _PulseDot(QWidget):
    """会呼吸的圆点。颜色由父级注入。"""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._phase = 0.0
        self.setFixedSize(12, 12)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def set_color(self, color):
        self._color = QColor(color)
        self.update()

    def _tick(self):
        self._phase = (self._phase + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r_max = min(self.width(), self.height()) / 2

        alpha = 0.25 + 0.45 * (0.5 + 0.5 * math.sin(self._phase))
        glow = QColor(self._color)
        glow.setAlphaF(alpha)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r_max, r_max)

        p.setBrush(self._color)
        p.drawEllipse(QPointF(cx, cy), r_max * 0.45, r_max * 0.45)


class StatusPill(QFrame):
    """顶栏右侧状态胶囊。``set_state(text, color)`` 切换显示。"""

    def __init__(self, text="就 绪", color=C.OK, parent=None):
        super().__init__(parent)
        self._dot_color = color
        self.setFixedHeight(38)
        self.setMinimumWidth(120)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 20, 0)
        layout.setSpacing(11)

        self._dot = _PulseDot(color, self)
        layout.addWidget(self._dot, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._lbl = QLabel(text)
        self._lbl.setFont(sans(10, bold=True, ls=2))
        layout.addWidget(self._lbl)
        layout.addStretch(0)

        self._refresh()

    def set_state(self, text, color):
        self._dot_color = color
        self._dot.set_color(color)
        self._lbl.setText(text)
        self._refresh()

    def _refresh(self):
        self.setStyleSheet(f"""
            StatusPill {{
                background: {C.CARD};
                border: 1px solid {C.BORDER_DARK};
                border-radius: 19px;
            }}
            QLabel {{
                color: {self._dot_color};
                background: transparent;
            }}
        """)
