"""Spore 客户端入口：单例（第二实例唤醒首实例后退出）→ 打开本机数据库 → 主窗口。

2026-11-13 起不再有后端进程、账号与同步：数据在 ``%LOCALAPPDATA%\\Spore\\spore.db``，
由 :class:`spore_client.store.Store` 直接读写。
"""

import ctypes
import os
import sys
import threading

from PySide6.QtCore import Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__, theme
from .app_icon import app_icon
from .instance_lock import acquire_instance_lock
from .log import get_logger
from .main_window import MainWindow
from .store import Store

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
    target = getattr(app, "_main", None)
    LOG.info("wake received: target=%s",
             type(target).__name__ if target is not None else "none-yet")
    if target is None:
        return  # 窗口还没建好——它马上就会自己 show
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
    app.setWindowIcon(app_icon())  # 孢子球（与 Spore-Mobile 同一个图标）
    # 外观：档位读 ui_settings.theme（system|light|dark），系统变化时自动跟随
    theme.apply()
    theme.follow_system()
    _install_excepthooks()

    # ---- 单例：内核互斥体才是判据；管子降级成唤醒通道 ----
    lock = acquire_instance_lock()
    if lock is None:
        LOG.info("instance started: pipe held by existing instance → wake + exit")
        _wake_existing()
        return 0
    app._instance_lock = lock  # noqa: SLF001 — 句柄不放，锁就不放（进程退出内核自动释放）
    server = QLocalServer()
    server.newConnection.connect(lambda: _on_wake(server, app))
    if not server.listen(INSTANCE_NAME):
        # 单例不受影响（锁在手），只是唤醒通道废了
        LOG.error("instance pipe listen failed: %s", server.errorString())
    app._instance_server = server  # noqa: SLF001 — 防 GC
    LOG.info("instance started: pipe owned")

    # ---- 本机数据库：打不开就没法用，明确告知而不是静默空白 ----
    try:
        store = Store()
    except Exception as e:  # noqa: BLE001 — 损坏/权限/占用都要给人话
        LOG.error("store open failed: %s", e)
        QMessageBox.critical(
            None, "Spore",
            f"数据库打不开，Spore 无法启动。\n\n{store_path_hint()}\n\n{e}")
        return 1
    app._store = store  # noqa: SLF001 — 防 GC

    win = MainWindow(store)
    win.show()
    app._main = win  # noqa: SLF001
    LOG.info("entered main window")
    return app.exec()


def store_path_hint() -> str:
    from .store import DEFAULT_DB
    return f"数据库位置：{DEFAULT_DB}"


if __name__ == "__main__":
    raise SystemExit(main())
