"""Spore 客户端入口：单例（第二实例唤醒首实例后退出）→ 起后端 → 登录窗口 → 主窗口。"""

import ctypes
import os
import sys
import threading
import time

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from . import __version__
from .api import ApiClient
from .app_icon import app_icon
from .backend import BackendError, EmbeddedBackend
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


BACKEND_START_TIMEOUT = 60.0  # 旧 bat 同款上限；Spring 冷启动实测约 6 秒


def _wait_backend(backend: EmbeddedBackend,
                  timeout: float = BACKEND_START_TIMEOUT) -> bool:
    """边泵 Qt 事件边等端口就绪，返回是否就绪。

    直接阻塞 = 「双击了没反应」；给个进度小窗，界面照常响应。
    """
    from qfluentwidgets import IndeterminateProgressBar, StrongBodyLabel

    win = QWidget(None, Qt.Window)
    win.setWindowTitle("Spore")
    win.setWindowIcon(app_icon())
    box = QVBoxLayout(win)
    box.setContentsMargins(30, 26, 30, 24)
    box.setSpacing(16)
    box.addWidget(StrongBodyLabel("正在启动后端服务…"))
    box.addWidget(IndeterminateProgressBar(win, start=True))
    win.resize(360, 118)
    win.show()
    win.raise_()
    win.activateWindow()

    loop = QEventLoop()
    state = {"ok": False}
    deadline = time.monotonic() + timeout

    def tick():
        if backend.ready():
            state["ok"] = True
            loop.quit()
        elif not backend.alive or time.monotonic() >= deadline:
            loop.quit()  # 进程秒退 / 等满超时 → 调用方报错

    timer = QTimer(win)
    timer.setInterval(200)
    timer.timeout.connect(tick)
    timer.start()
    tick()  # 理论上刚起进程不会就绪，但别为必然的等待赌一把
    if not state["ok"]:
        loop.exec()
    timer.stop()
    win.close()
    return state["ok"]


def _ensure_backend(app: QApplication) -> str | None:
    """起后端（或确认外部后端在跑）。返回 None = 就绪；否则是给登录页看的一句话原因。

    起不来**不弹框、不退出**——照样进登录窗，把原因写进状态栏：发行包里单独跑
    `Spore-<ver>-win64.exe`（那个本来就不带 jar）也得能打开看说明，而不是弹个红叉
    就自杀（2026-10-03 打包自检实测：dist 里没 jar，弹框 + 退出直接让构建断言失败）。
    """
    backend = EmbeddedBackend()
    app._backend = backend  # noqa: SLF001 — 防 GC
    app.aboutToQuit.connect(backend.stop)  # 关客户端 = 停自己起的那个后端
    try:
        spawned = backend.start_if_needed()
    except BackendError as e:
        LOG.error("backend start refused: %s", e)
        return str(e)
    if not spawned:
        return None  # 外部后端已在 8080：只用不接管（退出时也不去收它）
    if _wait_backend(backend):
        LOG.info("backend ready at %s:%s", backend.host, backend.port)
        return None
    if backend.alive:
        reason = (f"后端 {BACKEND_START_TIMEOUT:.0f} 秒内没有监听 "
                  f"{backend.host}:{backend.port}（详见 logs\\backend-console.log）")
        backend.stop()  # 卡在半路的进程别留成孤儿
    else:
        reason = "后端进程启动后立刻退出了（详见 logs\\backend-console.log）"
    LOG.error("backend failed: %s | tail: %s", reason,
              backend.tail_console().replace("\n", " | "))
    return reason


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

    # ---- 后端：随客户端起（无命令行窗口），退出随客户端停 ----
    problem = _ensure_backend(app)

    def enter_main(vo: dict):
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        login.close()
        LOG.info("entered main window (login ok)")

    # 静默登录优先（device.token 在 → 直接进主窗）；后端不通就别白等 15 秒超时
    me = try_device_login(api) if problem is None else None
    if me is not None:
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        LOG.info("entered main window (silent login)")
        return app.exec()

    login = LoginWindow(api, startup_note=problem)
    login.loginSucceeded.connect(enter_main)
    app._login = login  # noqa: SLF001 — 单例唤醒要用
    login.show()
    LOG.info("showing login window (%s)",
             "backend unavailable" if problem else "no valid device token")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
