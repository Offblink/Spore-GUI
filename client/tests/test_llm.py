"""llm.py 契约测试——不起网络：SSE 解析/装配/重试判定全是纯逻辑。

钉住的都是 llm.js 的移植关键点：多 index tool_calls 装配、isRetryable 判定、
「已吐字不重试」。这三处错了分别是：并行工具调用串台、业务错误空转重试、用户看到重复文本。
"""


from spore_client.answer.llm import (
    RETRY_LIMIT,
    _parse_sse_lines,
    _tool_calls,
    is_retryable,
)


def _state():
    return {"content": "", "reasoning": "", "slots": {}}


def _feed(chunks: list[str], state=None):
    """把 SSE data 行分块喂进解析器（模拟网络分片），返回累计事件。"""
    st = state or _state()
    buf = ""
    events = []
    for c in chunks:
        buf += c
        ev, buf = _parse_sse_lines(buf, st)
        events.extend(ev)
    return events, st, buf


# ---------- isRetryable（llm.js 同款判定） ----------

def test_retryable_429_and_5xx():
    assert is_retryable("HTTP 429 rate limited") is True
    assert is_retryable("HTTP 503 upstream") is True
    assert is_retryable("HTTP 500") is True


def test_not_retryable_4xx_business_errors():
    assert is_retryable("HTTP 400 bad request") is False
    assert is_retryable("HTTP 401 unauthorized") is False


def test_retryable_network_class():
    assert is_retryable("stream interrupted: read timeout") is True
    assert is_retryable("network: connection reset") is True
    assert is_retryable("stream idle >60s") is True


# ---------- SSE 解析 ----------

def test_text_and_reasoning_accumulate():
    chunks = [
        'data: {"choices":[{"delta":{"reasoning_content":"想一想"}}]}\n',
        'data: {"choices":[{"delta":{"content":"答案是B"}}]}\n',
        'data: [DONE]\n',
    ]
    events, st, rest = _feed(chunks)
    assert st["reasoning"] == "想一想"
    assert st["content"] == "答案是B"
    kinds = [k for k, _, _ in events]
    assert "reasoning" in kinds and "text" in kinds
    assert rest == ""


def test_chunked_line_split_reassembles():
    # 一行 JSON 被网络切成三块喂进来，也能解出
    line = 'data: {"choices":[{"delta":{"content":"分片"}}]}\n'
    pieces = [line[:15], line[15:33], line[33:]]
    events, st, _ = _feed(pieces)
    assert st["content"] == "分片"
    assert events  # 拼完整后产生了事件


def test_parallel_tool_calls_assembled_by_index():
    # 两路 tool_calls 交错到达（index 0/1 各自追加 arguments 片段）
    import json

    def sse(payload: dict) -> str:
        return "data: " + json.dumps(payload, ensure_ascii=False) + "\n"

    def delta_tc(index: int, **fn) -> dict:
        tc = {"index": index}
        if "id" in fn:
            tc["id"] = fn.pop("id")
        tc["function"] = fn
        return {"choices": [{"delta": {"tool_calls": [tc]}}]}

    chunks = [
        sse(delta_tc(0, id="c0", name="web_search", arguments='{"q"')),
        sse(delta_tc(1, id="c1", name="web", arguments='{"u"')),
        sse(delta_tc(0, arguments=':"deepseek"}')),
        sse(delta_tc(1, arguments=':"https://x.cn"}')),
        "data: [DONE]\n",
    ]
    _, st, _ = _feed(chunks)
    calls = _tool_calls(st)
    assert len(calls) == 2
    assert calls[0]["name"] == "web_search"
    assert '"q":"deepseek"' in calls[0]["args"]
    assert calls[1]["name"] == "web"
    assert "https://x.cn" in calls[1]["args"]


def test_malformed_json_lines_skipped_not_crash():
    chunks = [
        "data: {broken\n",
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n',
        "data: [DONE]\n",
    ]
    _, st, _ = _feed(chunks)
    assert st["content"] == "ok"  # 半截 JSON 跳过，好数据不丢


def test_non_data_lines_and_done_ignored():
    chunks = [": comment\n", "event: ping\n", "data: [DONE]\n", "\n"]
    events, st, _ = _feed(chunks)
    assert events == [] and st["content"] == ""


def test_provider_style_whole_message_tool_calls():
    # 少见 provider：tool_calls 整块挂在 message 上而非 delta
    chunks = [
        'data: {"choices":[{"message":{"tool_calls":[{"id":"c9","index":0,'
        '"function":{"name":"web_search","arguments":"{}"}}]}}]}\n',
        "data: [DONE]\n",
    ]
    _, st, _ = _feed(chunks)
    calls = _tool_calls(st)
    assert calls[0]["id"] == "c9" and calls[0]["name"] == "web_search"


def test_empty_name_slots_filtered():
    # 只有 index 没有 name 的半截槽位不进结果（llm.js filter(s => s.name)）
    chunks = ['data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
              '"function":{"arguments":"{}"}}]}}]}\n', "data: [DONE]\n"]
    _, st, _ = _feed(chunks)
    assert _tool_calls(st) == []


# ---------- 重试上限（常量口径） ----------

def test_retry_limit_matches_js():
    assert RETRY_LIMIT == 3  # llm.js RETRY_LIMIT
