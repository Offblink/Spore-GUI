"""place_near 纯函数 + 追问小节标位置（04 §四 与 2026-10-03 反馈）。

浮窗定位错 → 用户找不到回答面板（钉死贴选区与两条钳位规则）；
chat-start 的「追问」灰字必须画在用户追问气泡**上方**（用户点名的顺序，
旧实现是先检索小票才见「追问」）。
"""

from PySide6.QtWidgets import QLabel

from spore_client.answer.settings import LlmSettings
from spore_client.answer_window import (
    AnswerWindow,
    _md_html,
    _SessionRow,
    place_near,
)

PANEL = (460, 560)        # AnswerWindow 默认尺寸
SCREEN = (1493, 933)      # 本机逻辑分辨率（150% 缩放）
MARGIN = 12


def test_places_right_of_selection_when_room():
    x, y = place_near((100, 100, 300, 200), *PANEL, *SCREEN)
    assert x == 100 + 300 + MARGIN          # 选区右缘外 12
    assert x + PANEL[0] <= SCREEN[0]        # 不越出屏幕右缘


def test_falls_back_left_when_right_side_full():
    # 选区贴屏幕右缘 → 右侧放不下，翻到左侧
    x, y = place_near((1100, 100, 380, 200), *PANEL, *SCREEN)
    assert x + PANEL[0] == 1100 - MARGIN    # 紧贴选区左缘外 12
    assert x >= MARGIN


def test_clamps_left_when_selection_spans_screen():
    # 选区横贯全屏：左右都放不下 → 钳回屏幕左缘（不许负坐标）
    x, y = place_near((100, 100, 1200, 200), *PANEL, *SCREEN)
    assert x == MARGIN


def test_vertical_center_clamped_to_top():
    # 选区贴屏幕上缘 → 纵向算出负 y → 钳回上缘
    x, y = place_near((100, 100, 300, 200), *PANEL, *SCREEN)
    assert y == MARGIN


def test_vertical_center_clamped_to_bottom():
    # 选区贴屏幕下缘 → 纵向超界 → 钳回下缘
    x, y = place_near((100, 800, 300, 200), *PANEL, *SCREEN)
    assert y == SCREEN[1] - PANEL[1] - MARGIN


def test_panel_sits_fully_on_screen():
    for sel in [(0, 0, 60, 40), (1433, 893, 60, 40), (700, 450, 400, 300)]:
        x, y = place_near(sel, *PANEL, *SCREEN)
        assert 0 <= x <= SCREEN[0] - PANEL[0]
        assert 0 <= y <= SCREEN[1] - PANEL[1]


# ---------- 渐显/渐隐（2026-10-03 反馈：整窗 α 动画） ----------

def test_show_and_hide_fade_settle_at_full_and_hidden(qapp):
    from PySide6.QtTest import QTest

    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win.show_fade()
    QTest.qWait(400)                      # 180ms 动画 + 余量
    assert win.isVisible()
    assert abs(win.windowOpacity() - 1.0) < 1e-6
    win.hide_fade()
    QTest.qWait(400)
    assert not win.isVisible()            # 淡出后才收窗
    assert abs(win.windowOpacity() - 1.0) < 1e-6   # α 复位，下次从 0 淡入


# ---------- 圆角描边（2026-10-03 反馈：边框要与背景区分） ----------

def test_panel_stylesheet_has_rounded_visible_border(qapp):
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    sheet = win.styleSheet()
    assert "border-radius" in sheet
    assert "border:1.5px solid" in sheet


def test_md_html_escapes_protocol_markers():
    html = _md_html("（<<ok>> 守卫）")
    assert "&lt;&lt;ok" in html
    assert "<ok>" not in html


def test_history_verify_chip_priority_matches_records(qapp):
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    # 跑完核实却残留 pending 标记（2026-10-03 图1 现场）→ 显示结果，不显示 ⏳
    win._add_history_msg({"role": "assistant", "kind": "answer", "ans": "A",
                          "verifyPending": True, "verifyRan": True,
                          "verifyVerdict": "OK", "verifyNote": "与初答一致"})
    blk = win._blocks[-1]
    assert blk["chip"].text() == "✅ 与初答一致"
    assert blk["verify_btn"].isHidden()          # 结果态不给核实按钮


def test_verify_button_sits_below_verify_card(qapp):
    # 2026-10-03 反馈：按钮在核实卡片**下方**（旧序在上方）
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win.on_event({"type": "answer-start", "idx": 1})
    blk = win._blocks[-1]
    lay = blk["frame"].layout()          # 卡片/按钮在块内布局，不在窗体布局
    frame_idx = lay.indexOf(blk["verify_frame"])
    btn_idx = lay.indexOf(blk["verify_btn"])
    assert 0 <= frame_idx < btn_idx


