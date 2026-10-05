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


def _init():
    """首次用到公式才 import matplotlib（import 本身 ~1s）。"""
    global _state
    if _state is None:
        import matplotlib
        matplotlib.use("Agg")
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
    """
    out = text
    blocks: list[str] = []

    def _sub(match: re.Match) -> str:
        raw = match.group(0)
        blocks.append(_formula_html(match.group(1), raw))
        return _PH.format(len(blocks) - 1)

    for rx in (_BLOCK_DOLLAR, _BLOCK_BRACKET, _INLINE_DOLLAR, _INLINE_PAREN):
        out = rx.sub(_sub, out)
    # 规则3 后半：\$ 渲染成字面 `$`（python-markdown 不把 $ 列进可转义标点，
    # `\$` 原样留着会露反斜杠）——公式已抽走，这里替换不会再产生新分隔符
    return out.replace("\\$", "$"), blocks


def restore_math(html: str, blocks: list[str]) -> str:
    """markdown 跑完后，把公式 HTML 填回占位符（单趟正则，不逐个 replace）。"""
    if not blocks:
        return html
    return _PH_RE.sub(lambda m: blocks[int(m.group(1))], html)
