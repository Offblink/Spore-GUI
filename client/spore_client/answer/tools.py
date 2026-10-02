"""检索链 + 工具派发——从 MV3 src/lib/tools.js 移植（源头同步自 Fungi spec §71）。

三道闸（逐字对齐）：空页/节流页每腿重试一次；结果必须含查询实词（诱饵页不返回）；
逐腿报错 `ERROR: Search failed (duckduckgo timed out; bing HTTP 429)`。
引擎链由「代理」字段定序：填了 ddg 打头，留空只走 bing（无代理时 ddg 直连白等超时）。
全程 httpx + 手写解析（Python 侧同样不用 DOM 依赖，正则与 bs4 混用）。
"""

from __future__ import annotations

import base64
import re
import time
import urllib.parse
from collections.abc import Callable

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEARCH_TIMEOUT = 12.0
WEB_TIMEOUT = 15.0
TRUNCATE = 12000
SEARCH_ATTEMPTS = 2      # 空页/节流页是可重试的失败，每腿两次
SEARCH_RETRY_PAUSE = 0.5
SEARCH_HITS = 8
# 短词/虚词不构成「结果属于这次查询」的证据（≥4 字符实词才算）
NOISE_WORDS = frozenset({
    "the", "and", "for", "with", "how", "what", "does", "that",
    "from", "into", "about",
})

_search_proxy = ""


def set_search_proxy(v: object) -> None:
    """每次核实开始前由引擎用当前设置调一次（设置改了下一次检索即生效）。"""
    global _search_proxy
    _search_proxy = str(v or "").strip()


def search_plan(proxy: str | None = None) -> list[str]:
    """纯函数，便于断言：有代理 ddg→bing→brave，无代理只走 bing。"""
    p = _search_proxy if proxy is None else str(proxy or "").strip()
    return ["duckduckgo", "bing", "brave"] if p.strip() else ["bing"]


TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description":
                "联网检索（DuckDuckGo → Bing）。返回编号的标题、URL、摘要。"
                "ERROR: 表示各引擎都被节流或不可达——稍后重试或换措辞；"
                "(no results ...) 表示引擎有响应但确实没有命中。"
                "用于核实事实、年份、术语、数据、最新信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索词，一次聚焦一个关键点"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web",
            "description": "抓取某个网页的正文纯文本（在搜索结果的基础上深读）。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "http(s) 链接"}},
                "required": ["url"],
            },
        },
    },
]

# ---------- 文本工具（纯函数） ----------

_NAMED_ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
    "hellip": "…", "mdash": "—", "ndash": "–", "ldquo": "“", "rdquo": "”",
    "lsquo": "‘", "rsquo": "’", "times": "×", "divide": "÷",
    "middot": "·", "copy": "©",
}
_ENTITY_RE = re.compile(r"&(#x?[0-9a-fA-F]+|[a-zA-Z]+);")


def decode_entities(text: str) -> str:
    def rep(m: re.Match) -> str:
        body = m.group(1)
        if body.startswith("#"):
            hexmode = body[1:2] in ("x", "X")
            try:
                code = int(body[2:] if hexmode else body[1:],
                           16 if hexmode else 10)
                return chr(code)
            except (ValueError, OverflowError):
                return m.group(0)
        return _NAMED_ENTITIES.get(body, m.group(0))
    return _ENTITY_RE.sub(rep, text)


def strip_tags(html: str) -> str:
    out = decode_entities(re.sub(r"<[^>]*>", " ", html))
    out = re.sub(r"[ \t ]+", " ", out)
    return re.sub(r"\n{3,}", "\n\n", out)


def truncate_middle(text: str, limit: int = TRUNCATE) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n... [{len(text) - limit} chars truncated] ...\n\n{text[-half:]}"


def clean(text: object) -> str:
    """HTML 片段 → 单行纯文本（实体解码 + 压空白）。"""
    out = decode_entities(str(text or ""))
    out = re.sub(r"<[^>]*>", "", out)
    return re.sub(r"\s+", " ", out).strip()


def ddg_target(href: str) -> str:
    """duckduckgo /l/?uddg= → 真链。只解码一次——二次 unquote 会把 URL 里合法的 %20 解坏。"""
    if href.startswith("//"):
        href = "https:" + href
    try:
        parts = urllib.parse.urlsplit(href)
        q = urllib.parse.parse_qs(parts.query)
        if "uddg" in q and q["uddg"]:
            return q["uddg"][0]
    except ValueError:
        pass  # 非法 URL 原样返回
    return href


