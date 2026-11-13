"""应用图标 = 孢子球（与 Spore-Mobile v2 同一套几何/配色）。

16/32/48/128/256 五档全塞进同一个 QIcon，窗口 / 任务栏 / 托盘各自挑最接近的
一档，避免只塞一档被拉糊。图标由 scratch 脚本按移动端矢量渲染（见 CHANGELOG /
提交说明），改图标要同时更新 `assets/app.ico`（tools/make_icon.py）。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon

_ASSETS = Path(__file__).parent / "assets"
_SIZES = (16, 32, 48, 128, 256)


def app_icon() -> QIcon:
    ic = QIcon()
    for size in _SIZES:
        p = _ASSETS / f"icon-{size}.png"
        if p.is_file():
            ic.addFile(str(p), QSize(size, size))
    return ic
