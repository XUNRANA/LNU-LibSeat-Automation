"""日志终端：顶栏 macOS 风圆点 + 三个 tab（全部/主/副），按 levelname 分色。

接收已格式化的日志行（来自 ``core.logger.attach_gui_handler``）：
``"06:29:59.970 INFO 🚀 [12340001] message\\n"``
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QStackedWidget, QVBoxLayout, QWidget,
)

from ..theme import C, mono, sans


_LEVEL_COLOR = {
    "DEBUG":    "#7a8a9a",
    "INFO":     "#e2e8f0",
    "WARNING":  C.WARN,
    "ERROR":    C.ERR,
    "CRITICAL": C.ERR,
}

_LEVEL_RE = re.compile(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s+(\w+)\s")
_ACCOUNT_RE = re.compile(r"\[(\w+)\]")
MAX_ACCOUNT_TABS = 2


class _Dots(QWidget):
    """终端窗口红/黄/绿装饰点。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 14)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, color in enumerate(("#e85a51", "#e7b94a", "#5fb950")):
            p.setBrush(QColor(color))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(2 + i * 18, 2, 10, 10)


def _make_text():
    txt = QPlainTextEdit()
    txt.setReadOnly(True)
    txt.setFont(mono(10))
    txt.setStyleSheet(f"""
        QPlainTextEdit {{
            background: {C.INK_DARK};
            color: #e2e8f0;
            border: none;
            padding: 14px 16px;
            selection-background-color: {C.AMBER_HOT};
        }}
        QScrollBar:vertical {{
            background: {C.INK_DARK};
            width: 8px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background: {C.AMBER_HOT};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0;
        }}
    """)
    return txt


class LogTerminal(QFrame):
    """三 tab 日志终端。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logTerminal")
        self.setStyleSheet(f"""
            QFrame#logTerminal {{
                background: {C.INK_DARK};
                border: 1px solid {C.BORDER_DARK};
                border-radius: 14px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── 顶栏 ──
        head = QFrame()
        head.setStyleSheet(f"background: {C.INK}; border-top-left-radius: 14px; border-top-right-radius: 14px;")
        head.setFixedHeight(46)
        head_l = QHBoxLayout(head)
        head_l.setContentsMargins(16, 0, 12, 0)
        head_l.setSpacing(14)

        head_l.addWidget(_Dots())

        title = QLabel("RUN  LOG")
        title.setFont(sans(10, bold=True, ls=4))
        title.setStyleSheet("color: #f5e2c4; background: transparent;")
        head_l.addWidget(title)

        head_l.addStretch(0)

        # tab 按钮
        self._tabs: list[QPushButton] = []
        tab_names = ["全 部"] + [str(i) for i in range(1, MAX_ACCOUNT_TABS + 1)]
        for i, name in enumerate(tab_names):
            btn = QPushButton(name)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setFont(sans(10, bold=True, ls=2))
            btn.setFixedHeight(28)
            btn.setMinimumWidth(42 if i else 62)
            btn.clicked.connect(lambda _, idx=i: self._switch(idx))
            self._tabs.append(btn)
            head_l.addWidget(btn)

        head_l.addSpacing(6)

        # 清空按钮
        clear = QPushButton("清 空")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.setFont(sans(9, ls=2))
        clear.setFixedHeight(28)
        clear.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {C.TEXT_DIM};
                border: 1px solid {C.AMBER_HOT};
                border-radius: 14px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: rgba(184, 133, 74, 0.2); color: {C.AMBER_LIGHT}; }}
        """)
        clear.clicked.connect(self.clear_all)
        head_l.addWidget(clear)

        outer.addWidget(head)

        # ── 主体 ──
        self._stack = QStackedWidget()
        self._views: list[QPlainTextEdit] = []
        for _ in range(MAX_ACCOUNT_TABS + 1):
            view = _make_text()
            self._stack.addWidget(view)
            self._views.append(view)
        outer.addWidget(self._stack, stretch=1)

        self._accounts: list[str] = []
        self._switch(0)
        self._refresh_tabs()

    # ── 控制 API ──
    def set_accounts(self, accounts: list[str] | tuple[str, ...] | None = None, primary: str = "", secondary: str = ""):
        if accounts is None:
            accounts = [primary, secondary]
        self._accounts = [str(account).strip() for account in accounts[:MAX_ACCOUNT_TABS] if str(account).strip()]
        if self._stack.currentIndex() > len(self._accounts):
            self._switch(0)
        self._refresh_tabs()

    def append_line(self, line: str):
        """接收来自 ``attach_gui_handler`` 的整行字符串（含 ``\\n``）。"""
        if not line:
            return
        if not line.endswith("\n"):
            line = line + "\n"
        text = line.rstrip("\n")
        level = "INFO"
        m = _LEVEL_RE.match(text)
        if m:
            level = m.group(1).upper()
        color = _LEVEL_COLOR.get(level, C.TEXT)

        # 路由：全部 + 按 [account] 命中的 tab
        targets = [0]
        for idx, account in enumerate(self._accounts, start=1):
            if account and f"[{account}]" in text:
                targets.append(idx)

        for idx in targets:
            self._write(self._views[idx], text + "\n", color)

    def append_raw(self, text: str, color=None):
        """无格式直接写入全部 tab，用于 GUI 自身的提示（启动/停止）。"""
        if not text:
            return
        if not text.endswith("\n"):
            text += "\n"
        self._write(self._views[0], text, color or C.AMBER_LIGHT)

    def clear_all(self):
        for v in self._views:
            v.clear()

    # ── 内部 ──
    @staticmethod
    def _write(view: QPlainTextEdit, text: str, color: str):
        cur = view.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur.insertText(text, fmt)
        view.setTextCursor(cur)
        view.ensureCursorVisible()

    def _switch(self, idx: int):
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tabs):
            btn.setChecked(i == idx)
        self._refresh_tabs()

    def _refresh_tabs(self):
        for i, btn in enumerate(self._tabs):
            if i == 0:
                btn.setText("全 部")
                btn.setVisible(True)
            else:
                visible = i <= len(self._accounts)
                btn.setText(str(i))
                btn.setVisible(visible)
            active = btn.isChecked()
            if active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.AMBER};
                        color: {C.INK_DARK};
                        border: none;
                        border-radius: 14px;
                        padding: 0 14px;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: transparent;
                        color: #d4c8a8;
                        border: 1px solid #4a5a78;
                        border-radius: 14px;
                        padding: 0 14px;
                    }}
                    QPushButton:hover {{ background: rgba(212, 165, 116, 0.15); color: {C.AMBER_LIGHT}; }}
                """)
