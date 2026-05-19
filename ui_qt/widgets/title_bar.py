"""Frameless window title bar with centered title and window controls."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from ..theme import C, sans


class TitleBar(QWidget):
    """Custom title bar so the window title can be centered."""

    CONTROL_WIDTH = 46
    CONTROL_HEIGHT = 34

    def __init__(self, title: str, icon_path: str = "", parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self._drag_offset = None

        self.setStyleSheet(f"""
            TitleBar {{
                background: {C.BG_PAPER};
                border-bottom: 1px solid {C.BORDER};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)

        icon = QLabel()
        icon.setFixedSize(22, 22)
        icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if icon_path and os.path.exists(icon_path):
            icon.setPixmap(QIcon(icon_path).pixmap(22, 22))
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.title = QLabel(title)
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.title.setFont(sans(13, bold=True, ls=1))
        self.title.setStyleSheet(f"color: {C.INK}; background: transparent;")
        layout.addWidget(self.title, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        controls = QWidget()
        controls.setFixedWidth(self.CONTROL_WIDTH * 3)
        controls_l = QHBoxLayout(controls)
        controls_l.setContentsMargins(0, 0, 0, 0)
        controls_l.setSpacing(0)

        self.btn_min = self._make_button("—")
        self.btn_min.clicked.connect(lambda: self.window().showMinimized())
        controls_l.addWidget(self.btn_min)

        self.btn_max = self._make_button("□")
        self.btn_max.clicked.connect(self._toggle_max_restore)
        controls_l.addWidget(self.btn_max)

        self.btn_close = self._make_button("×", close=True)
        self.btn_close.clicked.connect(lambda: self.window().close())
        controls_l.addWidget(self.btn_close)

        layout.addWidget(controls)

    def _make_button(self, text: str, close=False):
        btn = QPushButton(text)
        btn.setFixedSize(self.CONTROL_WIDTH, self.CONTROL_HEIGHT)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFont(sans(12, bold=True))
        hover_bg = C.ERR if close else C.INK_TINT
        hover_fg = C.TEXT_INVERT if close else C.INK
        btn.setStyleSheet(f"""
            QPushButton {{
                color: {C.INK};
                background: transparent;
                border: none;
            }}
            QPushButton:hover {{
                color: {hover_fg};
                background: {hover_bg};
            }}
            QPushButton:pressed {{
                background: {C.BORDER_DARK};
            }}
        """)
        return btn

    def _toggle_max_restore(self):
        win = self.window()
        if win.isMaximized():
            win.showNormal()
        else:
            win.showMaximized()
        self.sync_window_state()

    def sync_window_state(self):
        self.btn_max.setText("❐" if self.window().isMaximized() else "□")

    def mousePressEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle and handle.startSystemMove():
                event.accept()
                return
            self._drag_offset = event.globalPosition().toPoint() - self.window().pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 - Qt override
        if self._drag_offset is not None and not self.window().isMaximized():
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802 - Qt override
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_max_restore()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
