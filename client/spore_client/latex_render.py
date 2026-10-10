"""LaTeX 数学公式 → PNG data URI 内联图（回答面板 + 记录详情两个渲染点共用）。

分隔符契约（2026-10-05 主会话拍板，MV3 端按同一契约实现，两端逐条一致）：
- 块级：`$$..$$` 与 `\\[..\\]`，可跨行；
- 行内 `$..$` 四条（Pandoc 口径）：
  1) 开 `$` 后非空白——**允许 ASCII 数字开头**（`$2+2=4$` 必须渲染）；
  2) 闭 `$` 前非空白，且闭 `$` 后不是 ASCII 数字
     （治「单价 $5，$8 元」这类价格误配被吞）；
  3) `\\$` 转义美元符永不当分隔符，且渲染成字面 `$`；
  4) 行内不跨行（字符类排除 `\\n`；`\\(..\\)` 同）；
- 公式在 markdown 转义**之前**抽出（否则公式里的 `*` `_` 会被 markdown 吃掉）；
- 渲染失败（mathtext 不认识的命令/环境、空盒）→ 原样显示源码，
  不静默丢弃、不显示空白。

为什么走 matplotlib mathtext → PNG → data URI：
- Qt 富文本（QTextBrowser/QLabel 的 HTML 子集）**不支持 MathML**，
  latex2mathml 那条路是死路（2026-10-05 环境事实，别试）；
- matplotlib mathtext 是纯 Python/字体排版（Agg），无外部进程、无 LaTeX 安装；
- data URI 内联图实测可被 Qt 吃下：QTextDocument.resource 对
  `data:image/png;base64,...` 返回 QPixmap，offscreen 画布上数得出
  非背景像素（tests/test_latex_render.py::test_qt_richtext_draws_formula_pixels）。

用法（两个渲染点同一写法）：
    holed, formulas = extract_math(text)      # 先抽公式
    out = markdown.markdown(...)              # 再走 markdown（含 `<<` 转义）
    return restore_math(out, formulas)        # 最后把公式 HTML 放回去
"""

from __future__ import annotations

import base64
import html as _html
import io
import re

# 公式字号：12pt @ 100dpi ≈ 16.7px em，与正文 14.5~17px 同量级
_SIZE_PT = 12
_LOGICAL_DPI = 100     # Qt 逻辑 px 基准（width/height 属性按它算）
_RENDER_DPI = 150      # 实际渲染 dpi：150/100 → 150% 缩放屏上 1:1 落像素

_BLOCK_DOLLAR = re.compile(r"\$\$(.+?)\$\$", re.S)
_BLOCK_BRACKET = re.compile(r"\\\[(.+?)\\\]", re.S)
# 行内 $：两侧 (?<!\\) = 规则3（\$ 不当分隔符）；(?=\S) = 规则1（后随非空白，
# 数字允许）；(?<!\s) = 规则2 前半（前贴非空白）；(?![0-9]) = 规则2 后半（闭 $ 后
# 不是 ASCII 数字，防「单价 $5，$8 元」误配）；[^$\n] = 规则4 不跨行
_INLINE_DOLLAR = re.compile(r"(?<!\\)\$(?=\S)([^$\n]+?)(?<!\s)(?<!\\)\$(?![0-9])")
# 行内 \(..\)：规则4 同样不跨行（无 re.S）
_INLINE_PAREN = re.compile(r"\\\((.+?)\\\)")
# \x00 不在 markdown 的转义/内部占位（markdown 内部用 \x02/\x03，避开）
_PH = "\x00math{}\x00"
_PH_RE = re.compile("\x00math(\\d+)\x00")

_render_cache: dict[str, str] = {}
_state: tuple | None = None     # 懒加载 matplotlib：没公式的启动不付它的时间

# 中文只可能出现在 upright text（\text{} / rm 族）：默认 mathtext 字体（DejaVu/STIX）
# 没有中文字形，mathtext 不抛错、只 substituting dummy symbol——图是出了，但「发/字/节」
# 画成乱码（2026-10-10 实测样本会话 20261010-150820211：21 条公式全出图、全带缺字形警告）。
# custom 字体集把 rm/bf 指到本机含 CJK 的字体即根治；it/sf/tt/cal 不动
# （custom 下未覆盖的键保持默认 dejavusans 系，变量斜体等与切换前一致）。
_CJK_FAMILIES = ("Microsoft YaHei", "SimSun", "SimHei", "DengXian",
                 "Noto Sans CJK SC", "Noto Sans SC")
