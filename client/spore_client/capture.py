"""期5 截屏链路：全局热键 → 抓帧 → 冻结帧框选 → JPEG。

04 文档 §一/§五 纪律落地：
- 冻结帧：抓完只用位图，屏幕再变也不跟
- 框太小判定与 MV3 `overlay.js` 同口径：宽、高**都**低于 60×40 才拒
  （有其一够大就放行——宽条、高条都能截）；ESC 取消
- HiDPI：抓屏是物理像素、Qt 是逻辑坐标（本机 150%）→ 比例映射，不手算 DPI；
  map_rect 是纯函数，pytest 直接钉死（04 验收清单第 1 条）
- 抓帧前不隐藏自家窗口（2026-10-02 用户拍板「不需要最小化程序，用户自己会
  调整」）——自家窗口入不入镜由用户自己挪窗口决定
- AI 建议框（2026-10-08，**默认关**，settings_store.ml_suggest_enabled）：
  开关开着才异步跑离线 OCR（RapidOCR 懒加载单例，绝不在 UI 线程跑）→
  Suggestor（忠实移植 Mobile Suggestor.java）出单框 → 预填当前选区；
  识别失败/超时 8000ms/用户已起手 → 静默丢弃，退手动拖框（不弹任何提示）

单屏 v1：抓主屏、覆盖层对齐主屏；多屏/异常缩放为已知边界（04 §五.1）。
"""

from __future__ import annotations

import os
import re
import threading
import time
from contextlib import suppress
from pathlib import Path

import keyboard
from PIL import Image, ImageGrab
from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import settings_store
from .log import get_logger

LOG = get_logger()

MIN_W, MIN_H = 60, 40
JPEG_LONG_EDGE = 1600
JPEG_QUALITY = 82
# AI 建议框（与 Mobile 同参，2026-10-08 拍板）：识别超时 8000ms 与
# Mobile ML_TIMEOUT_MS 同值；识别前文本框先缩到长边 ≤1600 再识别
ML_TIMEOUT_MS = 8000
ML_LONG_EDGE = 1600
# 与 MV3 端一致（用户拍板 2026-10-02）：Alt+S 截屏；
# Alt+Z 呼出回答面板（P4 建 AnswerWindow 时注册，MV3 hideToggle 同款语义）
HOTKEY = "alt+s"
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
    """MV3 `overlay.js` 口径：两者有其一达到下限就允许，
    宽高**都**低于下限才算框太小（宽条、高条都能截，避免误杀细长截图）。
    """
    return w < MIN_W and h < MIN_H


# ---------- 建议框的缩放手柄与「采纳」按钮（2026-10-09 拍板，与 MV3 端同款） ----------
# 手柄 8 方位里**右下角让给「采纳」按钮** → 7 个；采纳只走按钮（单击框内/回车已废弃）。

HANDLES = ("nw", "n", "ne", "w", "e", "sw", "s")
HS = 10        # 手柄边长（px）
HIT = 6        # 命中容差：手柄小，鼠标不必压得很准
BTN_W, BTN_H = 56, 26


def handle_centers(r: QRectF) -> dict[str, tuple[float, float]]:
    """建议框 7 个缩放手柄的中心点（右下角没有手柄——那里是采纳按钮）。"""
    cx, cy = r.center().x(), r.center().y()
    return {
        "nw": (r.left(), r.top()),
        "n": (cx, r.top()),
        "ne": (r.right(), r.top()),
        "w": (r.left(), cy),
        "e": (r.right(), cy),
        "sw": (r.left(), r.bottom()),
        "s": (cx, r.bottom()),
    }


def hit_handle(x: float, y: float, r: QRectF) -> str | None:
    """命中缩放手柄 → 方位；没命中返回 None（容差 HS/2 + HIT）。"""
    reach = HS / 2 + HIT
    for d, (cx, cy) in handle_centers(r).items():
        if abs(x - cx) <= reach and abs(y - cy) <= reach:
            return d
    return None


def resize_rect(r: QRectF, d: str, x: float, y: float,
                bound_w: float, bound_h: float) -> QRectF:
    """拖哪条边就动哪条（含三角），夹进 [0, bound]；对边不动。纯函数，pytest 钉。"""
    out = QRectF(r)
    if "w" in d:
        out.setLeft(max(0.0, min(x, out.right())))
    if "e" in d:
        out.setRight(min(bound_w, max(x, out.left())))
    if "n" in d:
        out.setTop(max(0.0, min(y, out.bottom())))
    if "s" in d:
        out.setBottom(min(bound_h, max(y, out.top())))
    return out


