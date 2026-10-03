"""记录页渲染与行交互（2026-10-03 §8 回归 + 同批反馈）。

钉住的用户可见 bug/反馈修复：
- 检索小票 ⌕ 与文本被 markdown 的 <p> 拆成两行（§8-1 分行现场）；
- label 设 TextSelectableByMouse 吞掉按下事件不冒泡：点会话标题开不了会话、
  点科目名不触发展开（§8-4「点偏左边才能选中」）；
- 长标题把行尾 ✎× 挤出行外（label minimumSizeHint = 全文宽）；
- 移入科目 = 模态框单选（不是弹出菜单），右栏「接着问」带会话 id 发出；
- 开机自动加载 + 初始选中「全部」+ 检索按钮去掉、键入即时进第二形态
  （只平铺命中会话、不摆科目）；
- attachmentPath 恒空（push-attachment 不回写行）时题图回退消息 imagePath；
- 追问小节标灰字在用户追问气泡上方，截屏补充不带标。
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
    article_shot,
)

SIDEBAR_ROW = 254   # 280 侧栏 − 树区左右边距


class _FakeApi:
    """记录页 ctor 开机自载：假 api 返回空表，两个后台取数不碰真后端。"""

    def __init__(self):
        self.article_calls = 0
        self.cat_calls = 0

    def articles(self, **kw):
        self.article_calls += 1
        return {"list": []}

    def category_tree(self, *a, **kw):
        self.cat_calls += 1
        return []

    def resolve_attachment(self, raw):
        from pathlib import Path
        return str(Path(raw)) if raw and Path(raw).is_file() else ""


def _pane(qapp) -> RecordsPane:
    """构造记录页并等开机自载落定（跨线程信号队列化，wait 后还要泵事件）。"""
    api = _FakeApi()
    pane = RecordsPane(api)
    pane._fake_api = api
    for task in (pane._task, pane._cat_task):
        if task is not None:
            task.wait(3000)
    qapp.processEvents()
    return pane


def _answer_msg(**kw):
    m = {"role": "assistant", "kind": "answer", "ans": "A（对）"}
    m.update(kw)
    return m


def _widget_kinds(box) -> list[str]:
    out = []
    for i in range(box.count()):
        w = box.itemAt(i).widget()
        if w is not None:
            out.append(type(w).__name__)
    return out


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
    for b in (row.rename_btn, row.del_btn):   # 科目行只有 ✎ ×（⇄ 已移除）
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
    pane = _pane(qapp)
    pane.current_id = "a1"
    got: list = []
    pane.followupRequested.connect(lambda a, t: got.append((a, t)))
    pane.followup_input.setText("  再讲讲这题  ")
    pane._send_followup()
    assert got == [("a1", "再讲讲这题")]     # 原文去空白
    pane.followup_input.setText("   ")
    pane._send_followup()
    assert len(got) == 1                   # 空文本不发、输入框不自清（主窗判定后清）


# ---------- 开机自动加载 / 初始选中「全部」 / 搜索按钮移除 ----------

def test_startup_autoload_and_default_segment(qapp):
    pane = _pane(qapp)
    assert pane._fake_api.article_calls >= 1   # 开机即自动拉会话列表
    assert pane._fake_api.cat_calls >= 1       # 开机即自动拉分类树
    assert "#ffffff" in pane.seg_all.styleSheet()    # 初始选中「全部」
    assert "#ffffff" not in pane.seg_fav.styleSheet()
    assert pane.search.searchButton.isHidden()       # 搜索按钮已去掉


# ---------- 检索第二形态：只平铺命中会话、不摆科目（即时过滤） ----------

def test_keyword_enters_flat_second_form(qapp):
    pane = _pane(qapp)
    pane._cats = [{"id": "c1", "name": "科目甲", "depth": 0, "status": 1}]
    pane.rows = [
        {"id": "a1", "title": "Kestrel 并发", "categoryId": "c1"},
        {"id": "a2", "title": "SQA 计划", "categoryId": ""},
    ]
    pane.search.setText("kestrel")   # 即时过滤：textChanged → _do_search
    kinds = _widget_kinds(pane._tree_box)
    assert "CatRow" not in kinds              # 第二形态不摆科目
    assert kinds.count("SessionCard") == 1    # 只剩命中那条


# ---------- 题图：attachmentPath 恒空时回退消息 imagePath ----------

def test_article_shot_falls_back_to_message_image(tmp_path):
    img = tmp_path / "stored.jpg"
    img.write_bytes(b"a")
    msg_img = tmp_path / "msg.jpg"
    msg_img.write_bytes(b"b")
    api = ApiClient()   # 绝对路径解析不联网
    # push-attachment 不回写 article 行 → attachmentPath 空，从最后带图消息找
    art = {"attachmentPath": "", "messages": [
        {"role": "user", "kind": "answer", "hasImage": True,
         "imagePath": str(msg_img)},
        {"role": "assistant", "kind": "answer", "ans": "A"}]}
    assert article_shot(art, api) == str(msg_img)
    art["attachmentPath"] = str(img)
    assert article_shot(art, api) == str(img)     # attachmentPath 优先
    assert article_shot({"attachmentPath": "", "messages": []}, api) == ""


# ---------- 追问小节标在用户追问气泡上方 ----------

def test_followup_label_above_user_bubble_in_history_html():
    html = _detail_html({"messages": [
        {"role": "user", "kind": "answer", "text": "题目截图补充"},
        {"role": "user", "kind": "chat", "text": "再讲讲"},
        {"role": "assistant", "kind": "chat", "text": "好的。",
         "tools": ["检索 x"]},
    ]})
    assert html.count(">追问<") == 1           # 截屏补充（answer）不带标
    assert html.index("追问") < html.index("再讲讲")


# ---------- 🚫 中止按钮（反馈：只有发送没有禁用按钮） ----------

def test_cancel_button_emits_signal(qapp):
    pane = _pane(qapp)
    assert pane.cancel_btn.text() == "🚫"    # 按钮在行内（不只是信号存在）
    got: list = []
    pane.cancelRequested.connect(lambda: got.append(True))
    pane._emit_cancel()
    assert got == [True]


# ---------- 删除会话连带删题图（2026-10-03 反馈） ----------

def test_purge_deletes_storage_photo_and_spares_foreign_paths(tmp_path):
    from spore_client.records import purge_article_files

    store = tmp_path / "store"
    store.mkdir()
    photo = store / "art-1.jpg"
    photo.write_bytes(b"x")
    foreign = tmp_path / "foreign.jpg"
    foreign.write_bytes(b"y")

    class _Api:
        def storage_dir(self):
            return str(store)

    art = {"id": "art-1",
           "messages": [{"role": "user", "imagePath": str(foreign)}]}
    purge_article_files(art, _Api())
    assert not photo.exists()        # 题库附件 <id>.* 已删
    assert foreign.exists()          # 截图目录之外的路径绝不碰（防野路径）
