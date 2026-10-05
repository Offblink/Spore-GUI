"""MainWindow 构造回归（2026-10-03「客户端都跑不起来」）。

根因现场：eventFilter 在 FluentWindow.__init__ 期间就被 Qt 调进来
（qframeless 过滤器链），彼时 _qr_pop 未建 → AttributeError 被 shiboken
吞成 SystemError: returned NULL → 启动即崩。这里真构造 MainWindow 钉死。
"""

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from spore_client.api import ApiClient
from spore_client.main_window import MainWindow


@pytest.fixture(scope="module")
def main_win(qapp):
    # 端口 1：三个后台取数（记录页自载 ×2、/users/me）立刻拒绝，不碰真后端
    win = MainWindow(ApiClient("http://127.0.0.1:1/api"))
    for t in (win.records._task, win.records._cat_task, win._me_task):
        if t is not None:
            t.wait(3000)
    qapp.processEvents()
    yield win
    win._quitting = True          # 走真退分支：注销热键、停 capture
    win.close()


def test_main_window_constructs_despite_early_qt_events(main_win, qapp):
    # 构造本身通过 = eventFilter/resizeEvent 的构造期守卫有效（崩过就红）
    # /users/me 打不通 → 头像保持占位「?」
    assert main_win.avatar_btn.text() == "?"
    # 出生位置（2026-10-03 反馈「显示完全」）：放得下必须整窗在屏内；
    # 放不下（offscreen 测试屏只有 800×800）钳回左上角、保左上可见
    avail = qapp.primaryScreen().availableGeometry()
    geo = main_win.frameGeometry()
    if (geo.width() <= avail.width()
            and geo.height() <= avail.height()):
        assert avail.contains(geo)
    else:
        assert geo.topLeft() == avail.topLeft()


def test_tray_activation_reasons_supported(main_win):
    # PySide6 6.10 无 DoubleTrigger（改名 DoubleClick）——旧码托盘点击必炸
    main_win._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    main_win._on_tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)


def test_help_page_registered(main_win):
    # 2026-10-03 要求新增帮助页：挂进左索引（第四页）
    assert main_win.help_page.objectName() == "helpPage"
    assert main_win.stackedWidget.indexOf(main_win.help_page) >= 0


def test_persist_turn_writes_backend_id_so_next_turn_puts(main_win, monkeypatch):
    """2026-10-05 实测 bug 回归：POST 后不回写 sess.backend_id → 同一会话的
    下一个追问回合再次 POST，造出两个同名会话（一个第一次对话、
    一个两次对话一起）。第二回合必须走 PUT 更新原会话。"""
    from spore_client.answer.session import Msg, Session
    from spore_client.records import UNREAD

    sess = Session(title="SQA 范围")
    sess.messages.append(Msg(role="assistant", kind="answer", ans="B（错）"))
    posts: list = []
    puts: list = []
    monkeypatch.setattr(main_win.api, "create_article",
                        lambda body: posts.append(body) or {"id": "art-77"})
    monkeypatch.setattr(main_win.api, "update_article",
                        lambda aid, **kw: puts.append((aid, kw)) or {"id": aid})
    monkeypatch.setattr(main_win.api, "push_attachment",
                        lambda *a, **k: None)
    try:
        main_win._persist_turn_sync(sess)          # 第一回合：POST 新会话
        assert posts and not puts
        assert sess.backend_id == "art-77"         # ← 回写是本测试的核心

        main_win._persist_turn_sync(sess)          # 追问回合：PUT 原会话
        assert len(posts) == 1                     # 绝不再开新会话
        assert puts and puts[0][0] == "art-77"
    finally:
        UNREAD.discard("art-77")                   # 别把未读账带进别的测试
        t = main_win.records._task
        if t is not None:
            t.wait(3000)                           # reload 线程收尾


def test_placeholder_lands_row_then_end_puts(main_win, monkeypatch):
    """P3 回归：截图回合开局先 POST 占位行（status=answering、messages 空）——
    会话当即进记录列表；turn-end 走 PUT 换完整正文，绝不二次开新会话；
    占位回合的题图挪到 turn-end 首推（fa5b379 的 backend_id 回写链不动）。"""
    from spore_client.answer.session import Msg, Session
    from spore_client.records import UNREAD

    sess = Session(title="截图回合", image_path="C:/x/shot.png")
    sess.messages.append(Msg(role="user", kind="answer", text="", hasImage=True))
    sess.messages.append(Msg(role="assistant", kind="answer", ans="A"))
    posts: list = []
    puts: list = []
    pushes: list = []
    reloads: list = []
    monkeypatch.setattr(main_win.api, "create_article",
                        lambda body: posts.append(body) or {"id": "art-P3",
                                                            "fav": 0})
    monkeypatch.setattr(main_win.api, "update_article",
                        lambda aid, **kw: puts.append((aid, kw)) or {"id": aid})
    monkeypatch.setattr(main_win.api, "push_attachment",
                        lambda aid, p: pushes.append((aid, p)))
    monkeypatch.setattr(main_win.records, "reload",
                        lambda: reloads.append(1))
    try:
        main_win._placeholder_sync(sess)           # 开局占位
        assert posts[0]["status"] == "answering"
        assert posts[0]["messages"] == []          # 占位行不带正文
        assert sess.backend_id == "art-P3"         # 回写：turn-end 才能走 PUT
        assert main_win._placeholders[sess.id] == "art-P3"
        assert reloads                             # 列表当即刷新（P3 的核心诉求）

        main_win._persist_turn_sync(sess)          # turn-end 收编
        assert len(posts) == 1                     # 绝不再开第二条会话
        assert puts and puts[0][0] == "art-P3"
        assert puts[0][1]["messages"]              # 完整正文 PUT 进去
        assert pushes == [("art-P3", "C:/x/shot.png")]  # 题图 turn-end 首推
        assert sess.id not in main_win._placeholders
    finally:
        UNREAD.discard("art-P3")


def test_aborted_turn_drops_placeholder_row(main_win, monkeypatch):
    """P3：占位后回合中止/出错 → 维持既有语义（不落库），DELETE 占位行——
    列表绝不留一条永远「回答中」的僵尸。走 _engine_event 真路由。"""
    from spore_client.answer.session import Session

    sess = Session(title="中止回合")
    sess.backend_id = "art-Z"
    main_win._placeholders[sess.id] = "art-Z"
    deletes: list = []
    monkeypatch.setattr(main_win.api, "delete_article",
                        lambda aid: deletes.append(aid))
    monkeypatch.setattr(main_win.records, "reload", lambda: None)
    monkeypatch.setattr(main_win.engine, "session_by_id", lambda sid: sess)
    try:
        main_win._engine_event(
            {"type": "turn-end", "sid": sess.id, "aborted": True})
        assert deletes == ["art-Z"]
        assert sess.backend_id == ""
        assert sess.id not in main_win._placeholders
    finally:
        main_win._placeholders.pop(sess.id, None)


def test_placeholder_never_created_after_turn_finished(main_win, monkeypatch):
    """极快失败竞态：回合已收尾才轮到占位任务执行 → 终态守卫跳过，
    不制造没人收尾的占位行（否则 turn-end 已过、没人会 DELETE 它）。"""
    from spore_client.answer.session import Session

    sess = Session()
    sess.status = "done"
    posts: list = []
    monkeypatch.setattr(main_win.api, "create_article",
                        lambda body: posts.append(body) or {"id": "x"})
    main_win._placeholder_sync(sess)
    assert posts == []
    assert sess.backend_id == ""
