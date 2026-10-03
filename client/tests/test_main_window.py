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
