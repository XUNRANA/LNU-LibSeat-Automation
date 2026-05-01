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
    _gui_handler.setFormatter(GUIPreciseFormatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(_gui_handler)
    logging.getLogger().setLevel(logging.INFO)

def detach_gui_handler():
    """移除 GUI Handler"""
    global _gui_handler
    if _gui_handler:
        logging.getLogger().removeHandler(_gui_handler)
        _gui_handler = None


# ── 按账号拆分日志文件 ──
class _AccountTagFilter(logging.Filter):
    """只放行消息中包含 [account] 标签的日志记录。"""
    def __init__(self, account: str):
        super().__init__()
        self._tag = f"[{account}]"

    def filter(self, record):
        try:
            return self._tag in record.getMessage()
        except Exception:
            return False


_account_handlers = {}  # account -> handler


def register_account_log_file(account: str):
    """
    为指定账号注册一个独立的日志文件 logs/lnu_seat_<account>.log。
    任何包含 [account] 标签的日志都会同时写入该文件，
    实现「主账号全部写入 / 副账号全部写入」的拆分。
    """
    _ensure_defaults()
    if not account or account in _account_handlers:
        return
    try:
        if not os.path.exists(_LOG_DIR):
            os.makedirs(_LOG_DIR, exist_ok=True)
        log_file = os.path.join(_LOG_DIR, f"lnu_seat_{account}.log")
        fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
        fh.setFormatter(PreciseFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        fh.setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))
        fh.addFilter(_AccountTagFilter(account))
        logging.getLogger().addHandler(fh)
        _account_handlers[account] = fh
    except Exception:
        pass


def detach_all_account_log_files():
    """退出时移除所有账号日志 handler，避免重复 attach。"""
    global _account_handlers
    root = logging.getLogger()
    for h in list(_account_handlers.values()):
        try:
            root.removeHandler(h)
            h.close()
        except Exception:
            pass
    _account_handlers = {}


class PreciseFormatter(logging.Formatter):
    """日志时间精确到毫秒，格式: 2026-04-28 06:29:59.970"""
    def formatTime(self, record, datefmt=None):
        from datetime import datetime, timezone, timedelta
        ct = datetime.fromtimestamp(record.created, tz=timezone(timedelta(hours=8)))
        return ct.strftime("%Y-%m-%d %H:%M:%S.") + f"{int(record.msecs):03d}"


class GUIPreciseFormatter(logging.Formatter):
    """GUI 日志时间精确到毫秒，格式: 06:29:59.970"""
    def formatTime(self, record, datefmt=None):
        from datetime import datetime, timezone, timedelta
        ct = datetime.fromtimestamp(record.created, tz=timezone(timedelta(hours=8)))
        return ct.strftime("%H:%M:%S.") + f"{int(record.msecs):03d}"


def get_logger(name: str = "lnu") -> logging.Logger:
    _ensure_defaults()

    logger = logging.getLogger(name)
    logger.propagate = True  # 让日志向上传播到 root logger（GUI Handler 在那里）
    if logger.handlers:
        return logger

    level = getattr(logging, _LOG_LEVEL, logging.INFO)
    logger.setLevel(level)

    fmt = PreciseFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

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
