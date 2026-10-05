"""P6-GUI：两个渲染点的 LaTeX 数学公式渲染。

契约（与 MV3 端一致，主会话拍板）：
- 四类分隔符：`$$..$$` 块级、`$..$` 行内（开 `$` 后非空白、闭 `$` 前非空白，
  `$5` 不触发）、`\\[..\\]` 块级、`\\(..\\)` 行内；
- 渲染失败 → 原样显示源码（不静默丢弃、不显示空白）；
- 公式在 markdown 转义**之前**抽出（否则 `*` `_` 会被 markdown 吃掉）。
Qt 富文本不吃 MathML → 走 matplotlib mathtext → PNG → data URI 内联 img；
真像素断言证明 Qt 真能把 data URI 画出来（不是只拼了字符串）。
"""

import base64
import re

from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument

from spore_client.answer_window import _md_html
from spore_client.latex_render import extract_math
from spore_client.records import _detail_html

# 四类分隔符（每类都必须出渲染产物）
FOUR = [
    "$$E=mc^2$$",                 # 块级双美元
    "行内 $a^2+b^2=c^2$ 公式",     # 行内单美元
    r"\[\sum_{i=1}^{n} i\]",      # 反斜杠方括号包块
    r"值为 \(\sqrt{x+1}\)",        # 反斜杠小括号包行内
]

IMG_RE = re.compile(r'<img src="data:image/png;base64,([A-Za-z0-9+/=]+)"')


def _png_alphas(html: str) -> list[int]:
    """抽出 html 里所有 data URI 图，解码成 QImage，返回各自的非透明像素数。"""
    out = []
    for b64 in IMG_RE.findall(html):
        png = base64.b64decode(b64)
        img = QImage()
        assert img.loadFromData(png, "PNG"), "data URI 里的 PNG 必须能被 Qt 解码"
        assert not img.isNull() and img.width() > 0 and img.height() > 0
        n = 0
        for y in range(img.height()):
            for x in range(img.width()):
                if img.pixelColor(x, y).alpha() > 16:
                    n += 1
        out.append(n)
    return out


def _detail(text: str) -> str:
    return _detail_html({"messages": [
        {"role": "assistant", "kind": "chat", "text": text}]})


# ---------------------------------------------------------------- 红证/绿证
def test_answer_panel_renders_all_four_delimiters():
    for s in FOUR:
        html = _md_html(s)
        assert 'data:image/png;base64,' in html, f"未渲染: {s!r}"
        assert all(n > 40 for n in _png_alphas(html)), \
            f"公式图必须有真像素（非空白）: {s!r}"


def test_records_detail_renders_all_four_delimiters():
    for s in FOUR:
        html = _detail(s)
        assert 'data:image/png;base64,' in html, f"未渲染: {s!r}"
        assert all(n > 40 for n in _png_alphas(html)), \
            f"公式图必须有真像素（非空白）: {s!r}"