def accept_btn_rect(r: QRectF) -> QRectF:
    """「采纳」按钮：贴选区右下角**外侧**（右缘与选区对齐）。视口钳制由调用方做。"""
    return QRectF(r.right() - BTN_W, r.bottom() + 6, BTN_W, BTN_H)


def encode_jpeg(img: Image.Image, dest: Path) -> Path:
    """长边 1600、q82（与手机端同参），存盘返回路径。"""
    out = img.convert("RGB")
    out.thumbnail((JPEG_LONG_EDGE, JPEG_LONG_EDGE), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest, "JPEG", quality=JPEG_QUALITY)
    return dest


def unmap_rect(rect: tuple[float, float, float, float],
               logical_size: tuple[int, int],
               pixel_size: tuple[int, int]) -> tuple[float, float, float, float]:
    """图像像素矩形 (x, y, w, h) → 覆盖层逻辑坐标（map_rect 的逆向，比例映射）。"""
    x, y, w, h = rect
    gw, gh = logical_size
    pw, ph = pixel_size
    sx, sy = gw / pw, gh / ph
    return x * sx, y * sy, w * sx, h * sy


# ---------- Suggestor（忠实移植 Mobile Suggestor.java，行为由 SuggestTest 钉住） ----------
# 移植纪律：正则、15 个 cue 词、聚类判据、门槛、打分、padding、平手规则、
# sb 每行前拼空格 + firstLine() 取第一个空格前片段——一律照抄，勿「优化」。

#: 题号开头：`1.` `2、` `3．` `4)` `5）`（前导空白可有可无）；Java `^\s*\d+\s*[.、．)）]`
NUMBERING = re.compile(r"^\s*\d+\s*[.、．)）]")
#: 题干常见词（命中 +10，一票多词也只加一次）——与 Java CUES 逐字一致
CUES = ("下列", "选择", "判断", "如图", "关于", "说法", "正确", "错误",
        "多少", "等于", "计算", "求解", "公式", "实验", "如右图")


class OcrLine:
    """一行识别结果（冻结帧像素坐标）——对位 Java `Suggestor.Line`。"""

    __slots__ = ("left", "top", "right", "bottom", "text")

    def __init__(self, left: int, top: int, right: int, bottom: int,
                 text: str | None):
        self.left = int(left)
        self.top = int(top)
        self.right = int(right)
        self.bottom = int(bottom)
        self.text = "" if text is None else str(text)


class _Cluster:
    """纵向聚出的文本块。

    `sb`/`chars`/`lastLineH` 的更新次序照抄 Java（firstLine() 语义依赖
    sb 的拼接顺序：每行前都拼一个空格，首行 = trim 后第一个空格前的片段）。
    """

    __slots__ = ("left", "top", "right", "bottom", "last_line_h", "chars", "_sb")

    def __init__(self, line: OcrLine):
        self.left = line.left
        self.top = line.top
        self.right = line.right
        self.bottom = line.bottom
        self.last_line_h = line.bottom - line.top
        self.chars = 0
        self._sb = ""
        self.add(line)

    def add(self, line: OcrLine) -> None:
        self.left = min(self.left, line.left)
        self.top = min(self.top, line.top)
        self.right = max(self.right, line.right)
        self.bottom = max(self.bottom, line.bottom)
        self.last_line_h = line.bottom - line.top
        self._sb += " " + line.text
        self.chars += len(line.text.strip())

    def absorb(self, other: _Cluster) -> None:
        self.left = min(self.left, other.left)
        self.top = min(self.top, other.top)
        self.right = max(self.right, other.right)
        self.bottom = max(self.bottom, other.bottom)
        self._sb += " " + other._sb
        self.chars += other.chars

    def can_join(self, line: OcrLine) -> bool:
        # 纵向相邻（间隙 ≤ 1.6×上一行行高）且水平重叠 ≥ 0.2×窄者宽 → 同块
        gap = line.top - self.bottom
        if gap > 1.6 * self.last_line_h:
            return False
        overlap = min(self.right, line.right) - max(self.left, line.left)
        min_w = min(self.width, line.right - line.left)
        return min_w > 0 and overlap >= 0.2 * min_w

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def first_line(self) -> str:
        raw = self._sb.strip()
        nl = raw.find(" ")
        return raw[:nl] if nl >= 0 else raw

    def score(self) -> float:
        """题面信号 + 文本量；平手取先出现（上方）的块。"""
        text = self._sb
        s = min(self.chars, 150) / 10.0
        if "？" in text or "?" in text:
            s += 40
        if NUMBERING.match(self.first_line()):
            s += 25
        for cue in CUES:
            if cue in text:
                s += 10
                break  # 多词也只加一次，防止关键词堆叠压过问号
        return s


