"""期5 截屏链路：全局热键 → 隐藏自家窗口 → 抓帧 → 冻结帧框选 → JPEG。

04 文档 §一/§五 纪律落地：
- 冻结帧：抓完只用位图，屏幕再变也不跟
- 最小框 60×40（与 MV3 PANEL 判定同值），太小提示不收；ESC 取消
- HiDPI：抓屏是物理像素、Qt 是逻辑坐标（本机 150%）→ 比例映射，不手算 DPI；
  map_rect 是纯函数，pytest 直接钉死（04 验收清单第 1 条）
- 抓帧前隐藏自家窗口（防截到自己），抓完立刻恢复（冻结帧全屏不透明盖住）

单屏 v1：抓主屏、覆盖层对齐主屏；多屏/异常缩放为已知边界（04 §五.1）。
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

import keyboard
from PIL import Image, ImageGrab
from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

MIN_W, MIN_H = 60, 40
JPEG_LONG_EDGE = 1600
JPEG_QUALITY = 82
# 与 MV3 端一致（用户拍板 2026-10-02）：Alt+S 截屏；
# Alt+Z 呼出回答面板（P4 建 AnswerWindow 时注册，MV3 hideToggle 同款语义）
HOTKEY = "alt+s"
HIDE_DELAY_MS = 220  # 窗口隐藏 → 抓帧的合成间隔
CAPTURE_DIR = Path(
    os.environ.get("SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore")
) / "captures"


# ---------- 纯函数（pytest 钉住，不碰 Qt） ----------

def map_rect(sel: tuple[float, float, float, float],
             logical_size: tuple[int, int],
             pixel_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """逻辑选区 (x, y, w, h) → 图像像素矩形 (x, y, w, h)。

    比例映射：pixel/logical 系数分别算 x/y，钳进图像边界——任何缩放率都对。
    """
    lx, ly, lw, lh = sel
    gw, gh = logical_size
    pw, ph = pixel_size
    sx, sy = pw / gw, ph / gh
    x0 = max(0, min(pw, round(lx * sx)))
    y0 = max(0, min(ph, round(ly * sy)))
    x1 = max(0, min(pw, round((lx + lw) * sx)))
    y1 = max(0, min(ph, round((ly + lh) * sy)))
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def too_small(w: float, h: float) -> bool:
    return w < MIN_W or h < MIN_H


def encode_jpeg(img: Image.Image, dest: Path) -> Path:
    """长边 1600、q82（与手机端同参），存盘返回路径。"""
    out = img.convert("RGB")
    out.thumbnail((JPEG_LONG_EDGE, JPEG_LONG_EDGE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "JPEG", quality=JPEG_QUALITY)
    return dest


# ---------- 全局热键 ----------

class HotkeyManager:
    """keyboard 库钩子线程 → Qt 信号跨线程发射（接收方主线程自动队列化）。"""

    def __init__(self, on_trigger, combo: str = HOTKEY):
        self._combo = combo
        keyboard.add_hotkey(combo, on_trigger, suppress=False)

    def close(self):
        with suppress(Exception):
            keyboard.remove_hotkey(self._combo)


# ---------- 冻结帧覆盖层 ----------

class CropOverlay(QWidget):
    """全屏不透明显示冻结帧；拖拽框选，ESC 取消，太小不收。"""

    selected = Signal(object)  # (x, y, w, h) 逻辑坐标
    cancelled = Signal()

    def __init__(self, image: Image.Image,
                 logical: tuple[int, int], parent=None):
        super().__init__(parent)
        rgb = image.convert("RGB")
        self._image = rgb
        data = rgb.tobytes()
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3,
                      QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(qimg)
        self._logical = logical
        self._start: tuple[float, float] | None = None
        self._rect: QRectF | None = None
        self._hint = ""

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(0, 0, logical[0], logical[1])

    # --- 绘制 ---
    def paintEvent(self, ev):
        p = QPainter(self)
        # 冻结帧铺满（物理位图 → 逻辑几何，Qt 自己做缩放）
        p.drawPixmap(self.rect(), self._pixmap)
        if self._rect is not None and not self._rect.isEmpty():
            r = QRectF(self.rect())
            sel = self._rect.normalized()
            # 选区外压暗
            p.setOpacity(0.55)
            p.fillRect(QRectF(r.left(), r.top(), r.width(), sel.top() - r.top()),
                       "black")
            p.fillRect(QRectF(r.left(), sel.bottom(), r.width(),
                              r.bottom() - sel.bottom()), "black")
            p.fillRect(QRectF(r.left(), sel.top(), sel.left() - r.left(),
                              sel.height()), "black")
            p.fillRect(QRectF(sel.right(), sel.top(), r.right() - sel.right(),
                              sel.height()), "black")
            p.setOpacity(1.0)
            pen = QPen("#00b7c3", 2)
            p.setPen(pen)
            p.drawRect(sel)
            # 尺寸角标
            p.drawText(sel.left() + 4, max(14, sel.top() - 6),
                       f"{int(sel.width())}×{int(sel.height())}")
        if self._hint:
            p.setPen(QPen("#d13438"))
            p.drawText(24, self.height() - 24, self._hint)
        p.end()

    # --- 交互 ---
    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self.cancelled.emit()
            return
        self._hint = ""
        self._start = (ev.position().x(), ev.position().y())
        self._rect = None

    def mouseMoveEvent(self, ev):
        if self._start is None:
            return
        x0, y0 = self._start
        self._rect = QRectF(x0, y0, ev.position().x() - x0,
                            ev.position().y() - y0)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or self._rect is None:
            return
        r = self._rect.normalized()
        if r.isEmpty():
            return
        if too_small(r.width(), r.height()):
            self._hint = f"框太小（最小 {MIN_W}×{MIN_H}），重新拖或按 ESC 取消"
            self._rect = None
            self.update()
            return
        self.selected.emit((r.x(), r.y(), r.width(), r.height()))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(ev)


# ---------- 编排：隐藏 → 抓帧 → 覆盖层 → 裁剪落盘 ----------

class CaptureController:
    def __init__(self, on_captured):
        self._on_captured = on_captured  # 收到 JPEG 路径 str
        self._hidden: list[QWidget] = []
        self._overlay: CropOverlay | None = None
        self._image: Image.Image | None = None
        self._logical: tuple[int, int] = (0, 0)
        self._busy = False  # 框选中忽略热键（否则二次触发叠两层覆盖层）

    def start(self):
        """热键入口（Qt 主线程执行）。"""
        if self._busy:
            return
        self._busy = True
        app = QApplication.instance()
        screen = app.primaryScreen()
        self._logical = (screen.size().width(), screen.size().height())
        self._hidden = [w for w in app.topLevelWidgets() if w.isVisible()]
        for w in self._hidden:
            w.hide()
        QTimer.singleShot(HIDE_DELAY_MS, self._grab)

    def _grab(self):
        # PIL 在本进程（Qt6 per-monitor aware）按物理像素出图；
        # bbox 钳到主屏——多屏时 grab() 会带回整块虚拟屏，覆盖层却只有主屏宽，坐标会错位
        gw, gh = self._logical
        dpr = QApplication.instance().primaryScreen().devicePixelRatio()
        bbox = (0, 0, round(gw * dpr), round(gh * dpr))
        try:
            self._image = ImageGrab.grab(bbox=bbox)
        except OSError:
            self._image = ImageGrab.grab()  # bbox 越界等异常时退回全屏（单屏恒等）
        # 抓完即恢复——覆盖层全屏不透明，恢复的窗口藏它后面
        for w in self._hidden:
            w.show()
        self._hidden = []
        ov = CropOverlay(self._image, self._logical)
        ov.selected.connect(self._on_selected)
        ov.cancelled.connect(self._close)
        self._overlay = ov
        ov.show()
        ov.activateWindow()  # 接 ESC

    def _on_selected(self, sel):
        x, y, w, h = map_rect(sel, self._logical, self._image.size)
        crop = self._image.crop((x, y, x + w, y + h))
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = CAPTURE_DIR / f"cap-{stamp}.jpg"
        encode_jpeg(crop, dest)
        self._close()
        self._on_captured(str(dest))

    def _close(self):
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self._busy = False  # ESC/取消/裁剪完成都回到可触发态

    def shutdown(self):
        self._close()
