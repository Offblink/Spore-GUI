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

from PySide6.QtCore import QPoint, Qt
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


# ---------- 协议标记转义（「ok」不许被富文本当标签吃掉） ----------

def test_protocol_markers_survive_rendering():
    html = _detail_html({"messages": [_answer_msg(
        verifyPending=True,
        verifyNote="初答自评「确定」（<<ok>> 守卫），已跳过联网核实。")]})
    assert "&lt;&lt;ok" in html        # 转义后可视文本仍是 <<ok>>
    assert "<ok>" not in html          # 旧现场：被当标签吞掉、「ok」二字消失


def test_pending_verify_shows_real_button(qapp):
    """富文本画不出圆角 → 按钮改真 QPushButton 挂消息流下方（2026-10-03）。"""
    pane = _pane(qapp)
    art = {"id": "a1", "title": "T", "messages": [
        _answer_msg(verifyPending=True, verifyNote="点它开始")]}
    pane.current_id = "a1"
    pane.rows = [art]
    pane._render_detail(art)
    assert not pane.verify_btn.isHidden()          # 待核实 → 按钮亮
    got: list = []
    pane.verifyRequested.connect(got.append)
    pane._emit_verify()
    assert got == ["a1"]                           # 点按钮 → 带会话 id 发出
    done = {"id": "a1", "title": "T", "messages": [
        _answer_msg(verifyRan=True, verifyVerdict="OK")]}
    pane._render_detail(done)
    assert pane.verify_btn.isHidden()              # 已核实 → 按钮灭


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


# ---------- 涂抹多选（2026-10-05 照 mobile record.js：长按进 / 单选框涂抹 / 批量） ----------

def _multi_pane(qapp, rows: int = 5, size: tuple[int, int] = (1000, 800)) -> RecordsPane:
    """N 条会话 + 真 show（涂抹按全局几何命中行，offscreen 也要有布局）。"""
    pane = _pane(qapp)
    pane.rows = [
        {"id": f"s{i}", "title": f"会话{i}", "fav": 0, "categoryId": "",
         "updateTime": "2026-10-05 10:00:00", "status": "done",
         "messages": []}
        for i in range(rows)
    ]
    pane._render_tree()
    pane.resize(*size)
    pane.show()
    for _ in range(3):
        qapp.processEvents()
    assert len(pane._session_cards) == rows
    return pane


def test_batch_select_button_enters_mode_and_toggles(qapp):
    pane = _multi_pane(qapp)
    assert not pane._batch_bar.isVisible()

    pane.sel_btn.click()                      # 入口=「批量选择」按钮（2026-10-05 拍板）
    assert pane._selecting
    assert pane.sel_btn.text() == "退出选择"
    assert pane._batch_bar.isVisible()
    assert pane._multi == set()               # 0 选起手，不自动勾
    assert pane._sel_label.text() == "已选 0 项"
    assert not pane.batch_fav.isEnabled()     # 0 选 → 批量按钮禁用

    # 模式里点卡片 = 勾选，且绝不打开会话
    c3 = pane._session_cards[3]
    got: list = []
    c3.opened.connect(lambda i: got.append(i))
    QTest.mouseClick(c3, Qt.LeftButton, pos=c3.rect().center())
    assert pane._multi == {"s3"}
    assert pane.batch_fav.isEnabled()
    assert got == []

    pane.sel_btn.click()                      # 按钮再点 = 退出
    assert not pane._selecting
    assert pane.sel_btn.text() == "批量选择"
    assert not pane._batch_bar.isVisible()
    assert pane._multi == set()

    pane.sel_btn.click()                      # 重进 → 换筛选（收藏）退模式
    assert pane._selecting
    pane._set_seg(True)
    assert not pane._selecting


def test_paint_range_selects_and_reverses_on_backtrack(qapp):
    pane = _multi_pane(qapp)
    pane._set_selecting(True)
    cards = pane._session_cards
    c0 = cards[0]
    ck = c0.ck.pos() + QPoint(8, 8)

    QTest.mousePress(c0, Qt.LeftButton, pos=ck)          # 单选框起笔
    assert pane._paint is not None
    QTest.mouseMove(c0, c0.mapFromGlobal(
        cards[2].mapToGlobal(cards[2].rect().center())))  # 笔尖拖到 s2（真全局坐标）
    assert pane._multi == {"s0", "s1", "s2"}

    QTest.mouseMove(c0, c0.mapFromGlobal(
        cards[1].mapToGlobal(cards[1].rect().center())))  # 折返 → 换向反选新段
    assert pane._multi == {"s0"}                         # s1/s2 反选；s0 在段外

    QTest.mouseMove(c0, c0.mapFromGlobal(
        cards[3].mapToGlobal(cards[3].rect().center())))  # 再折返 → 段 1..3 全选
    assert pane._multi == {"s0", "s1", "s2", "s3"}

    QTest.mouseRelease(c0, Qt.LeftButton, pos=ck)        # 收笔：不加不减
    assert pane._multi == {"s0", "s1", "s2", "s3"}
    assert pane._paint is None

    # 单选框轻点（没动）= 就地翻选（mobile endStroke 同款）
    c4 = cards[4]
    p4 = c4.ck.pos() + QPoint(8, 8)
    QTest.mousePress(c4, Qt.LeftButton, pos=p4)
    assert pane._paint is not None
    QTest.mouseRelease(c4, Qt.LeftButton, pos=p4)
    assert pane._multi == {"s0", "s1", "s2", "s3", "s4"}


