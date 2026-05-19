"""10 个优先座位号输入栅格（2 行 × 5 列）。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLineEdit, QWidget

from ..theme import C, mono


class SeatGrid(QWidget):

    SLOT_COUNT = 10

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)

        self._inputs: list[QLineEdit] = []
        for i in range(self.SLOT_COUNT):
            edit = QLineEdit()
            edit.setFont(mono(13))
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            edit.setPlaceholderText(f"{i + 1:03d}")
            edit.setMaxLength(8)
            edit.setFixedHeight(40)
            edit.setMinimumWidth(64)
            edit.setStyleSheet(f"""
                QLineEdit {{
                    background: {C.CARD_SUNK};
                    border: 1px solid {C.BORDER};
                    border-radius: 8px;
                    padding: 0 6px;
                    color: {C.INK};
                }}
                QLineEdit:focus {{
                    border: 1.5px solid {C.AMBER};
                    background: {C.CARD};
                }}
            """)
            row, col = divmod(i, 5)
            layout.addWidget(edit, row, col)
            self._inputs.append(edit)

    # ── API ──
    def seats(self) -> list[str]:
        return [e.text().strip() for e in self._inputs if e.text().strip()]

    def set_seats(self, values):
        for i, e in enumerate(self._inputs):
            e.setText(values[i] if i < len(values) else "")
