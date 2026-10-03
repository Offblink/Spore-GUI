"""LLM 接入配置——key 只从 config（settings_store）读，源码零硬编码；
环境变量只覆盖 endpoint/model/轮数/代理（key 的环境变量通道 2026-10-03 废除）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 与 MV3 DEFAULT_SETTINGS / 手机端 SporeSettings 同默认值
DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"
DEFAULT_MAX_TOOL_ROUNDS = 5
DEFAULT_HISTORY_LIMIT = 10


@dataclass
class LlmSettings:
    endpoint: str = DEFAULT_ENDPOINT
    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    history_limit: int = DEFAULT_HISTORY_LIMIT
    fast_no_think: bool = True   # 初答直接作答不写推理（MV3 fastNoThink）
    auto_verify: bool = True     # 答完自动联网核实（MV3 autoVerify）
    proxy: str = ""              # 检索代理：填了 ddg 打头，留空只走 bing
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.api_key) and bool(self.endpoint)


def load_from_env() -> LlmSettings:
    """环境变量只管 endpoint/model/轮数/代理：SPORE_* 覆盖通用名。
    key 不在这条链上——apply_to_llm() 从 config 读（缺失记 errors，不抛）。"""
    s = LlmSettings()
    s.endpoint = os.environ.get("SPORE_ENDPOINT") or DEFAULT_ENDPOINT
    s.model = os.environ.get("SPORE_MODEL") or DEFAULT_MODEL
    try:
        rounds = int(os.environ.get("SPORE_MAX_TOOL_ROUNDS", ""))
        s.max_tool_rounds = max(0, min(10, rounds))
    except ValueError:
        pass  # 没设或设错都用默认 5
    s.proxy = os.environ.get("SPORE_SEARCH_PROXY", "")
    return s
