"""会话/消息模型——字段与 design/03 映射表、手机端 Session.Msg 同构。

落库时 Msg 直接序列化进 article.content.messages（后端 Msg.java 同名字段），
 imagePath/hasImage 指到题图，题图本体走 /sync/push-attachment 上推。
"""

from __future__ import annotations

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
