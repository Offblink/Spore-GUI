"""Session/Msg 序列化与 LLM 配置的契约测试。

Msg.to_dict 的输出直接进 POST /articles 的 messages[]，后端 Msg.java 按同名字段反序列化——
字段名/取舍错了就是静默丢数据（落库成功但内容缺块），这里钉死。
"""

from spore_client.answer.session import Msg, Session
from spore_client.answer.settings import DEFAULT_MODEL, load_from_env

# ---------- Msg → 后端 Msg.java 字段契约 ----------

def test_user_message_with_image_carries_path():
    m = Msg(role="user", kind="answer", text="补充说明", hasImage=True,
            imagePath="20261002-abc.jpg")
    d = m.to_dict()
    assert d["role"] == "user"
    assert d["kind"] == "answer"
    assert d["hasImage"] is True          # 后端 Boolean hasImage
    assert d["imagePath"] == "20261002-abc.jpg"
    assert d["text"] == "补充说明"
    assert "ts" in d and d["ts"] > 0


def test_empty_fields_omitted_but_core_keys_present():
    # 空串/False 不落（与手机端序列化口径一致，省体积）；role 是必有键
    d = Msg(role="assistant", kind="answer", ans="B（错）").to_dict()
    assert d["role"] == "assistant"
    assert d["ans"] == "B（错）"
    assert "why" not in d        # 空串省略
    assert "verifyNote" not in d  # 空串省略


def test_false_booleans_omitted_true_kept():
    m = Msg(role="assistant", kind="answer", ans="A",
            verifyRan=True, verifySkipped=False, hasImage=False)
    d = m.to_dict()
    assert d["verifyRan"] is True
    assert "verifySkipped" not in d   # False 不落——后端 null 语义一致
    assert "hasImage" not in d


def test_answer_fields_roundtrip():
    # 阶段A 解析出的四字段 + 核实结果都要能落库（结题演示：列表页读得到）
    m = Msg(role="assistant", kind="answer", no="17", title="SQA活动范围",
            ans="B（错）", why="故说法错误。",
            verifyVerdict="FIX", verifyNote="教材：原说法错误（来源：教材）",
            verifyRan=True, tools=["检索 SQA 定义"])
    d = m.to_dict()
    assert d["no"] == "17" and d["title"] == "SQA活动范围"
    assert d["verifyVerdict"] == "FIX"
    assert d["tools"] == ["检索 SQA 定义"]  # 检索小票原样透传（后端 JsonNode）


def test_session_id_unique_and_status_lifecycle():
    a, b = Session(), Session()
    assert a.id != b.id
    a.status = "answering"
    a.touch()
    assert a.updated >= a.created
    assert a.title == "新会话"   # 占位语义与两端一致（design/03 §1）


# ---------- LLM 配置：key 只走环境变量（评分红线：源码零硬编码） ----------

def test_env_key_missing_reported_not_raised(monkeypatch):
    monkeypatch.delenv("SPORE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    s = load_from_env()
    assert not s.ready
    assert s.errors and "环境变量" in s.errors[0]   # 记错不抛，UI 提示


def test_env_key_pickup_and_defaults(monkeypatch):
    monkeypatch.setenv("SPORE_API_KEY", "sk-test")
    monkeypatch.delenv("SPORE_ENDPOINT", raising=False)
    monkeypatch.delenv("SPORE_MODEL", raising=False)
    s = load_from_env()
    assert s.ready
    assert s.api_key == "sk-test"
    assert s.model == DEFAULT_MODEL          # 与 MV3/手机端同默认
    assert s.max_tool_rounds == 5            # MV3 maxToolRounds 默认


def test_env_rounds_clamped(monkeypatch):
    monkeypatch.setenv("SPORE_API_KEY", "sk-test")
    monkeypatch.setenv("SPORE_MAX_TOOL_ROUNDS", "99")
    assert load_from_env().max_tool_rounds == 10   # 上限 10（MV3 设置页同款钳制）
    monkeypatch.setenv("SPORE_MAX_TOOL_ROUNDS", "junk")
    assert load_from_env().max_tool_rounds == 5    # 设错用默认
