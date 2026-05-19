"""抢座 worker：用 ``threading.Thread`` 跑 ``main.main``，通过 Qt Signal 把日志路由回主线程。

关键点：
- ``log_line`` 是跨线程信号，PySide6 会自动用 ``Qt.QueuedConnection`` 排队到主线程派发，
  这样 GUI 不需要任何 ``QMutex`` 也不会卡顿。
- worker 用普通 ``threading.Thread`` 而不是 ``QThread``，是为了让现有 ``main.py``
  内部的多线程模型（每个账号一个线程）保持原样运行。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


class BookerWorker(QObject):

    log_line = Signal(str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._stop_event: threading.Event | None = None

    # ── API ──
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start_booking(self):
        if self.is_running():
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        if self._stop_event:
            self._stop_event.set()

    # ── 内部 ──
    def _run(self):
        from core.logger import attach_gui_handler, detach_gui_handler

        # 关键：用闭包把日志行转发到 Qt Signal
        attach_gui_handler(self._on_log)
        try:
            # 延迟导入：保证 ``inject_into_sys_modules`` 已经先注入 config
            from main import main as run_main

            run_main(stop_event=self._stop_event)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"{type(exc).__name__}: {exc}")
            self._on_log(f"\n❌ 异常退出: {exc}\n")
        finally:
            try:
                detach_gui_handler()
            except Exception:
                pass
            self.finished.emit()

    def _on_log(self, msg: str):
        self.log_line.emit(msg)