def unbing(url: str) -> str:
    """bing /ck/a?...&u=a1<base64url> → 真链（Fungi _unbing）。"""
    m = re.search(r"[?&]u=a1([A-Za-z0-9_-]+)", url)
    if not m:
        return url
    try:
        b64 = m.group(1).replace("-", "+").replace("_", "/")
        b64 += "=" * ((4 - len(b64) % 4) % 4)
        return base64.b64decode(b64).decode("utf-8")  # 非法字节 → 下面 except 兜
    except (ValueError, UnicodeDecodeError):
        return url


def relevant(query: str, results: str) -> bool:
    """相关性闸：结果必须含查询里某个实词（≥4 字符非虚词），否则判诱饵页。

    宁可报错也不给静默错答；拒绝时模型会换措辞重试。
    """
    tokens = [w for w in re.split(r"[^\w]+", query.lower())
              if len(w) >= 4 and w not in NOISE_WORDS]
    if not tokens:
        return True
    low = results.lower()
    return any(w in low for w in tokens)


def format_results(items: list[dict]) -> str:
    parts = []
    for i, it in enumerate(items):
        line = f"{i + 1}. {it['title']}\n   {it['url']}"
        if it.get("snippet"):
            line += f"\n   {it['snippet']}"
        parts.append(line)
    return "\n\n".join(parts)


def _leg_error(e: Exception) -> str:
    """腿级错误 → 引擎链报错片段（HTTP 状态原样、超时记 timed out）。"""
    if isinstance(e, httpx.TimeoutException):
        return "timed out"
    m = str(e)
    return m if re.fullmatch(r"HTTP \d+", m) else m[:60]


def _get_text(url: str, timeout: float,
              abort: Callable[[], bool] | None = None) -> str:
    if abort and abort():
        raise RuntimeError("The user aborted a request.")
    with httpx.Client(timeout=httpx.Timeout(timeout, connect=8.0),
                      follow_redirects=True,
                      headers={"User-Agent": USER_AGENT,
                               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}) as c:
        r = c.get(url)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.text


# ---------- 三条腿 ----------

def _search_ddg(query: str, abort=None) -> str:
    """DuckDuckGo 静态页：按标题锚点切分（容器 class 会变，锚点不变）。"""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    html = _get_text(url, SEARCH_TIMEOUT, abort)
    items: list[dict] = []
    for chunk in re.split(r'class="result__a"', html, flags=re.I)[1:]:
        a = re.match(r'^[^>]*?href="([^"]+)"[^>]*>([\s\S]*?)</a>',
                     chunk, re.I)
        if not a:
            continue
        href = decode_entities(a.group(1))
        if "y.js" in href or "ad_domain" in href:
            continue  # 赞助行
        sn = re.search(r'class="result__snippet"[^>]*>([\s\S]*?)</a>',
                       chunk, re.I)
        items.append({"title": clean(a.group(2)), "url": ddg_target(href),
                      "snippet": clean(sn.group(1)) if sn else ""})
        if len(items) >= SEARCH_HITS:
            break
    return format_results(items)


def _parse_rss(xml: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(r"<item>([\s\S]*?)</item>", xml):
        blk = m.group(1)
        t = re.search(r"<title>([\s\S]*?)</title>", blk)
        link = re.search(r"<link>([\s\S]*?)</link>", blk)
        d = re.search(r"<description>([\s\S]*?)</description>", blk)
        if not link:
            continue
        out.append({"title": clean(t.group(1) if t else ""),
                    "url": clean(link.group(1)),
                    "snippet": clean(d.group(1) if d else "")})
        if len(out) >= SEARCH_HITS:
            break
    return out


def _parse_html(html: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(r'<li class="b_algo[\s\S]*?</li>', html):
        blk = m.group(0)
        a = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)</a>',
                      blk)
        if not a:
            continue
        p = re.search(r"<p[^>]*>([\s\S]*?)</p>", blk)
        out.append({"title": clean(a.group(2)), "url": unbing(clean(a.group(1))),
                    "snippet": clean(p.group(1)) if p else ""})
        if len(out) >= SEARCH_HITS:
            break
    return out


