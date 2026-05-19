"""按钮族：PrimaryButton（琥珀填充）/ GhostButton（透明描边）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from ..theme import C, sans, soft_shadow


class PrimaryButton(QPushButton):
    """琥珀渐变主按钮，自带阴影。"""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(280, 56)
        self.setFont(sans(13, bold=True, ls=3))
        self.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_INVERT};
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {C.AMBER}, stop:1 {C.AMBER_HOT});
                border: none;
                border-radius: 28px;
                padding: 0 32px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 {C.AMBER_HOT}, stop:1 #8e6534);
            }}
            QPushButton:pressed {{ background: #8e6534; }}
            QPushButton:disabled {{
                color: #b8b3a6;
                background: {C.BORDER};
            }}
        """)
        self.setGraphicsEffect(soft_shadow(self, blur=28, dy=8, color=C.AMBER_HOT, alpha=80))


class GhostButton(QPushButton):
    """透明描边次要按钮。``danger=True`` 切换为危险色。"""

    def __init__(self, text, parent=None, danger=False):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(120, 56)
        self.setFont(sans(11, bold=True, ls=2))
        c = C.ERR if danger else C.INK
        bg_hover = C.ERR_LIGHT if danger else C.INK_TINT
        self.setStyleSheet(f"""
            QPushButton {{
                color: {c};
                background: transparent;
                border: 1.5px solid {c};
                border-radius: 28px;
                padding: 0 22px;
            }}
            QPushButton:hover {{ background: {bg_hover}; }}
            QPushButton:disabled {{
                color: {C.TEXT_DIM};
                border-color: {C.BORDER};
            }}
        """)