_CJK_PROBE = "中发传总字节时延处理排队"  # 样本会话公式里的全部汉字 + 基础覆盖字
_cjk_font: str | None = None     # 实际选中的字体族（测试按它判断本机是否具备条件）


def _pick_cjk_font() -> str | None:
    """找一个覆盖全部探针字的本机字体族；一个都没有 → None（保持默认行为不硬崩）。"""
    from matplotlib import font_manager as fm
    from matplotlib.ft2font import FT2Font
    for fam in _CJK_FAMILIES:
        try:
            face = FT2Font(fm.findfont(fm.FontProperties(family=[fam]),
                                       fallback_to_default=False))
            if all(face.get_char_index(ord(ch)) for ch in _CJK_PROBE):
                return fam
        except Exception:
            continue
    return None


def _init():
    """首次用到公式才 import matplotlib（import 本身 ~1s）。"""
    global _state, _cjk_font
    if _state is None:
        import matplotlib
        matplotlib.use("Agg")
        _cjk_font = _pick_cjk_font()
        if _cjk_font:
            matplotlib.rcParams["mathtext.fontset"] = "custom"
            matplotlib.rcParams["mathtext.rm"] = _cjk_font
            matplotlib.rcParams["mathtext.bf"] = f"{_cjk_font}:weight=bold"
        from matplotlib import figure
        from matplotlib.font_manager import FontProperties
        from matplotlib.mathtext import MathTextParser
        _state = (MathTextParser("path"), figure.Figure, FontProperties)
    return _state


def _render(src: str) -> tuple[bytes, int, int]:
    """mathtext 渲染（无定界符的）公式 → (透明底 PNG 字节, 逻辑宽, 逻辑高)。

    布局按 72dpi（px==pt）一次解析，出图按 _RENDER_DPI；width/height 属性按
    _LOGICAL_DPI 收算——150% 缩放屏上 logical×1.5 正好等于 PNG 自然像素。
    失败抛异常（调用方按契约回退显示源码）。
    """
    parser, Figure, FontProperties = _init()
    prop = FontProperties(size=_SIZE_PT)
    tex = f"${src}$"
    width, height, depth, _, _ = parser.parse(tex, dpi=72, prop=prop)
    if not (width > 0 and height > 0):
        raise ValueError("empty math box")
    fig = Figure(figsize=(width / 72.0, height / 72.0))
    # 与 matplotlib.math_to_image 同款定位：基线在盒底 depth 处、左缘贴边
    fig.text(0, depth / height, tex, fontproperties=prop, color="#000000")
    buf = io.BytesIO()
    fig.savefig(buf, dpi=_RENDER_DPI, format="png",
                facecolor="none", edgecolor="none")
    png = buf.getvalue()
    if not png:
        raise ValueError("empty png")
    logical_w = max(1, round(width * _LOGICAL_DPI / 72))
    logical_h = max(1, round(height * _LOGICAL_DPI / 72))
    return png, logical_w, logical_h


def _formula_html(src: str, raw: str) -> str:
    """公式 → `<img data URI>`；渲染失败 → 原样转义的源码（含定界符）。"""
    cached = _render_cache.get(raw)
    if cached is not None:
        return cached
    try:
        png, w, h = _render(src)
    except Exception:                      # 契约：任何渲染失败都回退显示源码
        out = _html.escape(raw)
    else:
        uri = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        out = (f'<img src="{uri}" width="{w}" height="{h}"'
               f' alt="{_html.escape(f"${src}$", quote=True)}"/>')
    if len(_render_cache) > 512:           # 防长会话无限涨
        _render_cache.clear()
    _render_cache[raw] = out
    return out


def extract_math(text: str) -> tuple[str, list[str]]:
    """把公式从文本里抽走，返回 (占位文本, 公式 HTML 列表)。

    顺序敏感：块级先于行内（`$$..$$` 不许被单 `$` 规则半路截胡）。
    **代码区（围栏块 / 4 空格缩进块）原样跳过**：块内的 `$` 不是公式、块内的 `\\$` 也不该被
    还原成字面 `$`——这是三端统一口径（移动/扩展的 md.js 也是「块内不解析」；本轮对齐，
    2026-10-10）。
    """
    blocks: list[str] = []
    parts: list[str] = []
    pos = 0
    for start, end in _code_ranges(text):
        parts.append(_extract_math_segment(text[pos:start], blocks))
        parts.append(text[start:end])          # 代码区原样留给 python-markdown 的
        pos = end                              # fenced_code / 缩进块去渲染
    parts.append(_extract_math_segment(text[pos:], blocks))
    return "".join(parts), blocks


