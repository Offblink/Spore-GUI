"""登录窗口：账号密码 + 🙈/👀 口令可见切换 + 注册（首个注册的用户即管理员）+ device.token 静默登录。

UI 只经 ApiClient 走 REST（handoff §1 铁律不变）。
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from .api import ApiClient, ApiError, NetworkError

DEVICE_TOKEN_FILE = Path(os.environ.get(
    "SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore"
)) / "device.token"


def _mask_line_edit(edit: QLineEdit) -> None:
    """LineEdit 是 qfluentwidgets 的；密码掩码走 Qt 自带 echo mode。"""
    edit.setEchoMode(QLineEdit.Password)


class _LoginTask(QThread):
    """登录/注册跑后台线程，避免 UI 卡 15s 超时。"""
    ok = Signal(dict)          # login 成功：LoginVO
    registered = Signal()      # 注册成功（随后自动登录）
    failed = Signal(str)

    def __init__(self, api: ApiClient, mode: str, u: str, p: str, parent=None):
        super().__init__(parent)
        self.api, self.mode, self.u, self.p = api, mode, u, p

    def run(self):
        try:
            if self.mode == "register":
                self.api.register(self.u, self.p)
                self.registered.emit()
            else:
                vo = self.api.login(self.u, self.p)
                self.ok.emit(vo)
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


class LoginWindow(QWidget):
    """登录成功后发 loginSucceeded(vo)，由 app 换主窗口。"""

    loginSucceeded = Signal(dict)

    def __init__(self, api: ApiClient, parent=None,
                 startup_note: str | None = None):
        super().__init__(parent)
        self.api = api
        self.revealed = False
        self._task: _LoginTask | None = None

        self.setWindowTitle("Spore")
        self.resize(420, 320)

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 36, 48, 36)
        root.setSpacing(14)

        title = StrongBodyLabel("登录")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        root.addWidget(title)
        root.addSpacing(8)

        self.username = LineEdit()
        self.username.setPlaceholderText("用户名")
        root.addWidget(self._row("用户名", self.username))

        # 密码行：qfluentwidgets LineEdit + 可见性切换按钮
        self.password = LineEdit()
        self.password.setPlaceholderText("密码")
        self.password.setEchoMode(QLineEdit.Password)
        self.eye = PushButton("🙈")
        self.eye.setFixedWidth(48)
        self.eye.clicked.connect(self._toggle_visibility)
        root.addWidget(self._row("密码", self.password, self.eye))

        self.status = CaptionLabel("")
        self.status.setTextColor("#d13438", "#d13438")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        if startup_note:
            self.status.setText(startup_note)  # 后端没起来：开门第一句就说清为什么连不上

        btn_row = QHBoxLayout()
        self.login_btn = PrimaryPushButton("登录")
        self.register_btn = PushButton("注册")
        btn_row.addStretch(1)
        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.register_btn)
        btn_row.addStretch(1)
        root.addLayout(btn_row)
        root.addStretch(1)

        self.login_btn.clicked.connect(lambda: self._start("login"))
        self.register_btn.clicked.connect(lambda: self._start("register"))
        self.password.returnPressed.connect(lambda: self._start("login"))
        self.username.returnPressed.connect(lambda: self.password.setFocus())

    # ---------- 布局小工具 ----------
    @staticmethod
    def _row(label: str, edit: LineEdit, extra: QWidget | None = None) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lb = BodyLabel(label)
        lb.setFixedWidth(44)
        lay.addWidget(lb)
        lay.addWidget(edit, 1)
        if extra is not None:
            lay.addWidget(extra)
        return w

    # ---------- 行为 ----------
    def _toggle_visibility(self):
        self.revealed = not self.revealed
        self.password.setEchoMode(
            QLineEdit.Normal if self.revealed else QLineEdit.Password)
        self.eye.setText("👀" if self.revealed else "🙈")

    def _start(self, mode: str):
        u, p = self.username.text().strip(), self.password.text()
        if not u or not p:
            self.status.setText("用户名和密码都要填")
            return
        if self._task is not None and self._task.isRunning():
            return  # 上一发还没回来（上一次就是超时挂的，别叠加）
        self.login_btn.setEnabled(False)
        self.register_btn.setEnabled(False)
        self.status.setText("连接中…" if mode == "login" else "注册中…")

        self._task = _LoginTask(self.api, mode, u, p, self)
        if mode == "register":
            # 注册成功后立刻自动登录（与 JavaFX 版语义一致）
            self._task.registered.connect(lambda: self._start("login"))
        self._task.ok.connect(self._on_ok)
        self._task.failed.connect(self._on_fail)
        self._task.finished.connect(self._reset_buttons)
        self._task.start()

    def _on_ok(self, vo: dict):
        # 登录成功 → 轮换并存本机令牌（下次启动免输）
        try:
            DEVICE_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            DEVICE_TOKEN_FILE.write_text(
                self.api.create_device_token(), encoding="utf-8")
        except (ApiError, NetworkError):
            pass  # 静默令牌失败不阻断登录
        self.loginSucceeded.emit(vo)

    def _on_fail(self, msg: str):
        self.status.setText(msg)

    def _reset_buttons(self):
        self.login_btn.setEnabled(True)
        self.register_btn.setEnabled(True)


def try_device_login(api: ApiClient) -> dict | None:
    """启动时用本机 device.token 静默换 JWT；失败返回 None（回登录页）。"""
    try:
        saved = DEVICE_TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not saved:
        return None
    try:
        api.device_login(saved)
        return api.me()
    except (ApiError, NetworkError):
        with suppress(OSError):
            DEVICE_TOKEN_FILE.unlink(missing_ok=True)  # 失效令牌清掉，回登录页
        return None