def test_session_list_stack_newest_on_top(qapp):
    # 2026-10-03 反馈：💬 列表像栈——最新会话在顶部、旧的往下堆
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win._render_sessions([
        {"id": "old", "title": "旧", "updateTime": "2026-10-01 10:00:00"},
        {"id": "new", "title": "新", "updateTime": "2026-10-03 10:00:00"},
    ])
    ids = []
    for i in range(win._pop_box.count()):
        w = win._pop_box.itemAt(i).widget()
        if isinstance(w, _SessionRow):
            ids.append(w._art.get("id"))
    assert ids == ["new", "old"]


# ---------- 回答面板位置固定（2026-10-05 用户点名：默认开、记住位置） ----------

def test_panel_fixed_position_defaults_on_and_reuses(qapp, tmp_path, monkeypatch):
    from spore_client import settings_store

    monkeypatch.setattr(settings_store, "PATH", tmp_path / "ui.json")
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    assert win._fixed_pos() is None          # 默认开、但还没记住 → 走选区附近

    settings_store.write({"panelFixed": True, "panelPos": [40, 50]})
    assert win._fixed_pos() == (40, 50)      # 固定开 → 记住的坐标生效

    settings_store.write({"panelFixed": False, "panelPos": [40, 50]})
    assert win._fixed_pos() is None          # 关掉 → 回到旧行为（选区附近）

    settings_store.write({"panelFixed": True, "panelPos": [99999, 99999]})
    assert win._fixed_pos() is None          # 坐标不在任何屏上 → 回落


# ---------- 并行回合事件过滤（2026-10-05：只认面板正看着的会话） ----------

def test_events_from_other_sessions_are_filtered(qapp):
    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win._sess_id = "cur"
    win.on_event({"type": "title", "title": "别场的", "sid": "other"})
    assert win.title.text() == "Spore"       # 后台会话的事件不许动面板
    win.on_event({"type": "title", "title": "本场的", "sid": "cur"})
    assert win.title.text() == "本场的"


# ---------- 💬 列表全量翻页（2026-10-05 用户点名「不要限制」） ----------

def test_session_list_fetches_all_pages(qapp):
    from spore_client.answer_window import _SessionsTask

    class _PagedApi:
        def articles(self, page=1, size=100, **kw):
            pages = {1: [{"id": str(i)} for i in range(200)],
                     2: [{"id": str(i)} for i in range(200, 203)]}
            return {"list": pages.get(page, [])}

    got: list = []
    t = _SessionsTask(_PagedApi())
    t.ok.connect(got.append)
    t.run()                                   # 直接跑（同线程信号直达）
    assert len(got) == 1 and len(got[0]) == 203   # 200/页翻到短页为止

    class _BrokenApi:   # 后端不翻页（每页同一批）→ 幂等集断路，不无限翻
        def articles(self, page=1, size=100, **kw):
            return {"list": [{"id": str(i)} for i in range(200)]}

    got2: list = []
    t2 = _SessionsTask(_BrokenApi())
    t2.ok.connect(got2.append)
    t2.run()
    assert len(got2[0]) == 200


def test_session_rows_show_unread_dot_and_clear_on_open(qapp):
    from spore_client.records import UNREAD

    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    UNREAD.add("old")
    try:
        win._render_sessions([
            {"id": "old", "title": "旧", "updateTime": "2026-10-01 10:00:00"},
            {"id": "new", "title": "新", "updateTime": "2026-10-03 10:00:00"},
        ])
        rows = [win._pop_box.itemAt(i).widget()
                for i in range(win._pop_box.count())]
        rows = [r for r in rows if isinstance(r, _SessionRow)]
        # 栈序：最新在顶（new），old 在第二 —— 点挂在 old 上
        assert rows[0].dot.isHidden()           # 没在跑的会话不带点
        assert not rows[1].dot.isHidden()       # 后台完成的会话带红点
        win._open_from_list({"id": "old"})
        assert "old" not in UNREAD              # 看过了：未读账消掉
    finally:
        UNREAD.discard("old")


# ---------- 追问小节标位置（2026-10-03 反馈） ----------

def test_chat_start_puts_followup_label_above_user_bubble(qapp):
    from PySide6.QtWidgets import QFrame

    win = AnswerWindow(LlmSettings(api_key="sk-test"))
    win.on_event({"type": "chat-start", "idx": 1, "text": "在吗"})
    items = [win._blocks_box.itemAt(i).widget()
             for i in range(win._blocks_box.count())]
    sec_idx = next(i for i, w in enumerate(items)
                   if isinstance(w, QLabel) and w.text() == "追问")
    bubble_idx = next(i for i, w in enumerate(items)
                      if isinstance(w, QFrame)
                      and w.objectName() == "userBubble")
    assert sec_idx < bubble_idx            # 灰字小节标在用户追问气泡上方
    user_texts = [b["user_lbl"].text() for b in win._blocks
                  if b["kind"] == "user" and b["user_lbl"] is not None]
    assert "在吗" in user_texts
