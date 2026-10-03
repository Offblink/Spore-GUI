"""记录页渲染与行交互（2026-10-03 §8 回归 + 同批反馈）。

钉住的用户可见 bug 修复：
- 检索小票 ⌕ 与文本被 markdown 的 <p> 拆成两行（§8-1 分行现场）；
- label 设 TextSelectableByMouse 吞掉按下事件不冒泡：点会话标题开不了会话、
  点科目名不触发展开（§8-4「点偏左边才能选中」）；
- 长标题把行尾 ✎⇄× 挤出行外（label minimumSizeHint = 全文宽）；
- 移入科目 = 模态框单选（不是弹出菜单），右栏「接着问」带会话 id 发出。
"""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from spore_client.api import ApiClient
from spore_client.records import (
    CatRow,
    RecordsPane,
    SessionCard,
    _detail_html,
    _MoveDialog,
)

SIDEBAR_ROW = 254   # 280 侧栏 − 树区左右边距


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


# ---------- 长名字不许把行尾按钮挤出行外（2026-10-03 用户反馈） ----------

def test_long_title_keeps_all_buttons_inside(qapp):
    card = SessionCard({"id": "a1", "title": "很长的会话标题" * 30})
    card.setFixedWidth(SIDEBAR_ROW)
    card.layout().activate()
    for b in (card.star, card.rename_btn, card.move_btn, card.del_btn):
        assert b.x() + b.width() <= card.width(), b.text()


def test_long_cat_name_keeps_buttons_inside(qapp):
    row = CatRow("c1", "很长的科目名称" * 30, 0)
    row.setFixedWidth(SIDEBAR_ROW)
    row.layout().activate()
    for b in (row.rename_btn, row.move_btn, row.del_btn):
        assert b.x() + b.width() <= row.width(), b.text()


# ---------- 移入科目模态框（用户点名：不要弹出菜单） ----------

def test_move_dialog_presets_current_and_reports_choice(qapp):
    cats = [{"id": "c1", "name": "软件测试", "depth": 0},
            {"id": "c2", "name": "嵌套科目", "depth": 1}]
    dlg = _MoveDialog(cats, "c2")
    assert dlg._selected() == "c2"        # 预选当前归属
    dlg._radios[0].setChecked(True)       # 切到「未分组」（同父自动互斥）
    assert dlg._selected() == ""
    stale = _MoveDialog(cats, "gone-id")
    assert stale._selected() == ""        # 归属科目已被删 → 落回未分组


# ---------- 右栏「接着问」发会话 id + 原文 ----------

def test_followup_input_emits_current_session(qapp):
    pane = RecordsPane(ApiClient())
    pane.current_id = "a1"
    got: list = []
    pane.followupRequested.connect(lambda a, t: got.append((a, t)))
    pane.followup_input.setText("  再讲讲这题  ")
    pane._send_followup()
    assert got == [("a1", "再讲讲这题")]     # 原文去空白
    pane.followup_input.setText("   ")
    pane._send_followup()
    assert len(got) == 1                   # 空文本不发、输入框不自清（主窗判定后清）
