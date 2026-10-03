"""Spore 客户端入口：单例（第二实例唤醒首实例后退出）→ 登录窗口 → 主窗口。"""

import ctypes
import os
import sys
import threading

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import __version__
from .api import ApiClient
from .app_icon import app_icon
from .log import get_logger
from .login import LoginWindow, try_device_login
from .main_window import MainWindow

LOG = get_logger()

# Windows 命名管道随服务进程消亡（无残留占位）；带用户名防跨用户会话互扰
INSTANCE_NAME = f"spore-desktop-client-{os.environ.get('USERNAME', 'default')}"


def _install_excepthooks() -> None:
    """未捕获异常必须留痕——pythonw 下 stderr 无处可去，没日志就等于蒸发。"""
    def _hook(tp, val, tb):
        LOG.error("uncaught exception", exc_info=(tp, val, tb))
    sys.excepthook = _hook

    def _th_hook(args):
        LOG.error("thread %s crashed", args.thread.name,
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = _th_hook


def _wake_existing() -> None:
    """已有实例占着单例名 → 给它发「唤醒」；连接成功即够，载荷不用等回执。"""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if not sock.waitForConnected(500):
        return
    sock.write(b"wake")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()


def _on_wake(server: QLocalServer, app: QApplication) -> None:
    conn = server.nextPendingConnection()
    if conn is not None:
        conn.close()  # 载荷不读：连上本身就是「唤醒」
    target = getattr(app, "_main", None) or getattr(app, "_login", None)
    LOG.info("wake received: target=%s",
             type(target).__name__ if target is not None else "none-yet")
    if target is None:
        return  # 首实例窗口还没建好——它马上就会自己 show
    if target.isMinimized():  # 最小化也要还原，光 show/raise 不够
        target.setWindowState(target.windowState() & ~Qt.WindowMinimized)
    target.show()
    target.raise_()
    target.activateWindow()


def main() -> int:
    # 任务栏身份（否则 pythonw 的窗口可能挂到别的控制台身份下）
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spore.Desktop")
    LOG.info("Spore client v%s starting (frozen=%s)",
             __version__, getattr(sys, "frozen", False))
    app = QApplication(sys.argv)
    app.setApplicationName("Spore")
    app.setWindowIcon(app_icon())  # = MV3 扩展图标（用户 2026-10-02 拍板）
    # MV3 品牌粉 + 浅色（design-brief §0）：MV3 options/review/drawer 均为纯浅色
    # 设计，强制浅色避免深色导航配白卡的错配
    from qfluentwidgets import Theme, setTheme, setThemeColor
    setThemeColor("#ec4899")
    setTheme(Theme.LIGHT)
    _install_excepthooks()

    # ---- 单例：listen 抢到名字 = 首实例；抢不到 = 已有实例，通知它唤醒、本进程退 ----
    server = QLocalServer()
    server.newConnection.connect(lambda: _on_wake(server, app))
    if not server.listen(INSTANCE_NAME):
        LOG.info("instance started: pipe held by existing instance → wake + exit")
        _wake_existing()
        return 0
    app._instance_server = server  # noqa: SLF001 — 防 GC
    LOG.info("instance started: pipe owned")

    api = ApiClient()
    app._api = api  # noqa: SLF001 — 防 GC

    def enter_main(vo: dict):
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        login.close()
        LOG.info("entered main window (login ok)")

    # 静默登录优先（device.token 在 → 直接进主窗）
    me = try_device_login(api)
    if me is not None:
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        LOG.info("entered main window (silent login)")
        return app.exec()

    login = LoginWindow(api)
    login.loginSucceeded.connect(enter_main)
    app._login = login  # noqa: SLF001 — 单例唤醒要用
    login.show()
    LOG.info("showing login window (no valid device token)")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
