"""两阶段协议解析 + 初答自检——从 MV3 src/lib/agent.js 逐函数移植。

语义权威 = MV3 tests/answer.test.mjs；tests/test_phases.py 是它的逐条对拍。
极性判定是启发式：误伤的代价只是多跑一次核实，漏判会把矛盾答案端给用户——两侧都钉死。
"""

from __future__ import annotations

import re

# ---------- 纯移植的正则（JS 原文逐字对应） ----------

_GUARD_RE = re.compile(r"<<ok>>|<<check>>|^CERT:.*$", re.M | re.I)
_FIELD_RE = {k: re.compile(rf"^{k}:\s*(.*)$", re.M)
             for k in ("NO", "TITLE", "ANS", "WHY", "CERT", "VERDICT", "NOTE")}
_LEFTOVER_RE = re.compile(r"^(NO|TITLE|ANS|WHY|CERT):.*$", re.M)

_POL_FALSE = re.compile(r"(错误|不对|不正确|不成立|不属实|有误|选错|并非|不满足)")
_POL_TRUE = re.compile(r"(正确|无误|成立|属实|选对|满足)")
_ANS_PAREN_RE = re.compile(r"（([^）]{1,8})）|\(([^)]{1,8})\)")
_SENT_SPLIT_RE = re.compile(r"[，,。；;！？!、\s]+")

_TITLE_CLEAN_RE = re.compile(r"[\"“”'‘’《》\[\]{}（）()<>：:；;，,。.!！？?、\s]+")
_NOISE_RE = re.compile(r"[^\dA-Za-z]")


def is_self_certain(raw: object) -> bool:
    """初答里带 <<ok>> 就跳过联网核实（CERT 行或正文里出现都算）。"""
    return bool(re.search(r"<<ok>>", str(raw or ""), re.I))


def _grab(key: str, raw: str) -> str:
    m = _FIELD_RE[key].search(raw)
    return m.group(1).strip() if m else ""


def _sanitize_title(text: object) -> str:
    return _TITLE_CLEAN_RE.sub(" ", str(text or "")).strip()[:20]


def parse_phase_a(raw: object) -> dict:
    """阶段A 五行协议 → {no, title, ans, why}；模型没写 ANS 行时有兜底链。"""
    text = str(raw or "")
    no = _grab("NO", text)
    title = _grab("TITLE", text)
    ans = _grab("ANS", text)
    why = _grab("WHY", text)
    if not ans:
        # 模型没写 ANS 行（或写成别的标签/空行）：剥掉已知字段行，剩下整段当答案
        leftover = _LEFTOVER_RE.sub("", text).strip()
        if leftover:
            ans = leftover
        elif not why and no:
            ans, no = no, ""
        # 只写了 WHY：正文即答案，不能让答案栏空着（wait/展示都靠它）
        if not ans and why:
            ans, why = why, ""
    ans = _GUARD_RE.sub("", ans).strip()
    why = _GUARD_RE.sub("", why).strip()
    no = re.sub(r"\s+", "", no)
    if no in ("无", "none", "-"):
        no = ""
    title = _sanitize_title(title)
    if title in ("无", "none", "-"):
        title = ""
    return {"no": no, "title": title, "ans": ans.strip(), "why": why.strip()}


def parse_phase_b(raw: object) -> dict:
    """阶段B 三行协议 → {verdict, ans, note, ran}。

    ANS 单独抓一次：NOTE 的 [\\s\\S]* 会吃到文末，模型把 ANS 排到 NOTE 后面时会吞掉它。
    """
    text = str(raw or "")
    m = re.search(r"^VERDICT:\s*(FIX|OK)\b", text, re.M | re.I)
    verdict = m.group(1).upper() if m else ""
    ans = _grab("ANS", text)
    note = ""
    mn = re.search(r"^NOTE:\s*([\s\S]*)$", text, re.M)
    if mn:
        note = mn.group(1).strip()
    if not note:
        note = _LEFTOVER_RE.sub("", text).strip()
    note = re.sub(r"^\s*ANS:.*$", "", note, flags=re.M).strip()
    if not note:
        note = "（模型没给出核实说明，建议自己再看一眼来源）"
    if not verdict:
        return {"verdict": "", "note": note, "ans": ans, "ran": True}
    return {"verdict": verdict, "note": note, "ans": ans, "ran": True}


# ---------- 初答自检：极性 ----------

def _polarity_of(seg: object) -> bool | None:
    """一句话的结论极性：False=判错/不成立，True=判对/成立；看不出回 None。"""
    s = str(seg or "").strip()
    if not s:
        return None
    if _POL_FALSE.search(s):
        return False
    if re.fullmatch(r"错|否", s):
        return False
    if _POL_TRUE.search(s):
        return True
    if re.fullmatch(r"对|是", s):
        return True
    return None


def _polarity_of_why(why: object) -> bool | None:
    """解析的极性：从最后一个分句往前找，第一个带极性的说了算（结论都在句尾）。"""
    parts = [p for p in _SENT_SPLIT_RE.split(str(why or "")) if p]
    for p in reversed(parts):
        pol = _polarity_of(p)
        if pol is not None:
            return pol
    return None


def _polarity_of_ans(ans: object) -> bool | None:
    """答案行的极性：判断题「A（对）/ B（错）」；括号里是数值/字母就不判。"""
    text = str(ans or "").strip()
    m = _ANS_PAREN_RE.search(text)
    return _polarity_of((m.group(1) or m.group(2)) if m else text)


def contradicts(ans: object, why: object) -> bool:
    """答案行与解析结论打架（「A（对）」+「故该说法错误」）→ 不许走 <<ok>> 跳核实的捷径。"""
    a = _polarity_of_ans(ans)
    w = _polarity_of_why(why)
    return a is not None and w is not None and a != w


def format_answer_preview(no: object, ans: object, why: object) -> str:
    """流式阶段展示用：把 NO:/ANS:/WHY: 的字段拍成人话。"""
    head = f"第{_NOISE_RE.sub('', str(no or ''))}题" if no else ""
    parts = " ".join(p for p in (head, ans) if p)
    return "\n".join(p for p in (parts, why) if p)
