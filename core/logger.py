import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# 延迟读取 config，避免模块不存在时崩溃
def _get_config_attr(name, default):
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default

_LOG_DIR = None
_LOG_LEVEL = None

def _ensure_defaults():
    global _LOG_DIR, _LOG_LEVEL
    if _LOG_DIR is None:
        _LOG_DIR = _get_config_attr("LOG_DIR", "logs")
    if _LOG_LEVEL is None:
        _LOG_LEVEL = _get_config_attr("LOG_LEVEL", "INFO").upper()


# ── GUI 日志 Handler ──
class GUILogHandler(logging.Handler):
    """将日志推送到 GUI 回调函数的 Handler"""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def emit(self, record):
        try:
            msg = self.format(record) + "\n"
            self.callback(msg)
        except Exception:
            pass

_gui_handler = None

def attach_gui_handler(callback):
    """注册 GUI 回调，只推送 INFO 及以上级别到 GUI"""
    global _gui_handler
    _gui_handler = GUILogHandler(callback)
    _gui_handler.setLevel(logging.INFO)  # 过滤掉 DEBUG 噪音
    _gui_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
    logging.getLogger().addHandler(_gui_handler)
    logging.getLogger().setLevel(logging.INFO)

def detach_gui_handler():
    """移除 GUI Handler"""
    global _gui_handler
    if _gui_handler:
        logging.getLogger().removeHandler(_gui_handler)
        _gui_handler = None


def get_logger(name: str = "lnu") -> logging.Logger:
    _ensure_defaults()

    logger = logging.getLogger(name)
    logger.propagate = True  # 让日志向上传播到 root logger（GUI Handler 在那里）
    if logger.handlers:
        return logger

    level = getattr(logging, _LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    # Console handler
    if sys.stdout is not None:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        ch.setLevel(level)
        logger.addHandler(ch)

    # Rotating file handler
    try:
        if not os.path.exists(_LOG_DIR):
            os.makedirs(_LOG_DIR, exist_ok=True)
        log_file = os.path.join(_LOG_DIR, "lnu_seat.log")
        fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        fh.setLevel(level)
        logger.addHandler(fh)
    except Exception:
        pass  # 文件写入失败不影响运行

    return logger
