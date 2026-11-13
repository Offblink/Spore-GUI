"""服务器连接凭据：``%LOCALAPPDATA%\\Spore\\sync_state.json``（SPORE_HOME 可重定向）。

红线：``token`` 只在内存与本文件——不进日志、不进 ``ui_settings.json``（那份是
LLM 配置白名单，且会被设置页整体回读）。游标不进这里：它们在 ``spore.db`` 的
``sync_meta`` 表里，db 备份/还原自带水位。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .log import LOG_DIR, get_logger

LOG = get_logger()

PATH: Path = LOG_DIR.parent / "sync_state.json"

_FIELDS = ("api", "token", "username", "nick", "uid")


def load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: data[k] for k in _FIELDS if k in data}


def save(d: dict) -> None:
    """白名单过滤后原子写（tmp + os.replace）；失败只记日志、不抛。"""
    clean = {k: d[k] for k in _FIELDS if k in d}
    tmp = PATH.with_suffix(".json.tmp")
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, PATH)
    except OSError as e:
        LOG.warning("sync state write failed: %s", e)


def clear() -> None:
    """断开连接：凭据清空（游标由 Store.reset_sync_cursors 清）。"""
    save({})