def test_qt_richtext_draws_formula_pixels(qapp):
    """真画：offscreen QTextDocument 渲 data URI 图 → 画布上出现非背景像素。

    只放一张公式图（周围不放任何文字），白底上数非白像素——
    吃不下 data URI 的实现这里必然是 0。
    """
    html = _md_html("$$\\sum_{i=1}^{n} x_i^2 = \\frac{n(n+1)}{2}$$")
    m = re.search(r'<img [^>]+/>', html)
    assert m, "块级公式应产出 <img>"
    doc = QTextDocument()
    doc.setHtml(m.group(0))
    doc.setTextWidth(400)
    img = QImage(400, 120, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    doc.drawContents(painter)
    painter.end()
    nonwhite = sum(
        1 for y in range(img.height()) for x in range(img.width())
        if (lambda c: c.red() < 245 or c.green() < 245 or c.blue() < 245)(
            img.pixelColor(x, y)))
    assert nonwhite > 200, f"Qt 未把公式图画出来: nonwhite={nonwhite}"


# ---------------------------------------------------------------- 分隔符边界
def test_dollar_five_not_captured():
    """`$5` 这种价格文本不许被当公式（开 `$` 后/闭 `$` 前边界规则）。"""
    for s in ("价格 $5", "价格 $5 与 $10", "值 $ 5 $"):
        html = _md_html(s)
        assert 'data:image/png' not in html, f"$5 被误伤: {s!r}"
        assert "$" in html or "&amp;" in html   # 源码原样可见


def test_dollar_five_alongside_real_formula_still_renders():
    html = _md_html("价格 $5，公式 $x^2$ 在此")
    assert 'data:image/png;base64,' in html
    assert "$5" in html                          # 价格原样保留


def test_broken_formula_falls_back_to_raw_source():
    """mathtext 解析失败（未知命令）→ 原样显示源码，不许静默丢弃/空白。"""
    html = _md_html("$$\\notacommand{x}$$")
    assert 'data:image/png' not in html
    assert "\\notacommand{x}" in html            # 源码原样在
    # 定界符也原样显示
    assert "$$" in html


def test_formula_content_survives_markdown_escaping():
    """公式在 markdown 转义之前抽出：`*` `_` 不许被 markdown 变成强调标签。"""
    html = _md_html("行内 $a_b*c$ 尾")
    assert 'data:image/png;base64,' in html
    assert "<em>" not in html and "<strong>" not in html
    assert "a_b*c" in html                       # alt 属性留着源码


def test_broken_formula_escapes_html():
    """失败回退的源码进 HTML 前要转义，`<` 不许被富文本当标签吃掉。"""
    html = _md_html("$$a < b$$")
    if 'data:image/png' not in html:
        assert "a &lt; b" in html
        assert "a < b" not in html


def test_plain_text_untouched():
    assert 'data:image/png' not in _md_html("普通回答，没有公式 1+1=2。")
    assert 'data:image/png' not in _detail("普通回答。")


# ------------------------------------------ 行内分隔符四条（主会话 2026-10-05 拍板）
def test_rule1_digit_opener_renders():
    """规则1：开 `$` 后允许 ASCII 数字——`$2+2=4$` 必须渲染成图。"""
    html = _md_html("口算 $2+2=4$ 结束")
    assert 'data:image/png;base64,' in html
    assert all(n > 40 for n in _png_alphas(html))


def test_rule2_closer_not_followed_by_digit():
    """规则2：闭 `$` 后是数字 → 不配对——「单价 $5，$8 元」整段留原文。"""
    html = _md_html("单价 $5，$8 元")
    assert 'data:image/png' not in html, "价格对被当公式吞了"
    assert "$5" in html and "$8" in html, "价格必须原样可见"

    # 真实混排：价格 + 空格 + 公式 → 价格留原文、公式照常出图
    html = _md_html("单价 $5，公式 $x^2$ 元")
    assert 'data:image/png;base64,' in html
    assert "$5" in html


def test_rule3_escaped_dollar_not_delimiter_and_literal():
    """规则3：`\\$` 不当分隔符，且渲染成字面 `$`（不露反斜杠）。"""
    html = _md_html(r"转义 \$5 与 $x^2$")
    assert 'data:image/png;base64,' in html, "真公式仍要渲染"
    assert "\\$5" not in html, "转义美元符要显示成字面 $"
    assert "$5" in html


def test_rule4_inline_does_not_cross_lines():
    """规则4：行内裸 `$` 跨行不配对（块级可跨行，见下）。"""
    holed, blocks = extract_math("$a\nb$")
    assert blocks == [], "行内跨行不许配对"
    assert holed == "$a\nb$"
    html = _md_html("$a\nb$")
    assert 'data:image/png' not in html
    assert "$a" in html                      # 源码原样可见


def test_rule4_block_may_cross_lines():
    """块级 `$$..$$` 允许跨行：抽取层必须吃下（mathtext 渲不了就回退源码）。"""
    _, blocks = extract_math("$$a\nb$$")
    assert len(blocks) == 1, "块级应跨行抽取"
    _, blocks = extract_math("\\[a\nb\\]")
    assert len(blocks) == 1, "\\[..\\] 应跨行抽取"
