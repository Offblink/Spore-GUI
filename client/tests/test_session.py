"""Session/Msg 序列化与 LLM 配置的契约测试。

Msg.to_dict 的输出直接进 POST /articles 的 messages[]，后端 Msg.java 按同名字段反序列化——
字段名/取舍错了就是静默丢数据（落库成功但内容缺块），这里钉死。
"""

from spore_client.answer.session import (
    Msg,
    Session,
    msgs_of,
    session_from_article,
)
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


# ---------- ArticleVO → 可接续 Session（§8-2；2026-10-03 自 answer_window 迁入） ----------

def test_session_from_article_carries_backend_id_and_msgs():
    art = {"id": "20261002-abc", "title": "SQA 范围", "fav": 1,
           "status": "done",
           "messages": [{"role": "user", "kind": "chat", "text": "在吗",
                         "ts": 5},
                        {"role": "assistant", "kind": "answer", "ans": "A（对）",
                         "tools": ["检索 SQA 定义"]},
                        "畸形行"]}
    sess = session_from_article(art, msgs_of(art))
    assert sess.backend_id == "20261002-abc"   # turn-end 据此走 PUT 而非 POST
    assert sess.title == "SQA 范围" and sess.fav is True
    assert [m.role for m in sess.messages] == ["user", "assistant"]
    assert sess.messages[0].ts == 5            # ts 是排序依据，别丢
    assert sess.messages[1].tools == ["检索 SQA 定义"]


# ---------- LLM 配置：key 只依赖 config（2026-10-03 拍板，源码零硬编码） ----------

def test_api_key_not_read_from_env_anymore(monkeypatch):
    # key 的环境变量通道已废除——只认 settings_store 的 apiKey
    monkeypatch.setenv("SPORE_API_KEY", "sk-env")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env2")
    s = load_from_env()
    assert s.api_key == ""
    assert not s.ready                        # 无 key 不就绪（key 由 config 另行读入）


def test_env_model_and_rounds_defaults(monkeypatch):
    monkeypatch.delenv("SPORE_ENDPOINT", raising=False)
    monkeypatch.delenv("SPORE_MODEL", raising=False)
    s = load_from_env()
    assert s.model == DEFAULT_MODEL          # 与 MV3/手机端同默认
    assert s.max_tool_rounds == 5            # MV3 maxToolRounds 默认


def test_env_rounds_clamped(monkeypatch):
    monkeypatch.setenv("SPORE_API_KEY", "sk-test")
    monkeypatch.setenv("SPORE_MAX_TOOL_ROUNDS", "99")
    assert load_from_env().max_tool_rounds == 10   # 上限 10（MV3 设置页同款钳制）
    monkeypatch.setenv("SPORE_MAX_TOOL_ROUNDS", "junk")
    assert load_from_env().max_tool_rounds == 5    # 设错用默认
