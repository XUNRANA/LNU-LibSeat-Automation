"""辽大学院风主题：配色、字体、阴影工具。"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QGraphicsDropShadowEffect


class C:
    """调色板。所有颜色集中在这里，改一处全局生效。"""

    # 纸感背景
    BG          = "#f5f1e8"   # 米白
    BG_PAPER    = "#faf6ec"   # 略亮纸

    # 卡片
    CARD        = "#fdfcf8"   # 蛋壳白
    CARD_SUNK   = "#f0ead9"   # 内嵌区域底色（稍暗于 CARD）
    BORDER      = "#e8e2d3"   # 浅琥珀边
    BORDER_DARK = "#cbbe97"

    # 主色 LNU 海军蓝
    INK         = "#003876"
    INK_LIGHT   = "#1e5599"
    INK_DARK    = "#002654"
    INK_TINT    = "#e2eaf3"   # 极浅蓝（hover/selected 背景）

    # 强调 琥珀
    AMBER       = "#d4a574"
    AMBER_HOT   = "#b8854a"
    AMBER_LIGHT = "#e8c896"
    AMBER_GLOW  = "#f5e2c4"

    # 文字
    TEXT        = "#1a1a1a"
    TEXT_MUTED  = "#5a5a5a"
    TEXT_DIM    = "#9a9a9a"
    TEXT_INVERT = "#fdfcf8"

    # 状态
    OK          = "#5b8c5a"
    WARN        = "#c8923c"
    ERR         = "#9b3838"
    ERR_LIGHT   = "#f0d8d8"


# ── 字体族 ──
SERIF = ["Source Han Serif SC", "Noto Serif SC", "STSong", "宋体", "SimSun"]
SANS  = ["Microsoft YaHei UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", "Segoe UI"]
MONO  = ["JetBrains Mono", "Cascadia Code", "Consolas", "Courier New"]


def _font(families, size, bold=False, ls=0):
    f = QFont()
    f.setFamilies(families)
    f.setPointSize(size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    if ls:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, ls)
    return f


def serif(size, bold=False, ls=0): return _font(SERIF, size, bold=bold, ls=ls)
def sans(size, bold=False, ls=0):  return _font(SANS,  size, bold=bold, ls=ls)
def mono(size, bold=False, ls=0):  return _font(MONO,  size, bold=bold, ls=ls)


def soft_shadow(parent, blur=24, dy=4, color="#003876", alpha=30):
    """带柔和阴影的图形特效，传给 ``QWidget.setGraphicsEffect``。"""
    eff = QGraphicsDropShadowEffect(parent)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    qc = QColor(color)
    qc.setAlpha(alpha)
    eff.setColor(qc)
    return eff