def _extract_math_segment(segment: str, blocks: list[str]) -> str:
    """单段（非代码区）内摘公式；占位符序号在整篇的 blocks 上连续。"""
    def _sub(match: re.Match) -> str:
        raw = match.group(0)
        blocks.append(_formula_html(match.group(1), raw))
        return _PH.format(len(blocks) - 1)

    out = segment
    for rx in (_BLOCK_DOLLAR, _BLOCK_BRACKET, _INLINE_DOLLAR, _INLINE_PAREN):
        out = rx.sub(_sub, out)
    # 规则3 后半：\$ 渲染成字面 `$`（python-markdown 不把 $ 列进可转义标点，
    # `\$` 原样留着会露反斜杠）——公式已抽走，这里替换不会再产生新分隔符
    return out.replace("\\$", "$")


# 围栏开启行（顶格；带语言串也算）——闭合要求与开启**逐字符相同**（python fenced_code 用反向引用）
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})[^\n]*$")


def _code_ranges(text: str) -> list[tuple[int, int]]:
    """代码区（围栏块 + 4 空格缩进块）的 [start, end) 偏移表。

    口径照 python-markdown 实测：围栏必须顶格（缩进即不认）、未闭合不算围栏；
    缩进块要求块起点（文档开头或空行之后），块内空行只在其后仍有缩进行时保留。
    """
    lines = text.split("\n")
    offsets: list[int] = []
    pos = 0
    for line in lines:
        offsets.append(pos)
        pos += len(line) + 1                    # +1 = 被 split 吃掉的换行
    ranges: list[tuple[int, int]] = []
    i = 0
    prev_blank = True                           # 文档开头算块起点
    while i < len(lines):
        line = lines[i]
        m = _FENCE_OPEN.match(line.rstrip())
        if m:
            marker = m.group(1)
            j = i + 1
            close = -1
            while j < len(lines):
                if lines[j].rstrip() == marker:
                    close = j
                    break
                j += 1
            if close >= 0:
                ranges.append((offsets[i], offsets[close] + len(lines[close])))
                i = close + 1
                prev_blank = False
                continue
            # 未闭合 → 不是围栏（python 口径），落回普通行处理
        if prev_blank and line.startswith("    "):
            j = i
            last = i
            while j < len(lines):
                cur = lines[j]
                if cur.startswith("    "):
                    last = j
                    j += 1
                elif cur.strip() == "" and j + 1 < len(lines) and lines[j + 1].startswith("    "):
                    j += 1                          # 块内空行（后面还有缩进行才算块内）
                else:
                    break
            ranges.append((offsets[i], offsets[last] + len(lines[last])))
            i = last + 1
            prev_blank = False
            continue
        prev_blank = line.strip() == ""
        i += 1
    return ranges


def restore_math(html: str, blocks: list[str]) -> str:
    """markdown 跑完后，把公式 HTML 填回占位符（单趟正则，不逐个 replace）。"""
    if not blocks:
        return html
    return _PH_RE.sub(lambda m: blocks[int(m.group(1))], html)


_IMG_TAG = re.compile(r'<img\s[^>]*?src="([^"]+)"[^>]*?>', re.I | re.S)
_IMG_ALT = re.compile(r'alt="([^"]*)"', re.I)


def placeholder_remote_images(html: str) -> str:
    """非 data URI 的图片 → 可见占位文本。

    Qt 富文本**不下载远程图**（QTextDocument 没有默认的网络资源加载器），
    原样留着 `<img src="https://…">` 的结果是**什么都不显示**——信息直接消失。
    这里退化成 `［图片：alt 或 URL］`，至少让读者知道此处有图与它的地址；
    公式渲出来的内联图是 data URI，原样保留（不受影响）。
    """
    def _sub(m: re.Match) -> str:
        src = m.group(1)
        if src.startswith("data:"):
            return m.group(0)
        alt = _IMG_ALT.search(m.group(0))
        label = alt.group(1) if (alt and alt.group(1)) else src
        return f"［图片：{_html.escape(label)}］"

    return _IMG_TAG.sub(_sub, html)
