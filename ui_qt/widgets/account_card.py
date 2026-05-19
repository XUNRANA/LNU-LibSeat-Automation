"""单账号配置卡：学号 + 密码 + 起止时段。主/副账号复用。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from ..theme import C, mono, sans


def _make_input(placeholder="", password=False):
    e = QLineEdit()
    e.setFont(sans(11))
    e.setPlaceholderText(placeholder)
    e.setMinimumHeight(38)
    if password:
        e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setStyleSheet(f"""
        QLineEdit {{
            background: {C.CARD_SUNK};
            border: 1px solid {C.BORDER};
            border-radius: 8px;
            padding: 0 12px;
            color: {C.INK};
        }}
        QLineEdit:focus {{
            border: 1.5px solid {C.AMBER};
            background: {C.CARD};
        }}
        QLineEdit:disabled {{
            color: {C.TEXT_DIM};
            background: {C.BG};
        }}
    """)
    return e


def _make_time_input(placeholder="xx:00", width=82):
    e = QLineEdit()
    e.setFont(mono(11))
    e.setAlignment(Qt.AlignmentFlag.AlignCenter)
    e.setMaxLength(5)
    e.setFixedSize(width, 38)
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(f"""
        QLineEdit {{
            background: {C.CARD_SUNK};
            border: 1px solid {C.BORDER};
            border-radius: 8px;
            color: {C.INK};
        }}
        QLineEdit:focus {{
            border: 1.5px solid {C.AMBER};
            background: {C.CARD};
        }}
        QLineEdit:disabled {{
            color: {C.TEXT_DIM};
            background: {C.BG};
        }}
    """)
    return e


class AccountCard(QFrame):

    def __init__(self, title="主 账 号", default_start="", default_end="", parent=None):
        super().__init__(parent)
        self.setObjectName("accountCard")
        self.setStyleSheet(f"""
            QFrame#accountCard {{
                background: {C.BG_PAPER};
                border: 1px solid {C.BORDER};
                border-radius: 12px;
            }}
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        title_label = QLabel(title)
        title_label.setFont(sans(10, bold=True, ls=2))
        title_label.setStyleSheet(f"color: {C.INK}; background: transparent;")
        outer.addWidget(title_label)

        # 学号
        outer.addLayout(self._labeled_row("学  号", placeholder="请输入学号", attr="student_id"))
        # 密码
        outer.addLayout(self._labeled_row("密  码", placeholder="请输入密码", attr="password",
                                           password=True))

        # 时段
        time_row = QHBoxLayout()
        time_row.setSpacing(10)
        time_lbl = QLabel("时  段")
        time_lbl.setFont(sans(10, ls=2))
        time_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        time_lbl.setFixedWidth(60)
        time_row.addWidget(time_lbl)

        self.start_input = _make_time_input("现在/xx:00", width=108)
        self.start_input.setText(default_start)
        time_row.addWidget(self.start_input)

        arrow = QLabel("→")
        arrow.setFont(sans(13, bold=True))
        arrow.setStyleSheet(f"color: {C.AMBER_HOT}; background: transparent;")
        arrow.setFixedWidth(20)
        arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        time_row.addWidget(arrow)

        self.end_input = _make_time_input("xx:00")
        self.end_input.setText(default_end)
        time_row.addWidget(self.end_input)
        time_row.addStretch(1)
        outer.addLayout(time_row)

    def _labeled_row(self, label, placeholder="", attr="", password=False):
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label)
        lbl.setFont(sans(10, ls=2))
        lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        lbl.setFixedWidth(60)
        row.addWidget(lbl)

        edit = _make_input(placeholder, password=password)
        row.addWidget(edit, stretch=1)
        setattr(self, f"{attr}_input", edit)

        if password:
            btn = QPushButton("显 示")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.setFixedSize(62, 38)
            btn.setFont(sans(9, bold=True, ls=1))
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {C.INK};
                    background: transparent;
                    border: 1px solid {C.BORDER_DARK};
                    border-radius: 8px;
                }}
                QPushButton:hover {{
                    background: {C.INK_TINT};
                    border-color: {C.INK};
                }}
                QPushButton:checked {{
                    color: {C.TEXT_INVERT};
                    background: {C.INK};
                    border-color: {C.INK};
                }}
                QPushButton:disabled {{
                    color: {C.TEXT_DIM};
                    background: {C.BG};
                    border-color: {C.BORDER};
                }}
            """)

            def toggle_password_visible(checked, input_box=edit, button=btn):
                input_box.setEchoMode(
                    QLineEdit.EchoMode.Normal
                    if checked else QLineEdit.EchoMode.Password
                )
                button.setText("隐 藏" if checked else "显 示")

            btn.toggled.connect(toggle_password_visible)
            row.addWidget(btn)
            self.password_toggle_btn = btn

        return row

    # ── API ──
    def account(self) -> str:
        return self.student_id_input.text().strip()

    def password(self) -> str:
        return self.password_input.text()

    def time_range(self) -> tuple[str, str]:
        return (
            self.start_input.text().strip(),
            self.end_input.text().strip(),
        )

    def set_values(self, account="", password="", start="", end=""):
        self.student_id_input.setText(account)
        self.password_input.setText(password)
        self.start_input.setText(start)
        self.end_input.setText(end)


