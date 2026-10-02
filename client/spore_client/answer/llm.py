"""OpenAI 兼容 SSE 流式客户端——从 MV3 src/lib/llm.js 移植。

语义对齐点（llm.js 文件头注释同款）：
- tool_calls 按 index 装配（并行多路也正确）
- 只对瞬时错误重试（429/5xx/网络/流中断），且只在尚未吐字时重试——避免重放已渲染文本
- 单块 chunk 空闲 60s 判可重试网络错误，不让回合永远挂着
- 端点不认 no_think 参数（HTTP 400）→ 去掉参数重来一次
- abort 回调贯穿循环，命中抛 AbortedError
传输层用 httpx（JS 侧是 fetch）；on_delta(kind, chunk, acc) 签名与 JS 一致。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable

import httpx

RETRY_LIMIT = 3
IDLE_TIMEOUT = 60.0  # 秒；httpx read timeout 即两块数据之间的等待上限

_RETRYABLE_STATUS = re.compile(r"HTTP (429|5\d\d)")
_RETRYABLE_NET = re.compile(
    r"network|failed to fetch|connection (failed|closed|reset|refused)"
    r"|terminated|stream interrupted|stream ended|timed? ?out|socket|idle",
    re.I,
)


class AbortedError(Exception):
    """用户中止回合。"""

    def __init__(self, message: str = "aborted"):
        super().__init__(message)


def is_retryable(message: str) -> bool:
    """llm.js isRetryable 同款：429/5xx/网络类才重试，400/401 等业务错不重试。"""
    return bool(_RETRYABLE_STATUS.search(message) or _RETRYABLE_NET.search(message))


def _parse_sse_lines(buf: str, state: dict) -> tuple[list[tuple[str, str, dict]], str]:
    """SSE 文本增量 → (事件列表, 未凑满一行的余量)。state 持有跨块累积状态。"""
    events: list[tuple[str, str, dict]] = []
    while "\n" in buf:
        line, buf = buf.split("\n", 1)
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue  # 半截 JSON 跳过，下一块拼完整再解
        choices = obj.get("choices") or [{}]
        delta = choices[0].get("delta") or {}
        if not delta and not choices[0].get("message"):
            continue
        r = delta.get("reasoning_content")
        if r is None:
            r = delta.get("reasoning")
        if r:
            state["reasoning"] += r
            events.append(("reasoning", r, _acc(state)))
        if delta.get("content"):
            state["content"] += delta["content"]
            events.append(("text", delta["content"], _acc(state)))
        for tc in delta.get("tool_calls") or []:
            idx = tc.get("index", 0)
            slot = state["slots"].setdefault(
                idx, {"index": idx, "id": "", "name": "", "args": ""})
            if tc.get("id"):
                slot["id"] = tc["id"]
            fn = tc.get("function") or {}
            if fn.get("name"):
                slot["name"] += fn["name"]
            if fn.get("arguments"):
                slot["args"] += fn["arguments"]
            events.append(("tool", "", _acc(state)))
        # 兼容把 tool_calls 放在 message 上的 provider（少见）
        for tc in (choices[0].get("message") or {}).get("tool_calls") or []:
            idx = tc.get("index", len(state["slots"]))
            fn = tc.get("function") or {}
            state["slots"][idx] = {"index": idx,
                                   "id": tc.get("id") or f"call_{idx}",
                                   "name": fn.get("name", ""),
                                   "args": fn.get("arguments", "")}
            events.append(("tool", "", _acc(state)))
    return events, buf


def _acc(state: dict) -> dict:
    """on_delta 的 acc 参数（engine 按 key 取累计值）。"""
    return {"content": state["content"], "reasoning": state["reasoning"]}


def _tool_calls(state: dict) -> list[dict]:
    calls = sorted(state["slots"].values(), key=lambda s: s["index"])
    return [{"id": s["id"] or f"call_{s['index']}",
             "name": s["name"], "args": s["args"]}
            for s in calls if s["name"]]


def _once(endpoint: str, api_key: str, model: str, messages: list,
          tools: list | None, max_tokens: int | None, temperature: float | None,
          no_think: bool, abort: Callable[[], bool] | None,
          on_delta: Callable[[str, str, dict], None] | None) -> dict:
    body: dict = {"model": model, "messages": messages, "stream": True,
                  "stream_options": {"include_usage": False}}
    if no_think:
        # 「直接作答」：deepseek 端点吃这两样，都把 reasoning_content 归零（llm.js 实测注释）
        body["reasoning_effort"] = "none"
        body["thinking"] = {"type": "disabled"}
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    if abort and abort():
        raise AbortedError()

    state = {"content": "", "reasoning": "", "slots": {}}
    headers = {"Content-Type": "application/json",
               "Authorization": f"Bearer {api_key}"}
    try:
        with httpx.Client(timeout=httpx.Timeout(
                IDLE_TIMEOUT, connect=10.0)) as client, \
                client.stream("POST", endpoint, headers=headers,
                              json=body) as resp:
            if resp.status_code != 200:
                detail = b"".join(resp.iter_bytes()).decode(
                    "utf-8", "replace")[:300]
                err = RuntimeError(f"HTTP {resp.status_code} {detail}")
                if resp.status_code == 400:
                    err.no_think_rejected = no_think
                raise err
            buf = ""
            for line in resp.iter_lines():
                if abort and abort():
                    raise AbortedError()
                if not line:
                    continue
                buf += line + "\n"
                events, buf = _parse_sse_lines(buf, state)
                for kind, chunk, acc in events:
                    if on_delta:
                        on_delta(kind, chunk, acc)
    except AbortedError:
        raise
    except httpx.HTTPError as e:
        # 流中断/超时都归为可重试网络类（llm.js 的 stream interrupted 同位语义）
        raise RuntimeError(f"stream interrupted: {e}") from e

    return {"content": state["content"], "reasoning": state["reasoning"],
            "tool_calls": _tool_calls(state)}


def stream_chat(*, endpoint: str, api_key: str, model: str, messages: list,
                tools: list | None = None, max_tokens: int | None = None,
                temperature: float | None = None, no_think: bool = False,
                on_delta: Callable[[str, str, dict], None] | None = None,
                abort: Callable[[], bool] | None = None) -> dict:
    """一次完成（带重试）。on_delta(kind, chunk, acc)：kind ∈ text|reasoning|tool。

    重试铁律（llm.js）：已吐过字就不再重试——否则用户看到重复内容。
    """
    emitted = False

    def counted(kind: str, chunk: str, acc: dict):
        nonlocal emitted
        if kind == "text" and chunk:
            emitted = True
        on_delta(kind, chunk, acc)

    cb = counted if on_delta else None
    attempt = 0
    last_error: Exception | None = None
    use_no_think = no_think
    while attempt < RETRY_LIMIT + 1:
        attempt += 1
        if abort and abort():
            raise AbortedError()
        try:
            return _once(endpoint, api_key, model, messages, tools,
                         max_tokens, temperature, use_no_think, abort, cb)
        except AbortedError:
            raise
        except Exception as e:  # noqa: BLE001 —— 收敛后按 isRetryable 判定
            last_error = e
            if emitted:
                break  # 已吐字不重试
            if getattr(e, "no_think_rejected", False) and use_no_think:
                use_no_think = False  # 端点不认参数 → 去掉重来一次
                continue
            if not is_retryable(str(e)) or attempt >= RETRY_LIMIT:
                break
            time.sleep(0.4 * attempt)  # 400ms 递增退避（llm.js 同款）
    raise RuntimeError(str(last_error)) from last_error