def _search_bing(query: str, abort=None) -> str:
    """RSS 主 + HTML 回落（本仓实测 cn.bing 结构稳定）。

    有响应但 0 条 = ''（引擎链当可重试空页）；三个入口全网络失败才抛错。
    """
    q = urllib.parse.quote(query)
    tries = [
        f"https://cn.bing.com/search?q={q}&format=rss&count=20&setlang=zh-CN",
        f"https://www.bing.com/search?q={q}&format=rss&count=20&setlang=en-US",
        f"https://cn.bing.com/search?q={q}&count=20&setlang=zh-CN",
    ]
    last_err: Exception | None = None
    saw_body = False
    for url in tries:
        try:
            text = _get_text(url, SEARCH_TIMEOUT, abort)
        except Exception as e:  # noqa: BLE001 —— 单腿失败换下一个入口
            last_err = e
            continue
        saw_body = True
        items = _parse_rss(text) if "format=rss" in url else _parse_html(text)
        if items:
            return format_results(items)
    if saw_body:
        return ""  # 节流页/改版 → 引擎链当空页重试
    raise last_err or RuntimeError("search failed")


def _search_brave(query: str, abort=None) -> str:
    """整页去标签兜底，≥50 字才算有内容——只在前两腿全挂时出场。"""
    raw = _get_text(
        "https://search.brave.com/search?q=" + urllib.parse.quote(query),
        SEARCH_TIMEOUT, abort)
    body = re.sub(r"<script[\s\S]*?</script>", " ", raw)
    body = re.sub(r"<style[\s\S]*?</style>", " ", body)
    body = re.sub(r"<svg[\s\S]*?</svg>", " ", body)
    body = re.sub(r"<!--[\s\S]*?-->", " ", body)
    text = strip_tags(body).strip()
    return text if len(text) >= 50 else ""


# ---------- 入口 ----------

def tool_web_search(query: str, abort: Callable[[], bool] | None = None) -> str:
    legs = {"duckduckgo": _search_ddg, "bing": _search_bing,
            "brave": _search_brave}
    plan = search_plan()
    failures: list[str] = []
    empty = 0
    for name in plan:
        for attempt in range(1, SEARCH_ATTEMPTS + 1):
            if abort and abort():
                raise RuntimeError("The user aborted a request.")
            try:
                results = legs[name](query, abort)
            except Exception as e:  # noqa: BLE001 —— 硬失败不重试，换腿
                failures.append(f"{name} {_leg_error(e)}")
                break
            if results and relevant(query, results):
                return truncate_middle(results, 8000)
            if results:
                failures.append(f"{name} returned unrelated hits")
                break  # 诱饵页不重试、不返回
            empty += 1  # 空页/节流页可重试
            if attempt < SEARCH_ATTEMPTS:
                time.sleep(SEARCH_RETRY_PAUSE)
    if failures:
        # 逐腿报错聚合（去重、截 200 字）——Fungi §71 口径
        return "ERROR: Search failed (" + "; ".join(
            dict.fromkeys(failures))[:200]
    if empty:
        return f"(no results for '{query}')"
    return "ERROR: Search failed (no engine configured)"


def tool_web(url: str, abort: Callable[[], bool] | None = None) -> str:
    """正文抓取：去 script/style/noscript/svg，压缩空白，中间截断。"""
    if not re.match(r"^https?://", url, re.I):
        return f"ERROR: not an http(s) url: {url}"
    try:
        raw = _get_text(url, WEB_TIMEOUT, abort)
    except Exception as e:  # noqa: BLE001
        return f"ERROR: fetch failed ({e})"
    body = raw
    for tag in ("script", "style", "noscript", "svg"):
        body = re.sub(rf"<{tag}[\s\S]*?</{tag}>", " ", body, flags=re.I)
    body = re.sub(r"<!--[\s\S]*?-->", " ", body)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|br)>", "\n", body, flags=re.I)
    body = re.sub(r"<(br|hr)\s*/?>", "\n", body, flags=re.I)
    raw_lines = strip_tags(body).split("\n")
    lines = [ln.strip() for ln in raw_lines]
    lines = [ln for i, ln in enumerate(lines) if ln or (i > 0 and lines[i - 1])]
    stripped = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(stripped) < 30:
        return f"ERROR: empty or blocked page: {url}"
    return truncate_middle(stripped, TRUNCATE)


def dispatch(name: str, args: dict,
             abort: Callable[[], bool] | None = None) -> str:
    """统一分发入口：未知工具/缺参/异常都回填 ERROR 字符串（不掀桌给模型）。"""
    try:
        if name == "web_search":
            if not args or not args.get("query"):
                return "ERROR: Missing required argument: query"
            return tool_web_search(str(args["query"]), abort)
        if name == "web":
            if not args or not args.get("url"):
                return "ERROR: Missing required argument: url"
            return tool_web(str(args["url"]), abort)
        return f"ERROR: Unknown tool: {name}"
    except Exception as e:  # noqa: BLE001
        if "aborted" in str(e).lower():
            raise
        return f"ERROR: {e}"
