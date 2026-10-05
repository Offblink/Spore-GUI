"""扫码配对的纯逻辑与取数线程（2026-10-03 自 settings 迁出）。

配对 UI 从设置页挪到**主窗左下角昵称头像**：点头像 → 按钮附近弹二维码
（非模态），手输通道整体废弃——本模块只管「token → 载荷 → QR 图」与头像首字母。
载荷形状不变：{"v":1,"api":本机REST,"token":LAN token}（02 认证节拍板）。
api 的 host 按 design/02 Base URL 要求用 **PC 局域网 IP**——桌面自己连
127.0.0.1 没问题，手机扫到回环地址就废了（2026-10-03 移动端联调实测），
所以出码前过 api_base_for_phone。
"""

from __future__ import annotations

import json
import socket
from urllib.parse import urlsplit, urlunsplit

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


def _is_lan_ipv4(ip: str) -> bool:
    """只认 RFC1918 私网 IPv4（10/8、172.16/12、192.168/16）。

    回环（127）、APIPA（169.254）、Clash/TUN 探测段（198.18）一律不算——
    这些地址手机同样连不上，换了等于没换。
    """
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if any(n > 255 for n in nums):
        return False
    a, b = nums[0], nums[1]
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def lan_ipv4() -> str:
    """本机局域网 IPv4（design/02 Base URL：``http://<PC局域网IP>:8080/api``）。

    先用 UDP connect 探默认路由出口（UDP connect 不发包、只做路由查表），
    结果过私网闸；再扫 ``getaddrinfo(hostname)`` 兜底。都拿不到 → 空串
    （调用方保持原 base，手机确认框仍可手改）。
    """
    probe = ""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 53))
            probe = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        pass
    if _is_lan_ipv4(probe):
        return probe
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None,
                                   socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        infos = []
    for info in infos:
        ip = info[4][0]
        if _is_lan_ipv4(ip):
            return ip
    return ""


def rewrite_loopback(base: str, ip: str) -> str:
    """把 base 的回环 host 换成 ip（scheme/端口/路径原样保留）。

    ip 不是局域网地址、或 base 本来就不是回环（用户已手填局域网）→ 原样返回。
    """
    if not _is_lan_ipv4(ip):
        return base
    try:
        parts = urlsplit(base)
    except ValueError:
        return base
    if (parts.hostname or "") not in ("127.0.0.1", "localhost", "::1"):
        return base
    netloc = ip + (f":{parts.port}" if parts.port else "")
    return urlunsplit((parts.scheme, netloc, parts.path,
                       parts.query, parts.fragment))


def api_base_for_phone(base: str) -> str:
    """扫码载荷里的 api：回环 → 本机局域网 IP；其余原样。"""
    return rewrite_loopback(base, lan_ipv4())


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