def _cluster(sorted_lines: list[OcrLine]) -> list[_Cluster]:
    """逐行归块；一行同时可入多块 → 并进最早创建的那块（照抄 Java 次序）。"""
    out: list[_Cluster] = []
    for line in sorted_lines:
        hits = [c for c in out if c.can_join(line)]
        if not hits:
            out.append(_Cluster(line))
            continue
        first = hits[0]
        first.add(line)
        for other in hits[1:]:
            first.absorb(other)
            out.remove(other)
    return out


def _pad(left: int, top: int, right: int, bottom: int,
         frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    p = int(max(8, min(24, 0.02 * max(right - left, bottom - top))))
    return (max(0, left - p), max(0, top - p),
            min(frame_w, right + p), min(frame_h, bottom + p))


def suggest(lines: list[OcrLine] | None,
            frame_w: int, frame_h: int) -> tuple[int, int, int, int] | None:
    """文本行 → 纵向聚类 → 选最像题的块 → 单框（帧坐标、含外扩 padding）。

    忠实移植 Mobile `Suggestor.java`（其行为由 Mobile SuggestTest 钉住）；
    块太小（宽 < 0.10×帧宽 或 高 < max(36, 0.015×帧高)）/无文本 → None，
    调用方退化为手动拖框。
    """
    if not lines or frame_w <= 0 or frame_h <= 0:
        return None
    usable = [ln for ln in lines
              if ln.text.strip() and ln.right > ln.left and ln.bottom > ln.top]
    if not usable:
        return None
    usable.sort(key=lambda ln: (ln.top, ln.left))  # 自上而下、左到右（Java 稳定排序同款）

    clusters = _cluster(usable)
    min_w = int(0.10 * frame_w)
    min_h = max(36, int(0.015 * frame_h))

    best: _Cluster | None = None
    best_score = 0.0
    for c in clusters:
        if c.width < min_w or c.height < min_h:
            continue   # 小块没资格当建议框（手动拖才够准）
        s = c.score()
        if best is None or s > best_score:
            best, best_score = c, s   # 平手（s == best_score）保留先出现的块
    if best is None:
        return None
    return _pad(best.left, best.top, best.right, best.bottom, frame_w, frame_h)


# ---------- 离线 OCR（RapidOCR 懒加载单例；开关关着时本区一行都不会执行） ----------

_ocr_engine = None          # 模块级单例：首跑 ~3.3s，之后复用
_ocr_lock = threading.Lock()


def _get_ocr_engine():
    """RapidOCR 懒加载（导入写在函数体内——关着开关 = 零导入、零 OCR 调用）。"""
    global _ocr_engine
    with _ocr_lock:
        if _ocr_engine is None:
            from rapidocr import RapidOCR  # 懒加载写在函数体里：关着开关就不导入
            _ocr_engine = RapidOCR()
    return _ocr_engine


def ocr_lines(img: Image.Image) -> list[OcrLine]:
    """PIL 冻结帧 → RapidOCR 文本行（帧像素坐标）。

    先把长边缩到 ≤1600 再识别，结果坐标按同一比例缩回帧坐标；
    识别不出/无框 → []。异常向上抛（调用方记日志后静默退手动）。
    """
    engine = _get_ocr_engine()
    fw, fh = img.size
    work = img
    if max(fw, fh) > ML_LONG_EDGE:
        s = ML_LONG_EDGE / max(fw, fh)
        work = img.resize((max(1, round(fw * s)), max(1, round(fh * s))),
                          Image.BILINEAR)
    res = engine(work)   # PIL 输入 → rapidocr 内部 RGB→BGR，与文件路径入口同链
    boxes = getattr(res, "boxes", None)
    txts = getattr(res, "txts", None)
    if boxes is None or txts is None:
        return []
    sx, sy = fw / work.width, fh / work.height
    lines: list[OcrLine] = []
    for box, txt in zip(boxes, txts, strict=False):
        xs = [float(p[0]) for p in box]   # 4 点框（可旋转）→ 外接矩形
        ys = [float(p[1]) for p in box]
        lines.append(OcrLine(round(min(xs) * sx), round(min(ys) * sy),
                             round(max(xs) * sx), round(max(ys) * sy), txt))
    return lines


def suggest_box(img: Image.Image) -> tuple[int, int, int, int] | None:
    """冻结帧 → 建议框（帧像素矩形）或 None；识别异常向上抛给线程侧记日志。"""
    return suggest(ocr_lines(img), img.width, img.height)


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
    """全屏不透明显示冻结帧；拖拽框选，ESC 取消，太小不收。

    AI 建议框入口 `apply_suggestion`（镜像 Mobile `setSuggestion`）：预填为当前选区，
    **边界可拖**（7 个手柄微调）+ 右下角「**采纳**」按钮提交 —— 单击框内/回车采纳
    已按 2026-10-09 拍板废弃；手拖选区照旧**松手即采纳**（只服务建议框的两步交互）。
    `_user_started`（左键起手）一旦置位，后到的建议一律拒绝。
    """

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
        self._user_started = False   # 左键起手标志：起手后到的建议一律丢弃
        self._moved = False          # 本次按下是否真的拖动过
        self._resize_dir: str | None = None  # 正在拖的边界方位（只有建议框能进）
        # 当前选区是否来自建议框：只有建议框显示手柄与「采纳」按钮，
        # 手拖出来的选区维持旧行为（起手即清、松手即采纳），ML 关着时与改动前逐字节一致
        self._rect_from_suggestion = False

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
            pen = QPen(QColor("#00b7c3"), 2)  # PySide6：QPen(str, int) 不是合法签名
            p.setPen(pen)
            p.drawRect(sel)
            # 尺寸角标
            p.drawText(sel.left() + 4, max(14, sel.top() - 6),
                       f"{int(sel.width())}×{int(sel.height())}")
            if self._rect_from_suggestion:
                # 建议框才有的两件：7 个缩放手柄 + 右下角「采纳」按钮
                p.setBrush(QBrush(QColor("#ffffff")))
                p.setPen(QPen(QColor("#ec4899"), 2))
                for hx, hy in handle_centers(sel).values():
                    p.drawRect(QRectF(hx - HS / 2, hy - HS / 2, HS, HS))
                br = self._btn_rect()
                p.setBrush(QBrush(QColor("#ec4899")))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(br, 13, 13)
                p.setPen(QPen(QColor("#ffffff")))
                p.drawText(br, Qt.AlignmentFlag.AlignCenter, "采纳")
                p.setBrush(Qt.BrushStyle.NoBrush)
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
        self._user_started = True     # 起手 → 之后到达的建议一律丢弃
        x, y = ev.position().x(), ev.position().y()
        self._start = (x, y)
        self._moved = False
        self._resize_dir = None
        if self._rect_from_suggestion and self._rect is not None:
            # 右下角「采纳」= 提交（单击框内 / 回车采纳已按 2026-10-09 拍板废弃）
            if self._btn_rect().contains(QPointF(x, y)):
                self._accept_rect()
                return
            hd = hit_handle(x, y, self._rect)
            if hd:
                self._resize_dir = hd  # 拖边界：改选区，松手**不**提交
                return
            if self._rect.contains(QPointF(x, y)):
                return                 # 框内空白：不动（边界与按钮才是操作面）
            # 框外起手 → 覆盖建议框，重新拖
            self._rect = None
            self._rect_from_suggestion = False
        else:
            self._rect = None          # 手拖选区：起手即清（既有行为）
        self.update()

    def mouseMoveEvent(self, ev):
        if self._start is None:
            return
        x, y = ev.position().x(), ev.position().y()
        if self._resize_dir and self._rect is not None:
            self._rect = resize_rect(self._rect, self._resize_dir, x, y,
                                     float(self.width()), float(self.height()))
            self.update()
            return
        if self._rect_from_suggestion:
            return                     # 框内空白拖动：选区原地不动
        x0, y0 = self._start
        self._moved = True
        self._rect = QRectF(x0, y0, x - x0, y - y0)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._resize_dir:
            self._resize_dir = None    # 收边界：选区留下，等点「采纳」
            return
        if self._rect_from_suggestion:
            return                     # 框内空白点一下：无效果，建议框还在
        if not self._moved:
            return                     # 原地单击：无效果（原行为同）
        self._accept_rect()

    def _accept_rect(self) -> None:
        """当前选区过门（非空、不太小）→ selected；太小 → 既有拒绝提示。"""
        if self._rect is None:
            return
        r = self._rect.normalized()
        if r.isEmpty():
            return
        if too_small(r.width(), r.height()):
            LOG.info("rejected too-small %.0fx%.0f", r.width(), r.height())
            self._hint = (f"框太小 {int(r.width())}×{int(r.height())}"
                          f"（宽 ≥{MIN_W} 或 高 ≥{MIN_H} 即可），"
                          "重新拖或按 ESC 取消")
            self._rect = None
            self._rect_from_suggestion = False
            self.update()
            return
        self.selected.emit((r.x(), r.y(), r.width(), r.height()))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            # Enter 采纳已废弃（2026-10-09 拍板）：采纳只走右下角按钮
            super().keyPressEvent(ev)

    def _btn_rect(self) -> QRectF:
        """「采纳」按钮矩形（贴选区右下角外侧、钳进视口）——绘制与命中同一来源。"""
        if self._rect is None:
            return QRectF()
        br = accept_btn_rect(self._rect)
        x = min(br.x(), self.width() - BTN_W)
        y = min(br.y(), self.height() - BTN_H)
        return QRectF(max(0.0, x), max(0.0, y), BTN_W, BTN_H)

    # --- AI 建议框 ---
    def apply_suggestion(self, x: float, y: float, w: float, h: float) -> bool:
        """§9.3 建议框入口（镜像 Mobile `setSuggestion`）：预填为当前选区。

        已起手（左键按下过）/框太小/空框 → 不覆盖，返回 False（调用方静默
        丢弃，用户手动拖框）。预填后**拖边界微调 → 点右下角「采纳」提交**；
        框内空白的点按/拖动不改不提交，框外起手即覆盖成手拖选区。
        """
        if self._user_started:
            return False
        if too_small(w, h):
            return False
        r = QRectF(x, y, w, h).normalized()
        if r.isEmpty():
            return False
        self._rect = r
        self._rect_from_suggestion = True   # 建议框：显示手柄与「采纳」按钮
        self.update()
        return True


# ---------- 编排：隐藏 → 抓帧 → 覆盖层 → 裁剪落盘 ----------

class _SuggestBridge(QObject):
    """OCR 工作线程 → 主线程回程桥。

    receiver 是本 QObject（随 CaptureController 建在主线程）：worker 里 emit
    时 Qt 按线程亲和自动队列化（HotkeyManager 同款接线纪律），
    `CaptureController._on_suggest` 恒在主线程执行。
    """

    done = Signal(int, object)   # (代号 gen, 建议框 (l,t,r,b) 帧像素 或 None)

    def __init__(self, on_result):
        super().__init__()
        self._on_result = on_result
        self.done.connect(self._deliver)

    @Slot(int, object)
    def _deliver(self, gen: int, box):
        self._on_result(gen, box)


class CaptureController:
    def __init__(self, on_captured):
        self._on_captured = on_captured  # 收到 (JPEG 路径 str, 逻辑选区)
        self._overlay: CropOverlay | None = None
        self._image: Image.Image | None = None
        self._logical: tuple[int, int] = (0, 0)
        self._busy = False  # 框选中忽略热键（否则二次触发叠两层覆盖层）
        self._t0 = time.monotonic()  # 热键计时基准（日志用）
        # AI 建议框（默认关）：代号防串轮（覆盖层关/新抓帧 → 旧结果作废）
        self._ml_gen = 0
        self._ml_t0 = 0.0
        self._bridge = _SuggestBridge(self._on_suggest)

    def start(self):
        """热键入口（Qt 主线程执行）。"""
        if self._busy:
            return
        self._busy = True
        self._t0 = time.monotonic()
        LOG.info("alt+s → capture start")
        screen = QApplication.instance().primaryScreen()
        self._logical = (screen.size().width(), screen.size().height())
        self._grab()

    def _grab(self):
        # PIL 在本进程（Qt6 per-monitor aware）按物理像素出图；
        # bbox 钳到主屏——多屏时 grab() 会带回整块虚拟屏，覆盖层却只有主屏宽，坐标会错位
        gw, gh = self._logical
        dpr = QApplication.instance().primaryScreen().devicePixelRatio()
        bbox = (0, 0, round(gw * dpr), round(gh * dpr))
        try:
            self._image = ImageGrab.grab(bbox=bbox)
        except OSError:
            try:
                self._image = ImageGrab.grab()  # bbox 越界等退回全屏（单屏恒等）
            except OSError as e:
                # 抓屏偶发失败：复位 _busy（否则热键从此哑火）并留痕，不甩异常
                LOG.error("screen grab failed (both bbox and full): %s", e)
                self._busy = False
                return
        LOG.info("frame grabbed in %.0fms",
                 (time.monotonic() - self._t0) * 1000)
        ov = CropOverlay(self._image, self._logical)
        ov.selected.connect(self._on_selected)
        ov.cancelled.connect(self._on_cancel)
        self._overlay = ov
        ov.show()
        ov.activateWindow()  # 接 ESC
        # AI 建议框（默认关）：覆盖层已先出现，识别在 daemon 线程异步跑，不阻塞
        if settings_store.ml_suggest_enabled():
            self._start_suggest()

    def _start_suggest(self):
        """冻结帧 → 线程里跑离线 OCR + suggest() → 信号回主线程预填选区。"""
        self._ml_gen += 1
        gen = self._ml_gen
        self._ml_t0 = time.monotonic()
        img = self._image

        def work():
            box = None
            try:
                box = suggest_box(img)
            except Exception as e:  # noqa: BLE001 —— ImportError/推理失败一律静默退手动
                LOG.warning("ml suggest failed: %s", e)
            self._bridge.done.emit(gen, box)

        threading.Thread(target=work, daemon=True, name="ml-suggest").start()
        LOG.info("ml suggest started (gen %d)", gen)

    def _on_suggest(self, gen: int, box):
        """建议框回主线程（Slot）：串轮/覆盖层已关/超时/空结果 → 静默丢弃。"""
        if gen != self._ml_gen or self._overlay is None:
            return                                  # 新一轮抓帧或已关 → 作废
        elapsed_ms = (time.monotonic() - self._ml_t0) * 1000
        if elapsed_ms > ML_TIMEOUT_MS:
            LOG.info("ml suggest arrived after %.0fms (> %dms) → dropped",
                     elapsed_ms, ML_TIMEOUT_MS)
            return
        if box is None:
            LOG.info("ml suggest empty → manual drag")   # 不弹提示（用户拍板）
            return
        x, y, w, h = unmap_rect(box, self._logical, self._image.size)
        if self._overlay.apply_suggestion(x, y, w, h):
            LOG.info("ml suggestion prefilled (%.0f, %.0f, %.0f, %.0f) logical",
                     x, y, w, h)
        else:
            LOG.info("ml suggestion discarded (user started or too small)")

    def _on_selected(self, sel):
        x, y, w, h = map_rect(sel, self._logical, self._image.size)
        crop = self._image.crop((x, y, x + w, y + h))
        from datetime import datetime
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = CAPTURE_DIR / f"cap-{stamp}.jpg"
        t_enc = time.monotonic()
        encode_jpeg(crop, dest)
        LOG.info("selected %.0fx%.0f logical → %dx%d px, %s "
                 "(encode %.0fms, total %.0fms from hotkey)",
                 sel[2], sel[3], w, h, dest.name,
                 (time.monotonic() - t_enc) * 1000,
                 (time.monotonic() - self._t0) * 1000)
        self._close()
        self._on_captured(str(dest), sel)

    def _on_cancel(self):
        LOG.info("capture cancelled (esc/right-click) after %.0fms",
                 (time.monotonic() - self._t0) * 1000)
        self._close()

    def _close(self):
        if self._overlay is not None:
            self._overlay.close()
            self._overlay = None
        self._busy = False  # ESC/取消/裁剪完成都回到可触发态
        self._ml_gen += 1   # 覆盖层已关 → 在途的 OCR 结果按代号作废

    def shutdown(self):
        self._close()
