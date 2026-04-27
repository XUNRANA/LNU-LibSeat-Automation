"""
浏览器窗口录屏(走 Selenium 内置 screenshot,无关桌面是否可见)。

每次 run_browser_session() 启动浏览器后立刻开始录,关闭浏览器前停止并写盘。
- 通过 driver.get_screenshot_as_png() 拿到浏览器内部渲染的画面(headless 也能拿)
- 用 OpenCV 写 MP4
输出: logs/recordings/session_<account>_<YYYYMMDD_HHMMSS>.mp4
"""
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np

from core.logger import get_logger

logger = get_logger(__name__)


class BrowserScreencastRecorder:
    """通过 driver.get_screenshot_as_png() 录浏览器窗口,支持 headless。"""

    def __init__(self, driver, account: str, log_dir: str = "logs", fps: int = 5):
        self.driver = driver
        self.account = account
        self.log_dir = log_dir
        self.fps = max(1, int(fps))

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._writer: cv2.VideoWriter | None = None
        self._filepath: str | None = None
        self._target_size: tuple[int, int] | None = None  # (w, h)
        self._started = False

    # ------------------------------------------------------------------
    def _grab_frame(self):
        """从浏览器拿一帧 PNG → 解码成 BGR ndarray。失败返回 None。"""
        try:
            png_bytes = self.driver.get_screenshot_as_png()
        except Exception as e:
            logger.debug("录屏抓帧失败: %s", e)
            return None
        try:
            arr = np.frombuffer(png_bytes, dtype=np.uint8)
            return cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception as e:
            logger.debug("录屏解码失败: %s", e)
            return None

    # ------------------------------------------------------------------
    def start(self):
        if self._started:
            return

        first_frame = self._grab_frame()
        if first_frame is None:
            logger.warning("⚠️ [%s] 录屏: 首帧抓取失败,放弃录屏。", self.account)
            return
        h, w = first_frame.shape[:2]
        # 视频编码要求宽高为偶数
        w &= ~1
        h &= ~1
        if w < 2 or h < 2:
            logger.warning("⚠️ [%s] 录屏: 浏览器分辨率过小 (%dx%d),放弃。", self.account, w, h)
            return

        sub_dir = os.path.join(self.log_dir, "recordings")
        os.makedirs(sub_dir, exist_ok=True)
        now = datetime.now(timezone(timedelta(hours=8)))
        filename = f"session_{self.account}_{now.strftime('%Y%m%d_%H%M%S')}.mp4"
        self._filepath = os.path.join(sub_dir, filename)

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        self._writer = cv2.VideoWriter(self._filepath, fourcc, self.fps, (w, h))
        if not self._writer.isOpened():
            logger.warning("⚠️ [%s] 录屏: VideoWriter 打开失败,放弃录屏。", self.account)
            self._writer = None
            return

        self._target_size = (w, h)
        self._started = True
        # 写入第一帧
        try:
            if first_frame.shape[1] != w or first_frame.shape[0] != h:
                first_frame = cv2.resize(first_frame, (w, h))
            self._writer.write(first_frame)
        except Exception:
            pass

        self._thread = threading.Thread(
            target=self._loop, daemon=True, name=f"recorder-{self.account}"
        )
        self._thread.start()
        logger.info(
            "🎥 [%s] 录屏开始: %s (%dx%d @ %dfps,浏览器内截图,支持 headless)",
            self.account, self._filepath, w, h, self.fps,
        )

    # ------------------------------------------------------------------
    def _loop(self):
        period = 1.0 / self.fps
        next_tick = time.monotonic() + period
        target_w, target_h = self._target_size

        while not self._stop_event.is_set():
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                if self._stop_event.wait(sleep_for):
                    break

            frame = self._grab_frame()
            if frame is not None and self._writer is not None:
                try:
                    if frame.shape[1] != target_w or frame.shape[0] != target_h:
                        frame = cv2.resize(frame, (target_w, target_h))
                    self._writer.write(frame)
                except Exception as e:
                    logger.debug("录屏写帧失败: %s", e)

            next_tick += period
            # 落后太多则重置节拍,避免越追越累
            if next_tick < time.monotonic() - period:
                next_tick = time.monotonic() + period

    # ------------------------------------------------------------------
    def stop(self):
        if not self._started:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        if self._writer is not None:
            try:
                self._writer.release()
            except Exception:
                pass
            self._writer = None
        if self._filepath:
            logger.info("🎬 [%s] 录屏已保存: %s", self.account, self._filepath)
        self._started = False


# 兼容旧名,导入处不必跟着改
EdgeWindowRecorder = BrowserScreencastRecorder