def test_batch_fav_flips_selected_rows(qapp):
    pane = _multi_pane(qapp)
    calls: list = []
    pane.api.update_article = lambda aid, **kw: calls.append((aid, kw))
    pane._set_selecting(True)
    pane._set_checked(pane._session_cards[0], True)
    pane._set_checked(pane._session_cards[2], True)

    pane._batch_fav()
    assert calls == [("s0", {"fav": 1}), ("s2", {"fav": 1})]
    assert pane.rows[0]["fav"] == 1 and pane.rows[2]["fav"] == 1

    calls.clear()
    pane._batch_fav()                    # 这次选中的全已收藏 → 统一取消
    assert calls == [("s0", {"fav": 0}), ("s2", {"fav": 0})]


def test_batch_delete_confirms_count_and_exits_mode(qapp, monkeypatch):
    pane = _multi_pane(qapp)
    deleted: list = []
    pane.api.delete_article = lambda aid: deleted.append(aid)
    seen: dict = {}

    class _OkBox:
        def __init__(self, title, text, parent=None):
            seen["title"] = title
            seen["text"] = text

        def exec(self):
            return True

    monkeypatch.setattr("spore_client.records.MessageBox", _OkBox)
    monkeypatch.setattr("spore_client.records.purge_article_files",
                        lambda art, api: None)
    pane._set_selecting(True)
    pane._set_checked(pane._session_cards[0], True)
    pane._set_checked(pane._session_cards[1], True)

    pane._batch_delete()
    assert deleted == ["s0", "s1"]
    assert "2" in seen["text"]           # 确认框带条数
    assert not pane._selecting           # 删完退多选（mobile 同款）
    assert pane._multi == set()
    if pane._task is not None:
        pane._task.wait(3000)            # reload 线程收尾，别在测试尾部销毁


def test_unread_dot_marks_and_clears(qapp):
    from spore_client.records import UNREAD

    pane = _multi_pane(qapp)
    try:
        pane.mark_unread("s2")
        assert "s2" in UNREAD
        assert pane._session_cards[2].dot.isVisible()
        pane._select_session("s2")        # 点开 = 已读
        assert "s2" not in UNREAD
        assert not pane._session_cards[2].dot.isVisible()

        pane.current_id = "s3"            # 右栏正看的那场不点红点
        pane.mark_unread("s3")
        assert "s3" not in UNREAD
    finally:
        UNREAD.discard("s2")
        UNREAD.discard("s3")


# ---------- P1：涂抹贴近视口上下缘自动滚动会话树（2026-10-05 用户点名） ----------

def test_paint_auto_scroll_follows_viewport_edges(qapp):
    from spore_client.records import PAINT_SCROLL_BAND

    pane = _multi_pane(qapp, rows=60, size=(1000, 640))   # 60 行 → 内容溢出
    pane._set_selecting(True)
    for _ in range(3):
        qapp.processEvents()               # 底栏露出后布局才落定
    vp = pane._tree_scroll.viewport()
    sb = pane._tree_scroll.verticalScrollBar()
    assert sb.maximum() > 0 and sb.value() == 0
    assert vp.height() > 2 * PAINT_SCROLL_BAND + 40   # 中部要留得出非边缘档

    c0 = pane._session_cards[0]
    ck = c0.ck.pos() + QPoint(8, 8)         # 单选框起笔（真全局由 Qt 映射）
    QTest.mousePress(c0, Qt.LeftButton, pos=ck)
    assert pane._paint is not None

    def move_to(g):                         # 取点一律 mapToGlobal 真全局（§5.1）
        QTest.mouseMove(c0, c0.mapFromGlobal(g))

    # 1) 笔尖进视口下缘带 → 向下连续滚
    move_to(vp.mapToGlobal(QPoint(0, vp.height() - 8)))
    QTest.qWait(250)
    assert sb.value() > 0

    # 2) 回到中部（非边缘档）→ 立即停，数值定住
    move_to(vp.mapToGlobal(QPoint(0, vp.height() // 2)))
    QTest.qWait(80)
    assert not pane._scroll_timer.isActive()
    mid = sb.value()
    QTest.qWait(200)
    assert sb.value() == mid

    # 3) 笔尖进视口上缘带 → 向上滚
    move_to(vp.mapToGlobal(QPoint(0, 8)))
    QTest.qWait(250)
    assert sb.value() < mid

    # 4) 收笔 → 滚动必停、数值定格
    QTest.mouseRelease(c0, Qt.LeftButton, pos=ck)
    assert pane._paint is None
    assert not pane._scroll_timer.isActive()
    final = sb.value()
    QTest.qWait(200)
    assert sb.value() == final
