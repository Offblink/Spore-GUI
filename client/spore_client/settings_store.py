"""非敏感 UI 设置持久化：%LOCALAPPDATA%\\Spore\\ui_settings.json。

对齐 MV3 options.js 的 FIELDS/CHECKS（磁盘镜像是浏览器 storage 专属件，
桌面端不做，见 2026-10-02 用户拍板）：
endpoint / model / maxToolRounds / historyLimit / proxy / fastNoThink /
autoVerify / **apiKey**。

api_key（2026-10-03 用户拍板改版）：**只依赖 config**——key 随白名单落进本
本地文件（不进 git/日志/文档），环境变量通道废除；apply_to_llm() 负责读回并
在缺失时记 errors（UI 提示）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .answer.settings import LlmSettings
from .log import LOG_DIR, get_logger

LOG = get_logger()

# 与 log.py 同根：%LOCALAPPDATA%\Spore\ui_settings.json（SPORE_HOME 可整体重定向）
PATH: Path = LOG_DIR.parent / "ui_settings.json"

# 落盘白名单（= MV3 FIELDS/CHECKS + apiKey）。不在表内的键一律丢弃。
_FIELDS = (
    "endpoint", "model", "maxToolRounds", "historyLimit", "proxy",
    "fastNoThink", "autoVerify", "apiKey",
    "panelFixed", "panelPos",   # 回答面板位置固定开关 + 记住的坐标（2026-10-05）
)


def read() -> dict:
    """读原始 dict；文件缺失/损坏一律回落 {}（不抛，主线用 .get 带默认）。"""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def write(d: dict) -> None:
    """白名单过滤后原子写（tmp + os.replace）；失败只记日志不抛。"""
    clean = {k: d[k] for k in _FIELDS if k in d}
    try:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_name(PATH.name + ".tmp")
        tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, PATH)
    except Exception as e:  # noqa: BLE001 —— 设置写失败不该掀桌，记日志即可
        LOG.warning("ui settings write failed: %s", e)


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def apply_to_llm(llm: LlmSettings) -> LlmSettings:
    """把文件里的值填进 llm；环境变量对 endpoint/model/轮数/代理仍可覆盖。

    api_key **只依赖 config**（2026-10-03 拍板：环境变量废除）——文件缺失即
    空 key 并记 errors（UI 提示，不抛）。
    """
    d = read()
    llm.api_key = str(d.get("apiKey") or "")
    if not llm.api_key:
        llm.errors.append(
            "API key 未设置——到设置页粘贴后回车保存即生效")
    if not d:
        return llm
    env = os.environ
    if isinstance(d.get("endpoint"), str) and d["endpoint"] \
            and not env.get("SPORE_ENDPOINT"):
        llm.endpoint = d["endpoint"]
    if isinstance(d.get("model"), str) and d["model"] \
            and not env.get("SPORE_MODEL"):
        llm.model = d["model"]
    if not env.get("SPORE_MAX_TOOL_ROUNDS"):
        n = _int(d.get("maxToolRounds"))
        if n is not None:
            llm.max_tool_rounds = max(0, min(10, n))       # MV3 options.js:43
    if "historyLimit" in d:
        n = _int(d.get("historyLimit"))
        if n in (None, 0):
            n = 10                                          # MV3 Number(x)||10
        llm.history_limit = max(2, min(50, n))              # MV3 options.js:45
    if isinstance(d.get("proxy"), str) and not env.get("SPORE_SEARCH_PROXY"):
        llm.proxy = d["proxy"]
    if isinstance(d.get("fastNoThink"), bool):
        llm.fast_no_think = d["fastNoThink"]
    if isinstance(d.get("autoVerify"), bool):
        llm.auto_verify = d["autoVerify"]
    return llm
