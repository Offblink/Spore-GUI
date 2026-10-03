"""两阶段作答编排——从 MV3 src/lib/agent.js 的 runTurn/verifyPhase 移植。

事件族与 MV3 同名（status/answer-start/answer-delta/think-delta/chat-start/
chat-delta/verify-delta/tool/title/error/turn-end），AnswerWindow 只认这套。
线程模型：回合跑在后台线程（引擎自持），emit 回调由调用方负责切回 UI 线程
（Qt 侧用 signal，跨线程 emit 自动队列化）。
"""

from __future__ import annotations

import base64
import threading
from collections.abc import Callable
from pathlib import Path

from ..answer.llm import AbortedError, stream_chat
from ..answer.phases import (
    contradicts,
    format_answer_preview,
    is_self_certain,
    parse_phase_a,
    parse_phase_b,
)
from ..answer.prompts import (
    CHAT_FORCE_FINAL,
    PHASE_A,
    PHASE_B,
    SYSTEM,
    VERIFY_FORCE_FINAL,
)
from ..answer.session import Msg, Session
from ..answer.settings import LlmSettings
from ..answer.tools import TOOLS, dispatch, set_search_proxy
from ..log import get_logger

LOG = get_logger()

Emit = Callable[[dict], None]


class Aborted(Exception):
    """回合被用户中止（与 llm.AbortedError 区分：这是引擎级出口）。"""


def image_data_url(path: str) -> str:
    """题图 → data URL（vision 消息要的形态）；读失败给占位图不炸回合。"""
    try:
        raw = Path(path).read_bytes()
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    except OSError:
        return ""


def _image_part(url: str) -> dict:
    return {"type": "image_url", "image_url": {"url": url}}


def _parse_tool_args(raw: str) -> dict:
    import json
    try:
        return json.loads(raw or "{}")
    except json.JSONDecodeError:
        try:
            # 尾逗号等常见小毛病：去掉再试一次（agent.js 同款兜底）
            import re
            return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
        except json.JSONDecodeError:
            return {}


