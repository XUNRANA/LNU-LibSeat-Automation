"""LNU 印章式圆形装饰，用于顶栏左侧。"""
from __future__ import annotations

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from ..theme import C, serif


class SealMark(QWidget):
    """简化版校徽/印章装饰，QPainter 自绘。"""

    def __init__(self, size=58, label="LNU", parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._label = label

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 2

        # 外圈 深蓝实心
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.INK))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # 内圈 米色 + 琥珀边
        p.setPen(QPen(QColor(C.AMBER), 1.5))
        p.setBrush(QColor(C.BG_PAPER))
        p.drawEllipse(QPointF(cx, cy), r * 0.78, r * 0.78)

        # 中央字
        p.setPen(QColor(C.INK))
        p.setFont(serif(13, bold=True, ls=1))
        p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self._label)
