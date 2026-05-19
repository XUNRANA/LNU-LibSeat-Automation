"""倒计时圆环：接受目标时间 + 多模式（idle / scheduled / now / running / done）。

用法::

    ring = CountdownRing()
    ring.set_scheduled(target_dt)   # 倒计时模式
    ring.set_now()                  # 立即模式（无倒计时数字）
    ring.set_running()              # 抢座中（圆环琥珀全亮 + 跑马动画）
    ring.set_idle()                 # 待机
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import C, mono, serif


def _bj_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


class CountdownRing(QWidget):

    MODE_IDLE      = "idle"
    MODE_SCHEDULED = "scheduled"
    MODE_WAITING   = "waiting"   # 已启动，等待到时自动切 running
    MODE_NOW       = "now"
    MODE_RUNNING   = "running"
    MODE_DONE      = "done"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._mode = self.MODE_IDLE
        self._target = None
        self._total_seconds = 1
        self._countdown_text = "--:--:--"
        self._hint_top = "等  待  配  置"
        self._hint_bottom = " "
        self._progress = 0.0
        self._pulse_phase = 0.0
        self._spin_phase = 0.0  # 用于运行中环旋转

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)  # ~30 fps

    # ── 状态切换 API ──
    def set_idle(self):
        self._mode = self.MODE_IDLE
        self._target = None
        self._countdown_text = "--:--:--"
        self._hint_top = "等  待  配  置"
        self._hint_bottom = " "
        self.update()

    def set_scheduled(self, target_dt, total_seconds=None):
        """target_dt 必须是带时区的 datetime（北京时间）。"""
        self._mode = self.MODE_SCHEDULED
        self._target = target_dt
        if total_seconds and total_seconds > 0:
            self._total_seconds = total_seconds
        else:
            diff = (target_dt - _bj_now()).total_seconds()
            self._total_seconds = max(1, int(diff))
        self._hint_top = "距  离  自  动  抢  座"
        self._hint_bottom = (
            f"BEIJING TIME  {target_dt.strftime('%H:%M')}"
        )
        self.update()

    def set_waiting(self, target_dt, total_seconds=None):
        """已启动抢座，等待到时自动切 running。显示倒计时。"""
        self._mode = self.MODE_WAITING
        self._target = target_dt
        if total_seconds and total_seconds > 0:
            self._total_seconds = total_seconds
        else:
            diff = (target_dt - _bj_now()).total_seconds()
            self._total_seconds = max(1, int(diff))
        self._hint_top = "等  待  抢  座  时  刻"
        self._hint_bottom = (
            f"BEIJING TIME  {target_dt.strftime('%H:%M')}"
        )
        self.update()

    def set_now(self):
        self._mode = self.MODE_NOW
        self._target = None
        self._countdown_text = "立  即"
        self._hint_top = "立    即    模    式"
        self._hint_bottom = "点 击 开 始 抢 座 立 即 执 行"
        self.update()

    def set_running(self):
        self._mode = self.MODE_RUNNING
        self._countdown_text = "RUNNING"
        self._hint_top = "正  在  抢  座"
        self._hint_bottom = "·  ·  ·"
        self._progress = 1.0
        self.update()

    def set_done(self, success=True):
        self._mode = self.MODE_DONE
        self._countdown_text = "DONE" if success else "STOP"
        self._hint_top = "本  轮  已  完  成" if success else "已  停  止"
        self._hint_bottom = " "
        self.update()

    # ── 渲染循环 ──
    def _tick(self):
        if self._mode in (self.MODE_SCHEDULED, self.MODE_WAITING) and self._target:
            now = _bj_now()
            secs = max(0, int((self._target - now).total_seconds()))
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self._countdown_text = f"{h:02d}:{m:02d}:{s:02d}"
            elapsed = self._total_seconds - secs
            self._progress = max(0.0, min(1.0, elapsed / self._total_seconds))
            # waiting 模式：倒计时归零后自动切 running
            if self._mode == self.MODE_WAITING and secs <= 0:
                self.set_running()
        elif self._mode == self.MODE_RUNNING:
            self._spin_phase = (self._spin_phase + 0.04) % (2 * math.pi)

        self._pulse_phase = (self._pulse_phase + 0.025) % (2 * math.pi)
        self.update()

    # ── 绘制 ──
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2

        outer_r = side * 0.40
        inner_r = side * 0.32
        ring_thick = outer_r - inner_r
        ring_mid_r = (outer_r + inner_r) / 2
        seal_r = outer_r + 18

        # 1. 印章双圈
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(C.INK), 1.4))
        p.drawEllipse(QPointF(cx, cy), seal_r, seal_r)
        p.setPen(QPen(QColor(C.INK), 0.6))
        p.drawEllipse(QPointF(cx, cy), seal_r + 6, seal_r + 6)

        # 2. 中央光晕
        glow = QRadialGradient(QPointF(cx, cy), inner_r * 0.95)
        base_alpha = {
            self.MODE_IDLE: 16,
            self.MODE_SCHEDULED: 28,
            self.MODE_NOW: 28,
            self.MODE_RUNNING: 60,
            self.MODE_DONE: 22,
        }.get(self._mode, 28)
        glow_alpha = int(base_alpha + 32 * (0.5 + 0.5 * math.sin(self._pulse_phase)))
        ag = QColor(C.AMBER_GLOW)
        ag.setAlpha(glow_alpha)
        glow.setColorAt(0, ag)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), inner_r * 0.95, inner_r * 0.95)

        # 3. 背景圆环
        ring_rect = QRectF(
            cx - ring_mid_r, cy - ring_mid_r,
            ring_mid_r * 2, ring_mid_r * 2,
        )
        bg_pen = QPen(QColor(C.BORDER))
        bg_pen.setWidthF(ring_thick)
        bg_pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(bg_pen)
        p.drawArc(ring_rect, 0, 360 * 16)

        # 4. 进度环：随模式有不同绘制
        prog_pen = QPen(QColor(C.AMBER))
        prog_pen.setWidthF(ring_thick)
        prog_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(prog_pen)

        if self._mode in (self.MODE_SCHEDULED, self.MODE_WAITING):
            p.drawArc(ring_rect, 90 * 16, -int(self._progress * 360 * 16))
        elif self._mode == self.MODE_NOW:
            # 立即模式：四个等距短弧装饰
            for k in range(4):
                p.drawArc(ring_rect, (90 - k * 90) * 16 + 12 * 16, -36 * 16)
        elif self._mode == self.MODE_RUNNING:
            # 跑马灯：80° 弧旋转
            start_deg = 90 - math.degrees(self._spin_phase)
            p.drawArc(ring_rect, int(start_deg * 16), -80 * 16)
        elif self._mode == self.MODE_DONE:
            p.drawArc(ring_rect, 90 * 16, -360 * 16)
        # MODE_IDLE: 不绘制进度

        # 5. 12 点起始锚点
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.INK))
        p.drawEllipse(QPointF(cx, cy - ring_mid_r), 5, 5)

        # 6. 文字
        p.setPen(QColor(C.AMBER_HOT))
        p.setFont(serif(10, ls=4))
        p.drawText(
            QRectF(0, cy - inner_r * 0.62, w, 24),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
            self._hint_top,
        )

        big_color = {
            self.MODE_RUNNING: C.AMBER_HOT,
            self.MODE_DONE: C.OK,
        }.get(self._mode, C.INK)
        if self._mode == self.MODE_DONE and "STOP" in self._countdown_text:
            big_color = C.ERR
        p.setPen(QColor(big_color))
        big_size = 54 if self._mode in (self.MODE_SCHEDULED, self.MODE_IDLE, self.MODE_WAITING) else 38
        p.setFont(mono(big_size, bold=True))
        p.drawText(
            QRectF(0, cy - 52, w, 104),
            Qt.AlignmentFlag.AlignCenter,
            self._countdown_text,
        )

        p.setPen(QColor(C.TEXT_MUTED))
        p.setFont(serif(9, ls=3))
        p.drawText(
            QRectF(0, cy + 40, w, 20),
            Qt.AlignmentFlag.AlignHCenter,
            self._hint_bottom,
        )

        # 7. 四方位琥珀小三角
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(C.AMBER))
        for angle_deg in (0, 90, 180, 270):
            a = math.radians(angle_deg - 90)
            x = cx + (seal_r + 3) * math.cos(a)
            y = cy + (seal_r + 3) * math.sin(a)
            tri = QPainterPath()
            tri.moveTo(x, y - 5)
            tri.lineTo(x + 4, y + 2)
            tri.lineTo(x - 4, y + 2)
            tri.closeSubpath()
            p.drawPath(tri)
