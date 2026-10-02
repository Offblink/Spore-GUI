"""Spore 客户端入口：登录窗口 -> 主窗口（三页签 + 截屏热键）。"""

import ctypes
import sys

from PySide6.QtWidgets import QApplication

from .api import ApiClient
from .login import LoginWindow, try_device_login
from .main_window import MainWindow


def main() -> int:
    # 任务栏身份（否则 pythonw 的窗口可能挂到别的控制台身份下）
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Spore.Desktop")
    app = QApplication(sys.argv)
    app.setApplicationName("Spore")

    api = ApiClient()
    app._api = api  # noqa: SLF001 — 防 GC

    def enter_main(vo: dict):
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        login.close()

    # 静默登录优先（device.token 在 → 直接进主窗）
    me = try_device_login(api)
    if me is not None:
        win = MainWindow(api)
        win.show()
        app._main = win  # noqa: SLF001
        return app.exec()

    login = LoginWindow(api)
    login.loginSucceeded.connect(enter_main)
    login.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
