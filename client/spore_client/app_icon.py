"""应用图标 = MV3 扩展图标（`Spore/icons/*.png` 拷进包内 `assets/`）。

用户 2026-10-02 拍板「图标换成 mv3 用的图标」。16/32/48/128 四档全塞进同一个
QIcon，窗口 / 任务栏 / 托盘各自挑最接近的一档，避免只塞一档被拉糊。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

_ASSETS = Path(__file__).parent / "assets"


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 32, 48, 128):
        p = _ASSETS / f"icon-{size}.png"
        if p.is_file():
            ic.addFile(str(p), QSize(size, size))
    return ic
