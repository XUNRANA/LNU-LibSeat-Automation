"""立即/定时模式切换按钮组。

两个并排按钮共享一个状态，发出 ``mode_changed(str)`` 信号（``"now"`` 或 ``"scheduled"``）。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..theme import C, sans


class ModeToggle(QWidget):

    mode_changed = Signal(str)

    def __init__(self, default="scheduled", parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._btn_now = self._make_btn("⚡  立 即 执 行")
        self._btn_now.clicked.connect(lambda: self._select("now"))
        layout.addWidget(self._btn_now)

        self._btn_sched = self._make_btn("⏰  定 时 执 行")
        self._btn_sched.clicked.connect(lambda: self._select("scheduled"))
        layout.addWidget(self._btn_sched)

        layout.addStretch(1)

        self._mode = default
        self._refresh()

    def _make_btn(self, text):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setMinimumSize(126, 40)
        b.setFont(sans(11, bold=True, ls=2))
        return b

    def _select(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        self._refresh()
        self.mode_changed.emit(mode)

    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str, silent=True):
        if mode not in ("now", "scheduled") or mode == self._mode:
            return
        self._mode = mode
        self._refresh()
        if not silent:
            self.mode_changed.emit(mode)

    def _refresh(self):
        for btn, key in ((self._btn_now, "now"), (self._btn_sched, "scheduled")):
            if self._mode == key:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        color: {C.TEXT_INVERT};
                        background: {C.INK};
                        border: 1.5px solid {C.INK};
                        border-radius: 20px;
                        padding: 0 18px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        color: {C.INK};
                        background: transparent;
                        border: 1.5px solid {C.BORDER_DARK};
                        border-radius: 20px;
                        padding: 0 18px;
                    }}
                    QPushButton:hover {{
                        background: {C.INK_TINT};
                        border-color: {C.INK};
                    }}
                """)
