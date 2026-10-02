"""AgentEngine 编排行为测试——假 LLM 走完整两阶段，不碰网络。

钉住的编排语义（agent.js 移植的关键分叉）：
- <<ok>> 自检跳核实；但答案与解析打架时绝不跳（用户截图那道判断题的守卫）
- FIX 覆盖答案行；turn-end 收尾事件必发；工具循环调 dispatch
"""

from spore_client.answer.engine import AgentEngine
from spore_client.answer.settings import LlmSettings


class FakeLlm:
    """按调用次序回放脚本化响应；记录每次调用参数供断言。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, **kw):
        self.calls.append(kw)
        res = self.script.pop(0)
        on_delta = kw.get("on_delta")
        content = res.get("content", "")
        if on_delta and content:
            # 模拟流式：整段一次给
            on_delta("text", content, {"content": content, "reasoning": ""})
        return res


def _run(engine, monkeypatch, script):
    fake = FakeLlm(script)
    monkeypatch.setattr("spore_client.answer.engine.stream_chat", fake)
    captured: list = []
    orig_emit = engine._emit

    def emit(ev):
        captured.append(ev)  # 全量捕获，供断言
        orig_emit(ev)

    engine._emit = emit
    engine.new_capture_turn("fake.jpg")
    engine._worker.join(timeout=10)
    assert not engine._worker.is_alive(), "回合线程 10s 未收尾（死循环？）"
    return fake, captured


def _settings(**kw):
    s = LlmSettings(api_key="sk-test")
    for k, v in kw.items():
        setattr(s, k, v)
    return s


PHASE_A_OK = (
    "NO: 17\nTITLE: SQA范围\n"
    "WHY: 制定质量计划属SQA计划活动，故说法错误。\n"
    "ANS: B（错）\nCERT: <<check>>"
)
PHASE_A_CERTAIN = PHASE_A_OK.replace("<<check>>", "<<ok>>")
PHASE_A_FIGHTING = (
    "NO: 17\nTITLE: 矛盾题\n"
    "WHY: 制定软件质量计划属于SQA活动中的计划与实施范畴，故该说法错误。\n"
    "ANS: A（对）\nCERT: <<ok>>"  # 答案说对、解析说错——用户截图原型
)
PHASE_B_FIX = "VERDICT: FIX\nANS: B（错）\nNOTE: 教材：SQA含计划活动（来源：教材）。"


def test_two_phase_turn_completes_with_fix(monkeypatch):
    eng = AgentEngine(_settings(), lambda ev: None)
    fake, events = _run(eng, monkeypatch, [
        {"content": PHASE_A_OK},   # 阶段A
        {"content": PHASE_B_FIX},  # 阶段B（无 tool_calls → 直接解析）
    ])
    types = [e["type"] for e in events]
    assert "answer-start" in types and "answer-delta" in types
    assert "turn-end" in types
    assert events[-1]["type"] == "turn-end"
    assert not events[-1].get("error")
    ans = eng.session.last_answer
    assert ans.ans == "B（错）"          # FIX 覆盖答案行
    assert ans.verifyRan is True
    assert ans.verifyVerdict == "FIX"
    # 阶段B 带了工具定义（联网核实的入场券）
    assert fake.calls[1].get("tools")


def test_self_certain_skips_verify(monkeypatch):
    eng = AgentEngine(_settings(), lambda ev: None)
    fake, events = _run(eng, monkeypatch, [{"content": PHASE_A_CERTAIN}])
    assert len(fake.calls) == 1  # 只有一次调用：核实被 <<ok>> 跳过
    ans = eng.session.last_answer
    assert ans.verifySkipped is True
    assert ans.verifyVerdict == "OK"
    assert events[-1]["type"] == "turn-end"


def test_fighting_answer_forces_verify_despite_ok_guard(monkeypatch):
    # 用户截图那道题：ANS 说对、WHY 说错、CERT 还写 <<ok>> → 必须复核
    eng = AgentEngine(_settings(), lambda ev: None)
    fake, _ = _run(eng, monkeypatch, [
        {"content": PHASE_A_FIGHTING},
        {"content": PHASE_B_FIX},
    ])
    assert len(fake.calls) == 2  # 核实没被跳过
    ans = eng.session.last_answer
    assert ans.ans == "B（错）"   # FIX 纠正了矛盾答案
    assert ans.verifyRan is True


def test_auto_verify_off_defers_to_button(monkeypatch):
    eng = AgentEngine(_settings(auto_verify=False), lambda ev: None)
    fake, events = _run(eng, monkeypatch, [{"content": PHASE_A_OK}])
    assert len(fake.calls) == 1
    ans = eng.session.last_answer
    assert ans.verifyPending is True     # 挂起 → 等「核实一下」
    assert ans.verifyRan is False
    assert events[-1]["type"] == "turn-end"


def test_tool_loop_dispatches_and_returns(monkeypatch):
    # 阶段B 首轮要工具 → dispatch → 第二轮给结论
    eng = AgentEngine(_settings(), lambda ev: None)
    script = [
        {"content": PHASE_A_OK},  # 阶段A 先消费一条
        {"content": "", "tool_calls": [  # 阶段B 首轮要工具
            {"id": "c0", "name": "web_search", "args": '{"query":"SQA 定义"}'}]},
        {"content": PHASE_B_FIX},  # dispatch 后第二轮给结论
    ]
    dispatched = []
    monkeypatch.setattr(
        "spore_client.answer.engine.dispatch",
        lambda name, args, abort: dispatched.append((name, args)) or "1. 结果")
    fake, events = _run(eng, monkeypatch, script)
    assert dispatched and dispatched[0][0] == "web_search"
    assert any(e["type"] == "tool" for e in events)   # 小票事件发出
    assert eng.session.last_answer.verifyRan is True
    # 第二轮的 messages 必须带上工具结果（role=tool），否则模型看不到检索内容
    second_msgs = fake.calls[1]["messages"]
    tool_msgs = [m for m in second_msgs if m.get("role") == "tool"]
    assert tool_msgs and "1. 结果" in tool_msgs[0]["content"]


def test_status_lifecycle_emitted(monkeypatch):
    eng = AgentEngine(_settings(), lambda ev: None)
    _, events = _run(eng, monkeypatch, [
        {"content": PHASE_A_OK}, {"content": PHASE_B_FIX}])
    statuses = [e.get("status") for e in events if e["type"] == "status"]
    assert "answering" in statuses      # 读题中
    assert "verifying" in statuses      # 核实中
