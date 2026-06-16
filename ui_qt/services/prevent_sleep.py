"""Windows 防休眠：抢座等待期间防止系统进入睡眠/挂起。

修复要点（v2）：
1. 加入 ES_DISPLAY_REQUIRED：仅 ES_SYSTEM_REQUIRED 不能阻止 Windows 的
   "Unattended Sleep Timeout"（无人值守睡眠，默认 2 分钟），保持显示器活跃
   后系统不再判定为"无人值守"。
2. 30s 心跳定时器：周期性重申 ExecutionState；当 GetLastInputInfo 显示用户
   空闲 >= 60s 时，再用 SendInput 模拟 1px 鼠标抖动并立即抵消，绕过
   Modern Standby (S0ix) 笔记本上 OS 主动暂停后台进程的策略，且不会打断
   正在使用电脑的用户。
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002

_INPUT_MOUSE = 0
_MOUSEEVENTF_MOVE = 0x0001

_HEARTBEAT_INTERVAL_MS = 30 * 1000
_IDLE_THRESHOLD_SEC = 60.0


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


_heartbeat_timer = None
_caffeinate_proc = None


def _enable_macos() -> bool:
    """macOS：用系统自带 caffeinate 阻止睡眠（显示器/系统/磁盘/用户活跃）。"""
    global _caffeinate_proc
    if _caffeinate_proc is not None and _caffeinate_proc.poll() is None:
        return True
    try:
        _caffeinate_proc = subprocess.Popen(
            ["caffeinate", "-dimsu"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        _caffeinate_proc = None
        return False


def _disable_macos() -> bool:
    """macOS：结束 caffeinate 进程，恢复常规休眠。"""
    global _caffeinate_proc
    if _caffeinate_proc is not None:
        try:
            _caffeinate_proc.terminate()
        except OSError:
            pass
        _caffeinate_proc = None
    return True


def _set_state(flags: int) -> bool:
    if not sys.platform.startswith("win"):
        return False
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
        return True
    except (AttributeError, OSError):
        return False


def _idle_seconds() -> float:
    if not sys.platform.startswith("win"):
        return 0.0
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            tick = ctypes.windll.kernel32.GetTickCount()
            return max(0.0, (tick - info.dwTime) / 1000.0)
    except (AttributeError, OSError):
        pass
    return 0.0


def _send_mouse_jiggle() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        inp = _INPUT()
        inp.type = _INPUT_MOUSE
        inp.u.mi = _MOUSEINPUT(
            dx=1, dy=0, mouseData=0,
            dwFlags=_MOUSEEVENTF_MOVE, time=0, dwExtraInfo=None,
        )
        size = ctypes.sizeof(_INPUT)
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), size)
        inp.u.mi.dx = -1
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), size)
    except (AttributeError, OSError):
        pass


def _heartbeat_tick() -> None:
    _set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED)
    if _idle_seconds() >= _IDLE_THRESHOLD_SEC:
        _send_mouse_jiggle()


def enable() -> bool:
    """开启防休眠。Windows: ExecutionState + 心跳；macOS: caffeinate；其它平台返回 False。"""
    global _heartbeat_timer
    if sys.platform == "darwin":
        return _enable_macos()
    if not sys.platform.startswith("win"):
        return False
    if not _set_state(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED):
        return False
    try:
        from PySide6.QtCore import QTimer
        if _heartbeat_timer is None:
            _heartbeat_timer = QTimer()
            _heartbeat_timer.setInterval(_HEARTBEAT_INTERVAL_MS)
            _heartbeat_timer.timeout.connect(_heartbeat_tick)
        if not _heartbeat_timer.isActive():
            _heartbeat_timer.start()
    except Exception:
        pass
    return True


def disable() -> bool:
    """关闭心跳并恢复系统常规休眠策略。"""
    global _heartbeat_timer
    if sys.platform == "darwin":
        return _disable_macos()
    if not sys.platform.startswith("win"):
        return False
    if _heartbeat_timer is not None:
        try:
            _heartbeat_timer.stop()
        except Exception:
            pass
    return _set_state(_ES_CONTINUOUS)
