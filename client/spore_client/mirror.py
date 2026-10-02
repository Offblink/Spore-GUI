"""磁盘镜像：把一个回合写成 markdown（best-effort，绝不向上抛）。

落点：<root>/<sub_root>/<YYYY-MM-DD>/<安全文件名>.md，题图拷到同目录同名 .jpg。
主线在回合落库后调用——它已经是收尾路径，镜像失败只许 LOG.warning，
不能把落库链路拖死（写盘异常 / 权限 / 盘满 全部收敛成返回 None）。
"""

from __future__ import annotations

import datetime
import re
import shutil
from pathlib import Path

from .log import get_logger

LOG = get_logger()

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MAX_NAME = 80


def _safe_name(title: str, fallback: str = "未命名会话") -> str:
    """文件名安全化：去 \\ / : * ? \" < > | 与控制字符，去首尾点空格，限长。"""
    name = _UNSAFE.sub("", str(title or "")).strip(" .")
    name = re.sub(r"\s+", " ", name)
    return name[:_MAX_NAME] or fallback


def _render(title: str, messages: list[dict]) -> str:
    """回合 → markdown。reason 全应用抛弃：think/verifyThink 永不落盘。"""
    out = [f"# {title or '未命名会话'}", ""]
    for m in messages:
        role = m.get("role", "")
        kind = m.get("kind", "")
        if role == "user":
            body = (str(m.get("text") or "")).strip()
            head = "## 截图提问" if m.get("hasImage") else "## 提问"
            out.append(head)
            if body:
                out.append(body)
            else:
                out.append("（截图）")
            out.append("")
            continue
        if kind == "answer":
            if m.get("no"):
                out.append(f"## 初答 {m['no']}")
            else:
                out.append("## 初答")
            if m.get("title"):
                out.append(f"**{m['title']}**")
            if m.get("ans"):
                out.append(str(m["ans"]).strip())
            if m.get("why"):
                out.append("")
                out.append("**解析**")
                out.append(str(m["why"]).strip())
            tools = m.get("tools") or []
            if tools:
                out.append("")
                out.append("**检索**")
                out.extend(f"- {t}" for t in tools)
            verdict = str(m.get("verifyVerdict") or "")
            if verdict:
                mark = {"OK": "通过", "FIX": "修正"}.get(
                    verdict.upper(), verdict)
                note = str(m.get("verifyNote") or "").strip()
                out.append("")
                out.append(f"**核实**：{mark}" + (f" —— {note}" if note else ""))
            out.append("")
        else:  # 追问 / 聊天
            body = (str(m.get("text") or "")).strip()
            if body:
                out.append("## 追问")
                out.append(body)
                out.append("")
    return "\n".join(out).strip() + "\n"


def write_turn(*, root: str, sub_root: str, title: str,
               messages: list[dict], image_path: str | None,
               with_image: bool) -> Path | None:
    """把一个回合写成 <root>/<sub_root>/<YYYY-MM-DD>/<安全文件名>.md。

    with_image=True 且 image_path 指向存在的题图 → 拷到同目录 <同名>.jpg。
    全程 best-effort：任何异常只 LOG.warning 并返回 None，绝不向上抛。
    """
    try:
        # sub_root 是路径：按分隔符拆段逐段消毒（保留层级，防 .. 蹲出去）
        parts = [_UNSAFE.sub("", p).strip(" .")
                 for p in re.split(r"[\\/]+", str(sub_root or "")) if p]
        parts = [p for p in parts if p]
        day = Path(root).joinpath(*parts) if parts else Path(root)
        day = day / datetime.date.today().isoformat()
        day.mkdir(parents=True, exist_ok=True)
        md = day / (_safe_name(title) + ".md")
        md.write_text(_render(title, messages), encoding="utf-8")
        if with_image and image_path:
            src = Path(image_path)
            if src.is_file():
                shutil.copy2(src, md.with_suffix(".jpg"))
        LOG.info("mirror wrote %s (%d bytes)", md, md.stat().st_size)
        return md
    except Exception as e:  # noqa: BLE001 —— 镜像是旁路，失败绝不掀翻落库
        LOG.warning("mirror write failed for %r: %s", title, e)
        return None
