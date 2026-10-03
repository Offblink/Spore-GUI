"""扫码配对的纯逻辑与取数线程（2026-10-03 自 settings 迁出）。

配对 UI 从设置页挪到**主窗左下角昵称头像**：点头像 → 按钮附近弹二维码
（非模态），手输通道整体废弃——本模块只管「token → 载荷 → QR 图」与头像首字母。
载荷形状不变：{"v":1,"api":本机REST,"token":LAN token}（02 认证节拍板）。
"""

from __future__ import annotations

import json

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage, QPixmap

from .api import ApiClient, ApiError, NetworkError


class LanTask(QThread):
    """后台取 LAN token（主线程不发网络请求，沿用 settings 里的同款）。"""

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


def build_payload(api_base: str, token: str) -> str:
    """扫码载荷：手机直连本机 REST 的 api + token。"""
    return json.dumps({"v": 1, "api": api_base, "token": token},
                      ensure_ascii=False)


def initial_of(*names: str) -> str:
    """头像首字母：昵称优先；取首个非空白字符并大写（中文即首字）。"""
    for n in names:
        s = (n or "").strip()
        if s:
            return s[0].upper()
    return "?"


def _qr_matrix(payload: str) -> list[list[bool]]:
    """QR 编码走本机已装的 qrcode 库（venv --system-site-packages 可用）。"""
    import qrcode  # noqa: PLC0415 —— 缺库时 ImportError 由 UI 兜底提示
    qr = qrcode.QRCode(version=None, box_size=1, border=0,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.get_matrix()


def payload_image(payload: str, size: int = 180):
    """载荷 → QR pixmap（白底黑块，border=1 模块静区）。"""
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