class AgentEngine:
    def __init__(self, settings: LlmSettings, emit: Emit):
        self.settings = settings
        self._emit = emit
        self.session = Session()
        self._abort = threading.Event()
        self._worker: threading.Thread | None = None
        set_search_proxy(settings.proxy)

    # ---------- 对外入口 ----------
    def new_capture_turn(self, image_path: str, supplement: str = "") -> Session:
        """截屏作答入口：新会话 + 用户消息（带图），后台开跑。"""
        self.session = Session(image_path=image_path)
        self.session.messages.append(
            Msg(role="user", kind="answer", text=supplement,
                hasImage=True, imagePath=image_path))
        self._start(self._run_turn)
        return self.session

    def send_followup(self, text: str) -> bool:
        """追问：复用当前会话（同一回合语义与 MV3 一致）。"""
        if self.is_busy():
            return False
        self.session.messages.append(Msg(role="user", kind="chat", text=text))
        self._start(self._run_turn)
        return True

    def load_session(self, sess: Session) -> bool:
        """收编一条外部（历史）会话，下一条追问即在其上接续（§8-2）。

        只置会话、清中止位，**不新建 worker 线程**——发消息时才开跑；
        正在跑别的回合时不换（换会把两场对话串到一起），返回 False 由
        调用方保持只读。turn-end 落库侧看 sess.backend_id 决定 POST/PUT。
        """
        if self.is_busy():
            return False
        self._abort.clear()
        self.session = sess
        return True

    def verify_only(self) -> bool:
        """手动核实（阶段B 单独跑）；没有可核实的回答返回 False。"""
        if self.is_busy() or self.session.last_answer is None:
            return False
        self._start(self._run_verify_only)
        return True

    def is_busy(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def cancel(self):
        self._abort.set()

    def _start(self, fn):
        self._abort.clear()
        self._worker = threading.Thread(target=fn, daemon=True, name="spore-agent")
        self._worker.start()

    # ---------- 主循环（agent.js runTurn 镜像） ----------
    def _run_turn(self):
        sess = self.session
        last = sess.messages[-1]
        if last.role != "user":
            self._fail(ValueError("no pending user message"), -1)
            return
        idx = len(sess.messages) - 1  # 占位：答案消息入列后会重算
        try:
            if not last.hasImage:
                self._run_chat(sess, last)
            else:
                self._run_capture(sess, last)
        except (Aborted, AbortedError) as e:
            self._finish(sess, idx, aborted=True, err=e)
        except Exception as e:  # noqa: BLE001 —— 回合错误必须全部收敛到 error 事件
            self._fail(e, idx)

    # ------------------------------------------------ 截图提问：两阶段
    def _run_capture(self, sess: Session, user_msg: Msg):
        self._set_status(sess, "answering", "读题中…")
        image = image_data_url(sess.image_path or user_msg.imagePath)
        extra = f"\n\n用户补充：{user_msg.text}" if user_msg.text else ""
        answer = Msg(role="assistant", kind="answer")
        sess.messages.append(answer)
        idx = len(sess.messages) - 1
        LOG.info("worker: image ready (%d b64 chars), emitting answer-start",
                 len(image))
        self._emit({"type": "answer-start", "idx": idx})

        api = self._api_kwargs()
        # ---- 阶段A：读题初答（流式，边收边解析五行协议）
        messages = [{"role": "user", "content": [
            _image_part(image), {"type": "text", "text": PHASE_A + extra}]}]

        def on_delta(kind, chunk, acc):
            if kind == "reasoning":
                if acc.get("reasoning", "") != answer.think:
                    answer.think = acc.get("reasoning", "")
                    self._emit({"type": "think-delta", "idx": idx,
                                "kind": "answer", "think": answer.think})
                return
            if kind not in ("text", "tool") or not chunk:
                return
            p = parse_phase_a(acc.get("content", ""))
            if (p["no"], p["title"], p["ans"], p["why"]) != \
               (answer.no, answer.title, answer.ans, answer.why):
                answer.no, answer.title, answer.ans, answer.why = \
                    p["no"], p["title"], p["ans"], p["why"]
                self._emit({"type": "answer-delta", "idx": idx, **_ans_dict(answer)})

        LOG.info("worker: phaseA stream_chat begin")
        res_a = stream_chat(messages=messages, no_think=self.settings.fast_no_think,
                            on_delta=on_delta, abort=self._abort.is_set, **api)
        LOG.info("worker: phaseA stream_chat done (%d chars)",
                 len(res_a.get("content", "")))
        raw_a = res_a.get("content", "")
        p = parse_phase_a(raw_a)
        answer.no = p["no"] or answer.no
        answer.title = p["title"] or answer.title
        answer.ans = p["ans"] or answer.ans
        answer.why = p["why"] or answer.why
        self._emit({"type": "answer-delta", "idx": idx, **_ans_dict(answer)})
        self._kick_naming(sess, answer)

        # ---- 守卫：<<ok>> 自评确定 → 跳核实；但答案与解析打架时必须复核
        certain = is_self_certain(raw_a)
        fighting = contradicts(answer.ans, answer.why)
        if certain and not fighting:
            answer.verifySkipped = True
            answer.verifyVerdict = "OK"
            answer.verifyNote = "初答自评「确定」（<<ok>> 守卫），已跳过联网核实。"
            self._emit({"type": "verify-delta", "idx": idx, "ran": False,
                        "skipped": True, "verdict": "OK", "note": answer.verifyNote,
                        "done": True})
            self._finish(sess, idx)
            return
        if self.settings.auto_verify:
            self._verify_phase(sess, answer, idx, image, extra)
        else:
            answer.verifyPending = True
            answer.verifyNote = "已关闭自动核实 · 点「核实一下」开始"
            self._emit({"type": "verify-delta", "idx": idx, "ran": False,
                        "pending": True, "note": answer.verifyNote, "done": True})
        self._finish(sess, idx)

    # ------------------------------------------------ 阶段B：联网核实（工具循环）
    def _verify_phase(self, sess, answer: Msg, idx, image, extra):
        rounds = max(0, self.settings.max_tool_rounds)
        if rounds <= 0:
            return
        set_search_proxy(self.settings.proxy)
        self._set_status(sess, "verifying", "核实中…")
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                _image_part(image), {"type": "text", "text": PHASE_A + extra}]},
            {"role": "assistant",
             "content": f"NO: {answer.no or '无'}\nANS: {answer.ans}\nWHY: {answer.why}"},
            {"role": "user", "content": PHASE_B.replace("$R$", str(rounds))},
        ]
        api = self._api_kwargs()
        verify = None
        for _round in range(rounds + 1):
            self._check_abort()
            res = stream_chat(messages=messages, tools=TOOLS, no_think=False,
                              on_delta=self._verify_delta_cb(answer, idx),
                              abort=self._abort.is_set, **api)
            if not res.get("tool_calls"):
                verify = parse_phase_b(res.get("content", ""))
                break
            self._set_status(sess, "searching", "检索中…")
            messages.append(_assistant_tool_msg(res))
            for tc in res["tool_calls"]:
                args = _parse_tool_args(tc.get("args", ""))
                brief = str(args.get("query") or args.get("url") or "")[:80]
                if answer.tools is None:
                    answer.tools = []
                answer.tools.append(("读取 " if tc["name"] == "web" else "检索 ") + brief)
                self._emit({"type": "tool", "idx": idx,
                            "name": tc["name"], "brief": brief})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": dispatch(tc["name"], args,
                                                     self._abort.is_set)})
        if verify is None and not self._abort.is_set():
            # 检索轮次用光：收走工具，强制输出三行结论
            fin = stream_chat(
                messages=[*messages, {"role": "user", "content": VERIFY_FORCE_FINAL}],
                max_tokens=300, no_think=False,
                on_delta=self._verify_delta_cb(answer, idx),
                abort=self._abort.is_set, **api)
            verify = parse_phase_b(fin.get("content", ""))
        if verify is None:
            verify = {"verdict": "", "note": "核实失败（网络或模型异常），可点 ↻ 重试。",
                      "ran": True}
        # FIX 且给出修正答案 → 覆盖答案行（否则答案说对、核实说错并排摆着）
        fixed = str(verify.get("ans", "")).strip()
        if verify.get("verdict") == "FIX" and fixed and \
                fixed.lower() not in ("无", "none", "-") and fixed != answer.ans:
            answer.ans = fixed
            self._emit({"type": "answer-delta", "idx": idx, **_ans_dict(answer)})
        answer.verifyRan = True
        answer.verifyPending = False   # 已跑完：不再是「待核实」（图1 类脏状态）
        answer.verifyVerdict = verify.get("verdict", "")
        answer.verifyNote = verify.get("note", "")
        self._emit({"type": "verify-delta", "idx": idx, "ran": True,
                    "verdict": answer.verifyVerdict, "note": answer.verifyNote,
                    "done": True})

    # ------------------------------------------------ 追问（纯文本 + 工具循环）
    def _run_chat(self, sess: Session, user_msg: Msg):
        self._set_status(sess, "answering", "回答中…")
        msg = Msg(role="assistant", kind="chat")
        sess.messages.append(msg)
        idx = len(sess.messages) - 1
        # text = 用户追问原文：面板要把它显示成用户气泡（MV3 utext 同语义）
        self._emit({"type": "chat-start", "idx": idx, "text": user_msg.text})
        set_search_proxy(self.settings.proxy)
        # 追问轮次下限 1：设置关的是「自动核实」，不是「永远不许查」
        rounds = max(1, self.settings.max_tool_rounds)
        messages = [{"role": "system", "content": SYSTEM}]
        messages += self._history()
        api = self._api_kwargs()
        think_base = ""

        def on_delta(kind, chunk, acc):
            nonlocal think_base
            if kind == "reasoning":
                msg.think = think_base + acc.get("reasoning", "")
                self._emit({"type": "think-delta", "idx": idx,
                            "kind": "chat", "think": msg.think})
                return
            if kind != "text" or not chunk:
                return
            msg.text += chunk
            self._emit({"type": "chat-delta", "idx": idx,
                        "text": chunk, "total": msg.text})

        last = None
        for _ in range(rounds):
            self._check_abort()
            last = stream_chat(messages=messages, tools=TOOLS,
                               on_delta=on_delta, abort=self._abort.is_set, **api)
            if not last.get("tool_calls"):
                break
            self._set_status(sess, "searching", "检索中…")
            messages.append(_assistant_tool_msg(last))
            for tc in last["tool_calls"]:
                args = _parse_tool_args(tc["args"])
                brief = str(args.get("query") or args.get("url") or "")[:80]
                if msg.tools is None:
                    msg.tools = []
                msg.tools.append(("读取 " if tc["name"] == "web" else "检索 ") + brief)
                self._emit({"type": "tool", "idx": idx,
                            "name": tc["name"], "brief": brief})
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": dispatch(tc["name"], args,
                                                     self._abort.is_set)})
            think_base = msg.think
            self._set_status(sess, "answering", "")
            last = None  # 这一轮只有工具调用，正文等下一轮
        if last is None:
            self._check_abort()
            last = stream_chat(
                messages=[*messages, {"role": "user", "content": CHAT_FORCE_FINAL}],
                on_delta=on_delta, abort=self._abort.is_set, **api)
        if not msg.text and last.get("content"):
            msg.text = last["content"]
        self._finish(sess, idx)

    # ------------------------------------------------ 手动核实
    def _run_verify_only(self):
        sess = self.session
        answer = sess.last_answer
        if answer is None:
            return
        idx = sess.messages.index(answer)
        user = sess.last_user
        image = image_data_url(sess.image_path or (user.imagePath if user else ""))
        extra = f"\n\n用户补充：{user.text}" if user and user.text else ""
        try:
            answer.verifyRan = False
            self._set_status(sess, "verifying", "核实中…")
            self._verify_phase(sess, answer, idx, image, extra)
            self._finish(sess, idx)
        except (Aborted, AbortedError) as e:
            self._finish(sess, idx, aborted=True, err=e)
        except Exception as e:  # noqa: BLE001
            self._fail(e, idx)

    # ---------- 收尾 ----------
    def _finish(self, sess: Session, idx: int, aborted=False, err=None, error=False):
        sess.status = "aborted" if aborted else ("error" if error else "done")
        if err is not None:
            sess.status = "aborted" if aborted else "error"
        sess.touch()
        ev = {"type": "turn-end", "idx": idx}
        if aborted:
            ev["aborted"] = True
        if error:
            ev["error"] = True
        self._emit(ev)

    def _fail(self, e: Exception, idx: int):
        aborted = isinstance(e, (Aborted, AbortedError))
        sess = self.session
        if not sess.title or sess.title == "新会话":
            self._ensure_named(sess)
        msg = str(getattr(e, "message", None) or e)[:200]
        if not aborted:
            self._emit({"type": "error", "idx": idx, "message": msg})
        self._finish(sess, idx, aborted=aborted, error=not aborted)

    def _check_abort(self):
        if self._abort.is_set():
            raise Aborted()

    def _set_status(self, sess, status, text):
        sess.status = status
        self._emit({"type": "status", "status": status, "text": text})

    def _api_kwargs(self):
        return {"endpoint": self.settings.endpoint,
                "api_key": self.settings.api_key,
                "model": self.settings.model}

    # ---------- 起名（纯本地零模型调用，agent.js kickNaming 语义） ----------
    def _kick_naming(self, sess: Session, answer: Msg):
        title = answer.title or (answer.ans[:14] if answer.ans else "")
        if not title:
            return
        self._rename(sess, title)

    def _ensure_named(self, sess: Session):
        if sess.title and sess.title != "新会话":
            return
        a = sess.last_answer
        title = (a.title if a else "") or (a.ans[:14] if a and a.ans else "")
        if title:
            self._rename(sess, title)

    def _rename(self, sess: Session, title: str):
        head = f"第{sess.last_answer.no}题 " if (
            sess.last_answer and sess.last_answer.no) else ""
        sess.title = (head + title)[:40]
        sess.touch()
        self._emit({"type": "title", "title": sess.title})

    # ---------- 上下文：只保留最近一张图（agent.js historyMessages 语义） ----------
    def _history(self) -> list[dict]:
        msgs: list[dict] = []
        img_idx = -1
        for i, m in enumerate(self.session.messages):
            if m.role == "user" and m.hasImage:
                img_idx = i
        url = image_data_url(
            self.session.messages[img_idx].imagePath) if img_idx >= 0 else ""
        limit = self.settings.history_limit
        start = max(0, len(self.session.messages) - limit)
        for i, m in enumerate(self.session.messages):
            if i < start:
                continue
            if m.role == "user":
                if url and i == img_idx:
                    msgs.append({"role": "user", "content": [
                        _image_part(url),
                        {"type": "text", "text": m.text or "（题目截图）"}]})
                else:
                    msgs.append({"role": "user",
                                 "content": m.text or "（题目截图）"})
            elif m.kind == "answer":
                msgs.append({"role": "assistant", "content":
                             format_answer_preview(m.no, m.ans, m.why)})
            elif m.kind == "chat" and m.text:
                msgs.append({"role": "assistant", "content": m.text})
        return msgs

    def _verify_delta_cb(self, answer: Msg, idx: int):
        def on_delta(kind, chunk, acc):
            if kind == "reasoning":
                if acc.get("reasoning", "") != answer.verifyThink:
                    answer.verifyThink = acc.get("reasoning", "")
                    self._emit({"type": "think-delta", "idx": idx,
                                "kind": "verify", "think": answer.verifyThink})
                return
            if kind == "text" and chunk:
                self._emit({"type": "verify-delta", "idx": idx,
                            "note": acc.get("content", ""), "verdict": ""})
        return on_delta


def _ans_dict(m: Msg) -> dict:
    return {"no": m.no, "title": m.title, "ans": m.ans, "why": m.why,
            "preview": format_answer_preview(m.no, m.ans, m.why)}


def _assistant_tool_msg(res: dict) -> dict:
    calls = [{"id": t["id"], "type": "function",
              "function": {"name": t["name"], "arguments": t["args"]}}
             for t in res.get("tool_calls", [])]
    return {"role": "assistant", "content": res.get("content") or None,
            "tool_calls": calls}
