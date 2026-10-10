"""表格网格线：两个渲染点（回答面板 QLabel / 记录详情 QTextDocument）真画得出框。

背景（2026-10-10 用户实测「表格怎么没有网格线」）：python-markdown 的表格只吐光板
`<table>/<th>/<td>`，而 Qt 富文本既不认 `<table border="1">` 属性、也**不认挂在
th/td 上的 border**（本机探针均 0 像素）——线必须挂在 `table` 元素上才画得出来。
`latex_render.style_tables` 于是给结果挂一段 `<style>` 并把表撑满（width="100%"）。

断言用真像素：带样式的渲染要出现 #E6E8F2 线与 #F1F3FB 表头底色；同一段 markdown
光板渲出来必须一条线都没有（负对照，免得断言退化成「Qt 反正会画框」的同义反复）。
"""

import markdown
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument
from PySide6.QtWidgets import QApplication, QLabel

from spore_client.answer_window import _md_div
from spore_client.records import _md

TABLE = """| 链路 | 单向时延 | 往返 RTT |
|:---|---:|:---|
| 地面站→卫星 | 120 ms | 240 ms |
| 跨洋中继（两跳） | 260 ms | 520 ms |
"""

LINE = QColor("#E6E8F2")      # 线色（spore.css --line）
CHIP = QColor("#F1F3FB")      # 表头底色（--chip）
W, H = 360, 220


def _paint(img: QImage, target: QColor, tol: int = 8) -> int:
    """画布上与 target 各通道差 ≤ tol 的像素数（抗锯齿混色也落在容差内）。"""
    n = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if (abs(c.red() - target.red()) <= tol
                    and abs(c.green() - target.green()) <= tol
                    and abs(c.blue() - target.blue()) <= tol):
                n += 1
    return n


def _label_image(html: str) -> QImage:
    """回答面板那条路：QLabel（RichText，与 _md_label 同设）离屏渲一帧。"""
    lbl = QLabel()
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setStyleSheet("background:#ffffff; color:#1a1d2e; font-size:17px;")
    lbl.setText(html)
    lbl.resize(W, H)
    lbl.show()
    QApplication.processEvents()
    img = lbl.grab().toImage()
    lbl.hide()
    return img


def _doc_image(html: str) -> QImage:
    """记录详情那条路：QTextEdit.setHtml 的同款外层 div + QTextDocument 出图。"""
    doc = QTextDocument()
    doc.setHtml('<div style="font-size:15px; line-height:1.6; color:#1a1d2e;">'
                f"{html}</div>")
    doc.setTextWidth(W)
    img = QImage(W, H, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    painter = QPainter(img)
    doc.drawContents(painter)
    painter.end()
    return img


def _raw_md(src: str) -> str:
    """同源 markdown、**不带** style_tables —— 负对照。"""
    return markdown.markdown(src, extensions=["fenced_code", "tables", "nl2br"])


def _x_span(img: QImage) -> int:
    xs = [x for y in range(img.height()) for x in range(img.width())
          if (lambda c: abs(c.red() - LINE.red()) <= 8
              and abs(c.green() - LINE.green()) <= 8
              and abs(c.blue() - LINE.blue()) <= 8)(img.pixelColor(x, y))]
    return (max(xs) - min(xs)) if xs else 0


def test_answer_label_draws_table_gridlines(qapp):
    """回答面板：线画出来、表撑满宽度、表头有底色；光板 markdown 一条线都没有。

    走 _md_div 的**生产形状**（外层 <div style=…> 把 <style> 包在里面）——
    样式块被 div 套住还生不生效，正是最容易悄悄坏掉的那一层。
    """
    wrap = '<div style="color:#1a1d2e; font-size:17px;">{}</div>'
    styled = _label_image(_md_div(TABLE, "#1a1d2e", 17))
    raw = _label_image(wrap.format(_raw_md(TABLE)))
    n_styled, n_raw = _paint(styled, LINE), _paint(raw, LINE)
    assert n_styled > 200, f"回答面板没画出网格线: {n_styled}"
    assert n_styled - n_raw > 200, (
        f"线不是样式带来的（负对照太接近）: styled={n_styled} raw={n_raw}")
    assert _x_span(styled) >= int(W * 0.9), (
        f"表格没撑满宽度（width=\"100%\" 没生效）: {_x_span(styled)} / {W}")
    assert _paint(styled, CHIP) > 300, "表头底色没画出来"


def test_records_document_draws_table_gridlines(qapp):
    """记录详情：同一段样式在 QTextDocument 那条路上同样出线（Qt 两套渲染器都认）。"""
    styled, raw = _doc_image(_md(TABLE)), _doc_image(_raw_md(TABLE))
    n_styled, n_raw = _paint(styled, LINE), _paint(raw, LINE)
    assert n_styled > 200, f"记录详情没画出网格线: {n_styled}"
    assert n_styled - n_raw > 200, (
        f"线不是样式带来的（负对照太接近）: styled={n_styled} raw={n_raw}")
