"""记录页渲染与行交互（2026-10-03 §8 回归）。

钉住两处用户可见 bug 的修复：
- 检索小票 ⌕ 与文本被 markdown 的 <p> 拆成两行（§8-1 用户贴的分行现场）；
- label 设 TextSelectableByMouse 吞掉按下事件不冒泡：点会话标题开不了会话、
  点科目名不触发展开（§8-4「点偏左边才能选中」）。
"""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from spore_client.records import CatRow, SessionCard, _detail_html


def _answer_msg(**kw):
    m = {"role": "assistant", "kind": "answer", "ans": "A（对）"}
    m.update(kw)
    return m


def test_answer_tool_ticket_stays_on_one_line():
    html = _detail_html(
        {"messages": [_answer_msg(tools=["检索 Kestrel async 支持"])]})
    # 旧代码：⌕ <p>检索 …</p> → 图标与文本分两行
    assert "⌕ 检索 Kestrel async 支持" in html
    assert "⌕ <p>" not in html


def test_chat_tool_ticket_stays_on_one_line():
    html = _detail_html(
        {"messages": [{"role": "assistant", "kind": "chat", "text": "在。",
                       "tools": ["读取 https://example.com/k"]}]})
    assert "⌕ 读取 https://example.com/k" in html
    assert "⌕ <p>" not in html


def test_click_on_title_opens_session(qapp):
    card = SessionCard({"id": "a1", "title": "SQA 范围"})
    got: list = []
    card.opened.connect(got.append)
    QTest.mouseClick(card.title_lbl, Qt.LeftButton)
    assert got == ["a1"]   # 标题不可选中 → 事件冒泡到 frame（§8-4）


def test_click_on_cat_name_toggles_expand(qapp):
    row = CatRow("c1", "软件测试", 0)
    got: list = []
    row.selected.connect(lambda cid, name: got.append(cid))
    QTest.mouseClick(row.name_lbl, Qt.LeftButton)
    assert got == ["c1"]   # 科目名同样不可选中（§8-4 同类）
