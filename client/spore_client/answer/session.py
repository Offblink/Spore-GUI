"""会话/消息模型——字段与 design/03 映射表、手机端 Session.Msg 同构。

落库时 Msg 直接序列化进 article.content.messages（后端 Msg.java 同名字段），
 imagePath/hasImage 指到题图，题图本体走 /sync/push-attachment 上推。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Msg:
    role: str                       # user / assistant
    kind: str = "chat"              # answer / chat
    text: str = ""
    think: str = ""
    no: str = ""
    title: str = ""
    ans: str = ""
    why: str = ""
    verifyVerdict: str = ""
    verifyNote: str = ""
    verifyThink: str = ""
    hasImage: bool = False
    imagePath: str = ""             # 题图相对路径（题库目录内）
    verifyRan: bool = False
    verifySkipped: bool = False
    verifyPending: bool = False
    thinkOpen: bool = False
    tools: list | None = None       # 检索小票 ["检索 xxx", ...]
    ts: int = field(default_factory=_now_ms)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in (None, "", False)}
        # 空 tools 不落、False 布尔不落（与手机端序列化口径一致，省体积）
        if self.tools:
            d["tools"] = self.tools
        for b in ("hasImage", "verifyRan", "verifySkipped", "verifyPending"):
            if getattr(self, b):
                d[b] = True
        return d


def _new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


@dataclass
class Session:
    id: str = field(default_factory=_new_id)
    created: int = field(default_factory=_now_ms)
    updated: int = field(default_factory=_now_ms)
    fav: bool = False
    subjectId: str | None = None
    title: str = "新会话"
    status: str = ""                # answering/verifying/searching/done/error/aborted
    messages: list[Msg] = field(default_factory=list)
    image_path: str = ""            # 本回合题图（GUI 本地路径，turn-end 时上推）
    backend_id: str = ""            # 后端 article id：历史接续时带上，turn-end 据此
                                    # PUT 更新而不是 POST 开新会话（§8-2）

    @property
    def last_user(self) -> Msg | None:
        for m in reversed(self.messages):
            if m.role == "user":
                return m
        return None

    @property
    def last_answer(self) -> Msg | None:
        for m in reversed(self.messages):
            if m.role == "assistant" and m.kind == "answer":
                return m
        return None

    def touch(self):
        self.updated = _now_ms()


def msgs_of(article: dict) -> list:
    """ArticleVO.messages（后端 toVo 顶层直带）；兼容详情 content.messages/JSON 串。"""
    msgs = article.get("messages")
    if isinstance(msgs, list):
        return msgs
    content = article.get("content")
    if isinstance(content, dict):
        msgs = content.get("messages")
        return msgs if isinstance(msgs, list) else []
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            return []
        msgs = data.get("messages") if isinstance(data, dict) else None
        return msgs if isinstance(msgs, list) else []
    return []


_MSG_FIELDS = ("role", "kind", "text", "no", "title", "ans", "why",
               "verifyVerdict", "verifyNote", "hasImage", "imagePath",
               "verifyRan", "verifySkipped", "verifyPending", "tools", "ts")


def session_from_article(article: dict, msgs: list) -> Session:
    """ArticleVO → 可接续的 Session：backend_id 带上，turn-end 落库走 PUT（§8-2）。

    只搬 Msg.to_dict 会落库的字段（think 不渲染也不进上下文，不搬）；
    缺键走 Msg 默认值，缺 role 的畸形行直接跳过。
    """
    sess = Session(
        title=str(article.get("title") or "新会话"),
        backend_id=str(article.get("id") or ""),
        fav=bool(article.get("fav")),
        status=str(article.get("status") or ""),
    )
    for m in msgs:
        if not isinstance(m, dict) or "role" not in m:
            continue
        kw = {k: m[k] for k in _MSG_FIELDS if k in m and m[k] not in (None, "")}
        sess.messages.append(Msg(**kw))
    return sess
