"""左侧可滚动配置面板：目标 / 主账号 / 副账号(可隐藏) / 执行设置。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QScrollArea, QVBoxLayout, QWidget,
)

from ..services.config_io import AccountState, GuiState, MAX_ACCOUNTS, ROOM_DATA, account_entries
from ..theme import C, mono, sans
from ..widgets.account_card import AccountCard
from ..widgets.mode_toggle import ModeToggle
from ..widgets.seat_grid import SeatGrid
from ..widgets.section_card import SectionCard


def _styled_combo(values):
    cb = QComboBox()
    cb.setFont(sans(11))
    cb.setMinimumHeight(38)
    cb.addItems(values)
    cb.setStyleSheet(f"""
        QComboBox {{
            background: {C.CARD_SUNK};
            border: 1px solid {C.BORDER};
            border-radius: 8px;
            padding: 0 12px;
            color: {C.INK};
        }}
        QComboBox:focus {{ border: 1.5px solid {C.AMBER}; background: {C.CARD}; }}
        QComboBox::drop-down {{
            border: none;
            width: 26px;
        }}
        QComboBox::down-arrow {{ image: none; }}
        QComboBox QAbstractItemView {{
            background: {C.CARD};
            color: {C.INK};
            border: 1px solid {C.BORDER_DARK};
            selection-background-color: {C.AMBER};
            selection-color: {C.TEXT_INVERT};
            outline: 0;
        }}
    """)
    return cb


def _styled_input(placeholder=""):
    e = QLineEdit()
    e.setFont(sans(11))
    e.setMinimumHeight(38)
    e.setPlaceholderText(placeholder)
    e.setStyleSheet(f"""
        QLineEdit {{
            background: {C.CARD_SUNK};
            border: 1px solid {C.BORDER};
            border-radius: 8px;
            padding: 0 12px;
            color: {C.INK};
        }}
        QLineEdit:focus {{ border: 1.5px solid {C.AMBER}; background: {C.CARD}; }}
    """)
    return e


def _row_label(text, width=68):
    lbl = QLabel(text)
    lbl.setFont(sans(10, ls=2))
    lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
    lbl.setFixedWidth(width)
    return lbl


def _styled_check(text):
    cb = QCheckBox(text)
    cb.setFont(sans(11, ls=2))
    cb.setCursor(Qt.CursorShape.PointingHandCursor)
    cb.setStyleSheet(f"""
        QCheckBox {{ color: {C.INK}; background: transparent; spacing: 8px; }}
        QCheckBox::indicator {{
            width: 18px; height: 18px;
            border-radius: 4px;
            border: 1.5px solid {C.BORDER_DARK};
            background: {C.CARD_SUNK};
        }}
        QCheckBox::indicator:hover {{ border-color: {C.AMBER}; }}
        QCheckBox::indicator:checked {{
            background: {C.AMBER};
            border-color: {C.AMBER_HOT};
            image: none;
        }}
    """)
    return cb


class ConfigPanel(QWidget):

    mode_changed = Signal(str)
    sched_time_changed = Signal()  # 任意 hh/mm 改变都发出

    def __init__(self, parent=None):
        super().__init__(parent)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_DARK};
                border-radius: 4px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {C.AMBER_HOT}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        # 容器
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body_l = QVBoxLayout(body)
        body_l.setContentsMargins(0, 0, 8, 0)
        body_l.setSpacing(16)

        body_l.addWidget(self._build_target_card())
        body_l.addWidget(self._build_account_card())
        body_l.addWidget(self._build_execution_card())
        body_l.addStretch(1)

        scroll.setWidget(body)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ────────── 目标卡 ──────────
    def _build_target_card(self):
        card = SectionCard("🎯", "目  标  设  置")

        # 校区
        row = QHBoxLayout()
        row.addWidget(_row_label("校  区"))
        self.cb_campus = _styled_combo(list(ROOM_DATA.keys()))
        self.cb_campus.currentTextChanged.connect(self._on_campus_change)
        row.addWidget(self.cb_campus, stretch=1)
        card.add_layout(row)

        # 自习室
        row = QHBoxLayout()
        row.addWidget(_row_label("自 习 室"))
        self.cb_room = _styled_combo(ROOM_DATA["崇山校区图书馆"])
        row.addWidget(self.cb_room, stretch=1)
        card.add_layout(row)

        # 优先座位
        seat_row = QHBoxLayout()
        seat_lbl = _row_label("优先座位", width=78)
        seat_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        seat_row.addWidget(seat_lbl)
        self.seats = SeatGrid()
        seat_row.addWidget(self.seats, stretch=1)
        card.add_layout(seat_row)

        return card

    def _on_campus_change(self, campus):
        rooms = ROOM_DATA.get(campus, [])
        self.cb_room.clear()
        self.cb_room.addItems(rooms)

    # ────────── 账号卡 ──────────
    def _build_account_card(self):
        card = SectionCard("👤", "账  号  设  置")

        self.account_cards: list[AccountCard] = []
        for idx in range(MAX_ACCOUNTS):
            title = f"账  号  {idx + 1}"
            account_card = AccountCard(title)
            account_card.setVisible(idx == 0)
            self.account_cards.append(account_card)
            if idx == 0:
                self.acc1 = account_card
                card.add_widget(account_card)

        self.chk_use_acc2 = _styled_check(f"启 用 更 多 账 号（最 多 {MAX_ACCOUNTS} 个）")
        self.chk_use_acc2.toggled.connect(self._on_toggle_acc2)
        card.add_widget(self.chk_use_acc2)

        for account_card in self.account_cards[1:]:
            card.add_widget(account_card)
        self.acc2 = self.account_cards[1]

        # 邮箱
        email_row = QHBoxLayout()
        email_row.setSpacing(10)
        email_lbl = _row_label("通知邮箱", width=78)
        email_row.addWidget(email_lbl)
        self.email_input = _styled_input("example@email.com")
        email_row.addWidget(self.email_input, stretch=1)
        card.add_layout(email_row)

        return card

    def _on_toggle_acc2(self, checked):
        for account_card in self.account_cards[1:]:
            account_card.setVisible(checked)

    # ────────── 执行卡 ──────────
    def _build_execution_card(self):
        card = SectionCard("⚡", "执  行  设  置")

        self.mode_toggle = ModeToggle(default="scheduled")
        self.mode_toggle.mode_changed.connect(self._on_mode_change)
        card.add_widget(self.mode_toggle)

        # 定时时间面板（默认显示，立即模式时隐藏）
        self.sched_frame = QFrame()
        self.sched_frame.setObjectName("schedFrame")
        self.sched_frame.setStyleSheet(f"""
            QFrame#schedFrame {{
                background: {C.INK_TINT};
                border: 1px solid {C.INK_LIGHT};
                border-radius: 10px;
            }}
        """)
        sf = QHBoxLayout(self.sched_frame)
        sf.setContentsMargins(16, 12, 16, 12)
        sf.setSpacing(10)

        sf_lbl = QLabel("抢座时间")
        sf_lbl.setFont(sans(10, ls=2))
        sf_lbl.setStyleSheet(f"color: {C.INK}; background: transparent;")
        sf_lbl.setFixedWidth(78)
        sf.addWidget(sf_lbl)

        self.sched_hour = QLineEdit("06")
        self._style_time_box(self.sched_hour)
        sf.addWidget(self.sched_hour)

        sep = QLabel(":")
        sep.setFont(mono(15, bold=True))
        sep.setStyleSheet(f"color: {C.INK}; background: transparent;")
        sep.setFixedWidth(8)
        sf.addWidget(sep)

        self.sched_min = QLineEdit("30")
        self._style_time_box(self.sched_min)
        sf.addWidget(self.sched_min)

        tz_lbl = QLabel("北 京 时 间")
        tz_lbl.setFont(sans(9, ls=2))
        tz_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        sf.addWidget(tz_lbl)
        sf.addStretch(1)

        for w in (self.sched_hour, self.sched_min):
            w.textChanged.connect(lambda _t: self.sched_time_changed.emit())

        card.add_widget(self.sched_frame)

        return card

    def _style_time_box(self, edit: QLineEdit):
        edit.setFont(mono(14, bold=True))
        edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit.setMaxLength(2)
        edit.setFixedSize(58, 38)
        edit.setStyleSheet(f"""
            QLineEdit {{
                background: {C.CARD};
                border: 1.5px solid {C.INK};
                border-radius: 8px;
                color: {C.INK};
            }}
            QLineEdit:focus {{ border-color: {C.AMBER}; }}
        """)

    def _on_mode_change(self, mode):
        self.sched_frame.setVisible(mode == "scheduled")
        self.mode_changed.emit(mode)

    # ────────── 状态读写 ──────────
    def collect_state(self) -> GuiState:
        s = GuiState()
        s.campus = self.cb_campus.currentText()
        s.room = self.cb_room.currentText()
        s.seats = self.seats.seats()
        s.accounts = []
        for idx, account_card in enumerate(self.account_cards):
            if idx > 0 and not self.chk_use_acc2.isChecked():
                continue
            start, end = account_card.time_range()
            entry = AccountState(
                account=account_card.account(),
                password=account_card.password(),
                start=start,
                end=end,
            )
            has_value = bool(entry.account or entry.password or entry.start or entry.end)
            if idx == 0 or has_value:
                s.accounts.append(entry)
        s.sync_legacy_fields()
        s.email = self.email_input.text().strip()
        s.mode = self.mode_toggle.mode()
        try:
            s.sched_hour = int(self.sched_hour.text() or "6")
        except ValueError:
            s.sched_hour = 6
        try:
            s.sched_min = int(self.sched_min.text() or "30")
        except ValueError:
            s.sched_min = 30
        return s

    def apply_state(self, state: GuiState):
        # 校区先于自习室设置（触发 cascade 后再覆盖自习室）
        idx = self.cb_campus.findText(state.campus)
        if idx >= 0:
            self.cb_campus.setCurrentIndex(idx)
        idx = self.cb_room.findText(state.room)
        if idx >= 0:
            self.cb_room.setCurrentIndex(idx)

        self.seats.set_seats(state.seats)
        entries = account_entries(state, include_empty=True)
        while len(entries) < MAX_ACCOUNTS:
            entries.append(AccountState())
        for idx, account_card in enumerate(self.account_cards):
            entry = entries[idx]
            account_card.set_values(entry.account, entry.password, entry.start, entry.end)
        has_extra_accounts = any(
            entry.account or entry.password or entry.start or entry.end
            for entry in entries[1:]
        )
        self.chk_use_acc2.setChecked(has_extra_accounts)
        self._on_toggle_acc2(has_extra_accounts)
        self.email_input.setText(state.email)
        self.mode_toggle.set_mode(state.mode, silent=False)
        self.sched_hour.setText(f"{state.sched_hour:02d}")
        self.sched_min.setText(f"{state.sched_min:02d}")

    def set_form_enabled(self, enabled: bool):
        for w in (
            self.cb_campus, self.cb_room, self.seats,
            *self.account_cards, self.chk_use_acc2,
            self.email_input, self.mode_toggle,
            self.sched_hour, self.sched_min,
        ):
            w.setEnabled(enabled)
