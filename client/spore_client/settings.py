"""设置页：LAN 二维码配对 + 题库目录切换 + LLM 配置展示。

- 二维码载荷 = 02 认证节拍板 JSON {"v":1,"api":...,"token":...}，ZXing 渲染成图；
  手机扫码后先 GET /users/me 验通（连通+鉴权一发验证）才置 paired。
- key 只在环境变量里，本页只展示「已配置/未配置」，绝不回显 key 本体（红线）。
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SwitchButton,
)

from .answer.settings import LlmSettings
from .api import ApiClient, ApiError, NetworkError


class _LanTask(QThread):
    ok = Signal(str)
    failed = Signal(str)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api

    def run(self):
        try:
            self.ok.emit(self.api.lan_token())
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


def _qr_matrix(payload: str) -> list[list[bool]]:
    """QR 编码走本机已装的 qrcode 库（venv --system-site-packages 可用）。"""
    import qrcode  # noqa: PLC0415 —— 缺库时 ImportError 由 UI 兜底提示
    qr = qrcode.QRCode(version=None, box_size=1, border=0,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def _payload_image(payload: str, size: int = 180):
    from PIL import Image, ImageDraw
    m = _qr_matrix(payload)
    n = len(m)
    scale = max(1, size // (n + 2))
    px = (n + 2) * scale
    img = Image.new("RGB", (px, px), "white")
    d = ImageDraw.Draw(img)
    for y in range(n):
        for x in range(n):
            if m[y][x]:
                d.rectangle([x * scale + scale, y * scale + scale,
                             (x + 1) * scale + scale - 1,
                             (y + 1) * scale + scale - 1], fill="black")
    qimg = QImage(img.tobytes(), px, px, px * 3, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg)


class SettingsPane(QWidget):
    def __init__(self, api: ApiClient, llm: LlmSettings, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")  # FluentWindow.addSubInterface 要求非空
        self.api = api
        self.llm = llm

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # ---- 手机配对 ----
        pair_card = QVBoxLayout()
        pair_card.addWidget(StrongBodyLabel("手机扫码配对"))
        pair_card.addWidget(CaptionLabel(
            "载荷 = {\"v\":1,\"api\":...,\"token\":...}；手机存 token 后先验 /users/me "
            "再放行同步（02 认证节拍板）。"))
        row = QHBoxLayout()
        self.qr_label = QLabel("加载中…")
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("border: 1px solid #ddd; background: #fff;")
        side = QVBoxLayout()
        self.token_edit = LineEdit()
        self.token_edit.setPlaceholderText("LAN token（手机手输兜底）")
        self.token_edit.setReadOnly(True)
        self.gen_btn = PrimaryPushButton("生成二维码")
        self.gen_btn.clicked.connect(self._gen_qr)
        side.addWidget(BodyLabel("token（只读）："))
        side.addWidget(self.token_edit)
        side.addWidget(self.gen_btn)
        side.addStretch(1)
        row.addWidget(self.qr_label)
        row.addLayout(side, 1)
        pair_card.addLayout(row)
        root.addLayout(pair_card)

        # ---- 题库目录 ----
        dir_card = QVBoxLayout()
        dir_card.addWidget(StrongBodyLabel("题库目录"))
        dir_row = QHBoxLayout()
        self.dir_edit = LineEdit()
        self.dir_edit.setReadOnly(True)
        self.dir_btn = PushButton("切换…")
        self.dir_btn.clicked.connect(self._switch_dir)
        self.dir_info = CaptionLabel("")
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.dir_btn)
        dir_card.addLayout(dir_row)
        dir_card.addWidget(self.dir_info)
        root.addLayout(dir_card)

        # ---- LLM 配置（只展示状态，key 不回显） ----
        llm_card = QVBoxLayout()
        llm_card.addWidget(StrongBodyLabel("作答模型"))
        kv = QHBoxLayout()
        kv.addWidget(CaptionLabel(f"endpoint：{self.llm.endpoint}"))
        kv.addStretch(1)
        kv.addWidget(CaptionLabel(f"model：{self.llm.model}"))
        llm_card.addLayout(kv)
        key_row = QHBoxLayout()
        key_row.addWidget(CaptionLabel(
            "API key：" + ("已从环境变量读取 ✓（不显示本体）"
                          if self.llm.api_key else "未配置 ✗")))
        key_row.addStretch(1)
        llm_card.addLayout(key_row)
        if self.llm.errors:
            llm_card.addWidget(CaptionLabel("；".join(self.llm.errors)))
        rounds_row = QHBoxLayout()
        rounds_row.addWidget(CaptionLabel("核实检索轮数："))
        # LineEdit 构造器只收 parent（qfluentwidgets 1.11.3 实测），文本走 setText
        self.rounds = LineEdit()
        self.rounds.setText(str(self.llm.max_tool_rounds))
        self.rounds.setFixedWidth(60)
        rounds_row.addWidget(self.rounds)
        rounds_row.addWidget(CaptionLabel("0=不自动核实"))
        rounds_row.addStretch(1)
        llm_card.addLayout(rounds_row)
        self.auto_verify = SwitchButton()
        self.auto_verify.setChecked(self.llm.auto_verify)
        self.auto_verify.checkedChanged.connect(
            lambda on: setattr(self.llm, "auto_verify", on))
        av_row = QHBoxLayout()
        av_row.addWidget(CaptionLabel("答完自动联网核实："))
        av_row.addWidget(self.auto_verify)
        av_row.addStretch(1)
        llm_card.addLayout(av_row)
        root.addLayout(llm_card)
        root.addStretch(1)

        self.status = CaptionLabel("")
        root.addWidget(self.status)

        self._lan_task: _LanTask | None = None

    # ---------- 配对 ----------
    def _gen_qr(self):
        self.status.setText("取 token…")
        self._lan_task = _LanTask(self.api, self)
        self._lan_task.ok.connect(self._on_token)
        self._lan_task.failed.connect(
            lambda m: self.status.setText(f"取 token 失败：{m}"))
        self._lan_task.start()

    def _on_token(self, token: str):
        self.token_edit.setText(token)
        payload = json.dumps({
            "v": 1,
            "api": self.api.base,          # 手机直连本机 REST
            "token": token,
        }, ensure_ascii=False)
        try:
            self.qr_label.setPixmap(_payload_image(payload))
            self.status.setText("二维码已生成（10 分钟内扫；token 常驻不过期）")
        except ImportError:
            self.status.setText("缺 qrcode 库，用下面的 token 手输")

    # ---------- 目录 ----------
    def _switch_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择题库目录")
        if not d:
            return
        self._switch_to(d)

    def _switch_to(self, d: str):
        """切换 = 拷贝→校验→切配置→删旧（后端 StorageService 全做，客户端只发请求）。"""
        self.status.setText("切换中…（拷贝→校验→切配置→删旧）")
        try:
            info = self.api.switch_storage(d)
            data = info if isinstance(info, dict) else {}
            self.dir_edit.setText(str(data.get("dir", d)))
            self.dir_info.setText(
                f"{data.get('files', '?')} 个文件 · {data.get('bytes', '?')} 字节")
            self.status.setText("题库目录已切换")
        except (ApiError, NetworkError) as e:
            self.status.setText(f"切换失败：{e}")

    def refresh(self):
        """进入本页时拉一次目录现状。"""
        try:
            info = self.api.storage_info()
            self.dir_edit.setText(str(info.get("dir", "")))
            self.dir_info.setText(
                f"{info.get('files', '?')} 个文件 · {info.get('bytes', '?')} 字节")
        except (ApiError, NetworkError):
            self.status.setText("读取题库目录失败（后端未启动？）")
