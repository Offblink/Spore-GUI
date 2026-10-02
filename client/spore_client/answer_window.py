"""回答浮窗——照 MV3 `src/content/drawer.js` 重设计（用户 2026-10-02 拍板）。

结构自上而下：标题条（标题·状态药丸·×）→ 题目截图 → 初答 → 工具调用（每条一行）
→ 核实框（chip + markdown 正文）→ 追问输入（↑ 发送 · 🚫 中止）。
追问**追加**在下方，不覆盖初答（同 MV3 renderMsgs 语义）。

纪律：
- **不渲染思考**：`think-delta` 一律忽略（用户点名整个应用抛弃 reason 内容；
  引擎层照跑，只是 UI 不展示、也不给展开入口）。
- **无 pin**：MV3 抽屉没有置顶控件，本窗恒置顶（WindowStaysOnTopHint）。
- 中止按钮 `🚫`，与右上角关闭 × 区分（用户点名）。
- 工具/核实框/状态药丸用**真 widget**（QFrame/QLabel + 样式表），
  才能拿到 border-radius / 悬停色；正文走 markdown → 富文本。
- 流式文本 200ms 节流重渲（04 §四：别每个 delta 重排）。

Alt+Z 呼出/收起（与 MV3 hideToggle 同键位，用户拍板）；新截屏落在选区附近
（04 §四，越界钳回屏内），Esc 隐藏。
"""

from __future__ import annotations

import re

import markdown
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton, StrongBodyLabel

from .answer.engine import AgentEngine
from .answer.settings import LlmSettings
from .log import get_logger

LOG = get_logger()

# MV3 drawer.js:579,631,662 状态文案（紫药丸；出错红药丸另配色）
STATUS_TEXT = {
    "answering": "读题中…",
    "verifying": "核实中…",
    "searching": "检索中…",
    "done": "",
    "error": "出错了",
    "aborted": "已停止",
}

_STATUS_OK = ("QLabel{background:#f4ecff; color:#7c4dbe; border-radius:999px;"
              " padding:2px 10px; font-size:12.5px;}")
_STATUS_ERR = ("QLabel{background:#ffeef1; color:#c81e45; border-radius:999px;"
               " padding:2px 10px; font-size:12.5px;}")
_CHIP = {"skip": ("#f1f2f8", "#7b81a0"), "fix": ("#ffeced", "#d02747"),
         "ok": ("#e7f8ef", "#0f9d58")}
# chip 文案照抄 MV3 drawer.js:686-693
_CHIP_TEXT = {"skip": "⏭ 已跳过 · 初答自评确定", "fix": "❌ 初答有误",
              "ok": "✅ 与初答一致", "pending": "⏳ 待核实"}


def _md_html(text: str) -> str:
    # math 扩展在 markdown≥3.6 已移除（装的是3.9，引用即每次渲染必抛）；
    # MV3 md.js 同样不渲染 LaTeX → 去掉保持两端语义一致
    return markdown.markdown(
        text, extensions=["fenced_code", "tables", "nl2br"])


def _md_div(text: str, color: str, size: int) -> str:
    """markdown → 包一层显式字号/字色（不依赖应用主题调色板）。"""
    return f'<div style="color:{color}; font-size:{size}px;">{_md_html(text)}</div>'


def place_near(sel: tuple[float, float, float, float],
               panel_w: int, panel_h: int,
               screen_w: int, screen_h: int,
               margin: int = 12) -> tuple[int, int]:
    """04 §四：浮窗出现在选区附近，越界钳回屏内。

    横向优先选区右侧，放不下换左侧，两边都放不下贴屏幕左缘（钳位）；
    纵向与选区垂直居中对齐，再钳进屏幕。纯函数，pytest 钉住。
    """
    sx, sy, sw, sh = sel
    y = round(sy + sh / 2 - panel_h / 2)
    y = max(margin, min(screen_h - panel_h - margin, y))
    x = round(sx + sw + margin)
    if x + panel_w > screen_w - margin:
        x = round(sx - panel_w - margin)
    x = max(margin, min(screen_w - panel_w - margin, x))
    return x, y


