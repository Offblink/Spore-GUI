r"""轻量文件日志：%LOCALAPPDATA%\Spore\logs\client.log（2MB ×3 轮转）。

红线：不记 key、不记回答正文/图片内容——只记事件类型、时序、异常。
落点与 captures 同根（SPORE_HOME 可整体重定向）。
"""

from __future__ import annotations

import logging
import os
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(
    os.environ.get("SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore")
) / "logs"

_lock = threading.Lock()


def get_logger(name: str = "spore") -> logging.Logger:
    log = logging.getLogger(name)
    with _lock:
        if not log.handlers:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            h = RotatingFileHandler(LOG_DIR / "client.log", maxBytes=2_000_000,
                                    backupCount=2, encoding="utf-8")
            h.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)s [%(threadName)s] "
                "%(message)s", "%Y-%m-%d %H:%M:%S"))
            log.addHandler(h)
            log.setLevel(logging.INFO)
    return log