def _no_head(no: object) -> str:
    """`第N题 ` 前缀（MV3 drawer.js:982-985：no 去掉非字母数字）。"""
    digits = re.sub(r"\D", "", str(no or ""))
    return f"第{digits}题 " if digits else ""


def _mini_btn(text: str, tip: str) -> QPushButton:
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFixedSize(30, 30)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        "QPushButton{background:transparent; border:none; font-size:15px;"
        " color:#a3a8c2; border-radius:6px;}"
        "QPushButton:hover{background:#fdecef; color:#d02747;"
        " border-radius:6px;}")
    return b


def _sec_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("QLabel{color:#9aa0bb; font-size:11.5px; font-weight:600;}")
    return lab


class AnswerWindow(QWidget):
    """单窗复用：一题一会话；新截屏清空重来（04 §五.6 一个 WebView 复用语义）。"""

    followupRequested = Signal(str)  # 主窗接：engine.send_followup

    def __init__(self, settings: LlmSettings, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self._drag_pos = None
        self._engine: AgentEngine | None = None
        self._blocks: list[dict] = []   # 追加式消息块（widget + 数据都在里面）
        self._cur: dict | None = None   # 正在流式的块
        self._dirty: set[int] = set()   # 待重渲的块（id）
        self._shot: QLabel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 标题条（可拖拽；无 pin —— MV3 抽屉无置顶控件） ----
        bar = QHBoxLayout()
        bar.setContentsMargins(16, 10, 8, 8)
        bar.setSpacing(8)
        self.title = StrongBodyLabel("Spore")
        self.status = QLabel("")
        self.status.setStyleSheet(_STATUS_OK)
        self.status.setVisible(False)
        self.close_btn = _mini_btn("×", "关闭（Alt+Z 可再呼出）")
        bar.addWidget(self.title, 1)
        bar.addWidget(self.status)
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

        # ---- 内容滚动区：截图 + 消息块 ----
        self._content = QWidget()
        self._content.setObjectName("contentBox")
        self._content.setStyleSheet("#contentBox{background:#ffffff;}")
        self._blocks_box = QVBoxLayout(self._content)
        self._blocks_box.setContentsMargins(16, 4, 16, 12)
        self._blocks_box.setSpacing(10)
        self._shot = self._make_shot()
        self._blocks_box.addWidget(self._shot)
        self._blocks_box.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._content)
        self._scroll.setStyleSheet("QScrollArea{background:#ffffff; border:none;}")
        root.addWidget(self._scroll, 1)

        # ---- 追问行 ----
        foot = QHBoxLayout()
        foot.setContentsMargins(12, 8, 12, 12)
        foot.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("接着问…（Enter 发送）")
        self.send_btn = PrimaryPushButton("↑")
        self.send_btn.setFixedSize(40, 40)
        self.send_btn.setToolTip("发送")
        self.cancel_btn = _mini_btn("🚫", "停止本回合")
        foot.addWidget(self.input, 1)
        foot.addWidget(self.send_btn)
        foot.addWidget(self.cancel_btn)
        root.addLayout(foot)

        self._md_timer = QTimer(self)
        self._md_timer.setInterval(200)
        self._md_timer.timeout.connect(self._flush)

        self.resize(460, 560)
        self.close_btn.clicked.connect(self.hide)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.cancel_btn.clicked.connect(self._cancel)

    # ---------- 拖拽 ----------
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_pos is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None

    # ---------- 对外 ----------
    def attach_engine(self, engine: AgentEngine):
        """引擎事件 → UI（引擎在后台线程 emit，主窗 Signal 队列回主线程）。"""
        self._engine = engine

    def new_turn(self, image_path: str, supplement: str = "",
                 sel: tuple[float, float, float, float] | None = None):
        self._clear()
        if sel is not None:  # 04 §四：出现在选区附近，越界钳回屏内
            screen = QApplication.instance().primaryScreen().size()
            self.move(*place_near(sel, self.width(), self.height(),
                                  screen.width(), screen.height()))
        self._show_shot(image_path)
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()  # 直接可追问；Esc 仍由本窗 keyPressEvent 接住隐藏
        LOG.info("panel shown at (%d,%d) size=%dx%d sel=%s",
                 self.x(), self.y(), self.width(), self.height(), sel)
        if self._engine is not None:
            self._engine.new_capture_turn(image_path, supplement)

    def on_event(self, ev: dict):
        """统一事件入口（主窗 engineEvent 队列化后调）。"""
        t = ev.get("type")
        if t == "think-delta":
            return  # reason 内容整个应用不展示（用户拍板）；引擎层照跑
        if t == "status":
            self._set_status(ev.get("status", ""), ev.get("text", ""))
        elif t == "answer-start":
            self._cur = self._append_block("answer")
            self._cur["ans"] = ""
            self._cur["placeholder"] = True
            self._dirty.add(id(self._cur))
            self._start_timer()
        elif t == "answer-delta":
            if self._cur is None:
                self._cur = self._append_block("answer")
            self._cur.update({
                "no": ev.get("no", ""), "title": ev.get("title", ""),
                "ans": ev.get("ans", ""), "why": ev.get("why", ""),
                "placeholder": False,
            })
            self._dirty.add(id(self._cur))
            self._start_timer()
        elif t == "tool":
            if self._cur is not None:
                label = "读取" if ev.get("name") == "web" else "检索"
                self._add_tool(self._cur, f"{label} {ev.get('brief', '')}")
        elif t == "verify-delta":
            if self._cur is not None:
                self._on_verify(self._cur, ev)
        elif t == "chat-start":
            self._cur = self._append_block("chat")
            self._cur["text"] = ""
            self._dirty.add(id(self._cur))
            self._start_timer()
        elif t == "chat-delta":
            if self._cur is not None:
                self._cur["text"] = ev.get("total", "")
                self._dirty.add(id(self._cur))
                self._start_timer()
        elif t == "title":
            self.title.setText(ev.get("title", "") or "Spore")
        elif t == "error":
            self._set_status("error", "")
            if self._cur is not None:
                self._cur["err"] = str(ev.get("message", ""))[:400]
                self._paint_err(self._cur)
        elif t == "turn-end":
            self._set_status("aborted" if ev.get("aborted") else
                             ("error" if ev.get("error") else "done"), "")
            self._md_timer.stop()
            self._flush()  # 收尾强制渲最后一次
            self._cur = None

    # ---------- 消息块 ----------
    def _make_shot(self) -> QLabel:
        lab = QLabel()
        lab.setObjectName("shotLabel")
        lab.setAlignment(Qt.AlignCenter)
        lab.setMaximumHeight(200)
        lab.setVisible(False)
        lab.setStyleSheet("#shotLabel{border:1px solid #e6e8f2;"
                          " border-radius:12px; background:#f7f8fc;}")
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)  # 截图不可点开
        return lab

    def _show_shot(self, path: str):
        pm = QPixmap(path)
        if pm.isNull():
            self._shot.setVisible(False)
            return
        avail = max(120, self.width() - 40)
        self._shot.setPixmap(pm.scaled(avail, 200, Qt.KeepAspectRatio,
                                       Qt.SmoothTransformation))
        self._shot.setVisible(True)

    def _reset_layout(self):
        while self._blocks_box.count():
            item = self._blocks_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._blocks = []
        self._cur = None
        self._dirty.clear()
        self._shot = self._make_shot()
        self._blocks_box.addWidget(self._shot)
        self._blocks_box.addStretch(1)

    def _append_block(self, kind: str) -> dict:
        """建一个消息块 widget，插在 stretch 之前（MV3 .msg.bot 左粉竖条）。"""
        frame = QFrame()
        frame.setObjectName("msgBlock")
        frame.setStyleSheet(
            "#msgBlock{border-left:3px solid #ec4899; padding:2px 0 2px 12px;}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        b: dict = {"kind": kind, "frame": frame, "tools_box": None,
                   "verify_frame": None, "chip": None, "note": None,
                   "verify_btn": None, "ans_lbl": None, "why_lbl": None,
                   "text_lbl": None, "err_lbl": None, "tools": [],
                   "ans": "", "why": "", "text": "", "no": "", "title": "",
                   "err": "", "verify": None, "verify_on": False,
                   "placeholder": False}

        if kind == "answer":
            lay.addWidget(_sec_label("初答"))
            b["ans_lbl"] = self._md_label()
            lay.addWidget(b["ans_lbl"])
            b["why_lbl"] = self._md_label()
            b["why_lbl"].setVisible(False)
            lay.addWidget(b["why_lbl"])
            b["tools_box"] = QVBoxLayout()
            b["tools_box"].setSpacing(4)
            lay.addLayout(b["tools_box"])
            b["verify_btn"] = QPushButton("🔍 核实一下")
            b["verify_btn"].setCursor(Qt.PointingHandCursor)
            b["verify_btn"].setVisible(False)
            b["verify_btn"].setStyleSheet(
                "QPushButton{background:#f1f3fb; color:#4a4f6b; border:none;"
                " border-radius:10px; padding:6px 14px; font-weight:600;}"
                "QPushButton:hover{background:#e8ebf7;}")
            b["verify_btn"].clicked.connect(
                lambda _=False, blk=b: self._do_verify(blk))
            lay.addWidget(b["verify_btn"])
            b["verify_frame"], b["chip"], b["note"] = self._make_verify()
            b["verify_frame"].setVisible(False)
            lay.addWidget(b["verify_frame"])
        else:  # chat：MV3 drawer.js:1012-1018 tools 排在正文之前
            b["tools_box"] = QVBoxLayout()
            b["tools_box"].setSpacing(4)
            lay.addLayout(b["tools_box"])
            lay.addWidget(_sec_label("追问"))
            b["text_lbl"] = self._md_label()
            lay.addWidget(b["text_lbl"])

        b["err_lbl"] = QLabel("")
        b["err_lbl"].setWordWrap(True)
        b["err_lbl"].setStyleSheet(
            "QLabel{color:#c81e45; font-size:14px; background:#ffeef1;"
            " border-radius:8px; padding:6px 8px;}")
        b["err_lbl"].setVisible(False)
        lay.addWidget(b["err_lbl"])

        idx = self._blocks_box.count() - 1  # stretch 在最后
        self._blocks_box.insertWidget(idx, frame)
        self._blocks.append(b)
        return b

    def _md_label(self) -> QLabel:
        lab = QLabel()
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.TextFormat.RichText)
        lab.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        return lab

    def _make_verify(self) -> tuple[QFrame, QLabel, QLabel]:
        """核实框（MV3 drawer.js:797-981）：头(核实+chip) + 正文 note。"""
        box = QFrame()
        box.setObjectName("verifyBox")
        box.setStyleSheet(
            "#verifyBox{background:#fbfcff; border:1px solid #e6e8f2;"
            " border-radius:10px;}")
        v = QVBoxLayout(box)
        v.setContentsMargins(11, 9, 11, 9)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(_sec_label("核实"))
        chip = QLabel("")
        chip.setVisible(False)
        head.addWidget(chip)
        head.addStretch(1)
        v.addLayout(head)
        note = QLabel("")
        note.setWordWrap(True)
        note.setTextFormat(Qt.TextFormat.RichText)
        note.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        note.setVisible(False)
        v.addWidget(note)
        return box, chip, note

    def _add_tool(self, blk: dict, text: str):
        """每条工具独占一行（用户点名「换行的工具调用」），圆角小票。"""
        blk["tools"].append(text)
        chip = QFrame()
        chip.setObjectName("toolChip")
        chip.setStyleSheet(
            "#toolChip{background:#f6f7fc; border-radius:7px;}")
        h = QHBoxLayout(chip)
        h.setContentsMargins(8, 3, 8, 3)
        h.setSpacing(5)
        icon = QLabel("⌕")
        icon.setStyleSheet("QLabel{color:#ec4899; background:transparent;"
                           " font-size:13px;}")
        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet("QLabel{color:#7b81a0; background:transparent;"
                           " font-size:13px;}")
        h.addWidget(icon)
        h.addWidget(body, 1)
        blk["tools_box"].addWidget(chip)

    def _do_verify(self, blk: dict):
        """MV3 drawer.js:999-1009：点掉即消失 → 发 verify-now。"""
        if self._engine is None:
            return
        if self._engine.verify_only():
            blk["verify_btn"].setVisible(False)

    # ---------- 核实 ----------
    def _on_verify(self, blk: dict, ev: dict):
        verify = blk.get("verify")
        if not isinstance(verify, dict):  # 块里预置的是 None，setdefault 不生效
            verify = {}
            blk["verify"] = verify
        if ev.get("pending"):
            verify.update({"kind": "pending", "note": ev.get("note", ""),
                           "done": True})
            blk["verify_btn"].setVisible(True)
        elif ev.get("done"):
            skipped = bool(ev.get("skipped"))
            verdict = str(ev.get("verdict", "") or "")
            verify.update({
                "kind": "skipped" if skipped else (
                    "fix" if verdict == "FIX" else "ok"),
                "verdict": verdict, "note": ev.get("note", ""),
                "done": True,
            })
            if not skipped:
                blk["verify_btn"].setVisible(False)
        else:  # 流式核实中
            verify.update({"kind": "pending", "note": ev.get("note", ""),
                           "done": False})
            blk["verify_btn"].setVisible(False)
        self._paint_verify(blk)

    def _paint_verify(self, blk: dict):
        verify = blk.get("verify") or {}
        if not verify:
            blk["verify_frame"].setVisible(False)
            return
        kind = verify.get("kind", "pending")
        if kind not in _CHIP_TEXT:
            kind = "pending"
        bg, fg = _CHIP.get(kind, _CHIP["skip"])
        chip = blk["chip"]
        chip.setText(_CHIP_TEXT[kind])
        chip.setStyleSheet(
            f"QLabel{{background:{bg}; color:{fg}; border-radius:999px;"
            f" padding:1px 8px; font-size:11.5px;}}")
        chip.setVisible(True)
        note = blk["note"]
        text = str(verify.get("note") or "")
        if text:
            note.setText(_md_div(text, "#3d4260", 15))
            note.setVisible(True)
        else:
            note.setVisible(False)
        blk["verify_frame"].setVisible(True)

    # ---------- 状态 / 文本 ----------
    def _set_status(self, status: str, text: str):
        label = STATUS_TEXT.get(status, text or "")
        self.status.setText(label)
        self.status.setVisible(bool(label))
        if status in ("error", "aborted"):
            self.status.setStyleSheet(_STATUS_ERR)
        else:
            self.status.setStyleSheet(_STATUS_OK)

    def _start_timer(self):
        if not self._md_timer.isActive():
            self._md_timer.start()

    def _flush(self):
        if not self._dirty:
            return
        ids = self._dirty
        self._dirty = set()
        bar = self._scroll.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 8
        for blk in self._blocks:
            if id(blk) in ids:
                self._paint(blk)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _paint(self, blk: dict):
        if blk["kind"] == "answer":
            head = _no_head(blk.get("no"))
            body = str(blk.get("ans") or "")
            if not body and blk.get("placeholder"):
                html = '<div style="color:#9aa0bb;"><i>读题中…</i></div>'
            else:
                html = _md_div(head + body, "#1a1d2e", 17)
            blk["ans_lbl"].setText(html)
            why = str(blk.get("why") or "")
            if why:
                blk["why_lbl"].setText(_md_div(why, "#4a4f6b", 15))
                blk["why_lbl"].setVisible(True)
            else:
                blk["why_lbl"].setVisible(False)
        else:
            blk["text_lbl"].setText(
                _md_div(str(blk.get("text") or ""), "#14172a", 15)
                if blk.get("text") else "")

    def _paint_err(self, blk: dict):
        if blk.get("err"):
            blk["err_lbl"].setText(blk["err"])
            blk["err_lbl"].setVisible(True)

    # ---------- 交互 ----------
    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.followupRequested.emit(text)

    def _cancel(self):
        if self._engine is not None:
            self._engine.cancel()

    def _clear(self):
        self._md_timer.stop()
        self.title.setText("Spore")
        self.status.setText("")
        self.status.setVisible(False)
        self.status.setStyleSheet(_STATUS_OK)
        self.input.clear()
        self._reset_layout()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(ev)
