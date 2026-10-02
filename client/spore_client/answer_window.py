"""回答浮窗——04 §四 设计：无边框 + 置顶 + 可拖拽，流式渲染，底部追问。

渲染：markdown 库转 HTML 进 QTextBrowser（MdCard 思路）；
流式节流 200ms 一次重渲（04 §四：别每个 delta 重排 DOM）。
Alt+Z 呼出/收起（与 MV3 hideToggle 同键位，用户拍板）；
每次新截屏落在选区附近（04 §四，越界钳回屏内），Esc 隐藏。
"""

from __future__ import annotations

import markdown
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import CaptionLabel, FluentIcon, PrimaryPushButton, StrongBodyLabel, ToolButton

from .answer.engine import AgentEngine
from .answer.settings import LlmSettings
from .log import get_logger

LOG = get_logger()

STATUS_TEXT = {
    "answering": "回答中…",
    "verifying": "核实中…",
    "searching": "检索中…",
    "done": "",
    "error": "出错了",
    "aborted": "已停止",
}


def _md_html(text: str) -> str:
    # math 扩展在 markdown≥3.6 已移除（装的是 3.9，引用即每次渲染必抛）；
    # MV3 md.js 同样不渲染 LaTeX → 去掉保持两端语义一致
    return markdown.markdown(
        text, extensions=["fenced_code", "tables", "nl2br"])


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


class AnswerWindow(QWidget):
    """单窗复用：一题一会话；新截屏清空重来（04 §五.6 一个 WebView 复用语义）。"""

    followupRequested = Signal(str)  # 主窗接：engine.send_followup

    def __init__(self, settings: LlmSettings, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self._drag_pos = None
        self._engine: AgentEngine | None = None
        self._md_pending = ""
        self._md_dirty = False
        self._think_pending = ""   # think-delta 与正文同走 200ms 节流——
        self._think_dirty = False  # 逐 chunk setPlainText 是 O(n²) 卡顿源

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 12)
        root.setSpacing(8)

        # ---- 标题条（可拖拽） ----
        bar = QHBoxLayout()
        self.title = StrongBodyLabel("Spore 作答")
        self.status = CaptionLabel("")
        self.status.setTextColor("#00b7c3", "#00b7c3")
        bar.addWidget(self.title, 1)
        bar.addWidget(self.status)
        self.pin_btn = ToolButton(FluentIcon.PIN)
        self.pin_btn.setToolTip("置顶开关")
        self.close_btn = ToolButton(FluentIcon.CLOSE)
        bar.addWidget(self.pin_btn)
        bar.addWidget(self.close_btn)
        root.addLayout(bar)

        # ---- 思考块（折叠） ----
        self.think_btn = CaptionLabel("▸ 思考")
        self.think_btn.setCursor(Qt.PointingHandCursor)
        self.think_view = QTextBrowser()
        self.think_view.setMaximumHeight(140)
        self.think_view.setVisible(False)
        self.think_btn.mousePressEvent = lambda e: self._toggle_think()
        root.addWidget(self.think_btn)
        root.addWidget(self.think_view, 0)

        # ---- 正文（流式） ----
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(True)
        root.addWidget(self.body, 1)

        # ---- 工具小票 ----
        self.tools_label = CaptionLabel("")
        self.tools_label.setWordWrap(True)
        self.tools_label.setVisible(False)
        root.addWidget(self.tools_label)

        # ---- 核实条 ----
        self.verify_label = CaptionLabel("")
        self.verify_label.setWordWrap(True)
        self.verify_label.setVisible(False)
        root.addWidget(self.verify_label)

        # ---- 追问行 ----
        foot = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("追问（回车发送）…")
        self.send_btn = PrimaryPushButton("发送")
        self.cancel_btn = ToolButton(FluentIcon.CLOSE)
        self.cancel_btn.setToolTip("停止本回合")
        foot.addWidget(self.input, 1)
        foot.addWidget(self.send_btn)
        foot.addWidget(self.cancel_btn)
        root.addLayout(foot)

        # 200ms 节流重渲定时器（04 §四：流式追加节流）
        self._md_timer = QTimer(self)
        self._md_timer.setInterval(200)
        self._md_timer.timeout.connect(self._flush_md)

        self.resize(460, 560)
        self.pin_btn.setChecked(True)
        self.pin_btn.clicked.connect(self._toggle_pin)
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
        """引擎事件 → UI（引擎在后台线程 emit，Qt 信号自动队列化到主线程）。"""
        self._engine = engine

    def new_turn(self, image_path: str, supplement: str = "",
                 sel: tuple[float, float, float, float] | None = None):
        self._clear()
        if sel is not None:  # 04 §四：出现在选区附近，越界钳回屏内
            screen = QApplication.instance().primaryScreen().size()
            self.move(*place_near(sel, self.width(), self.height(),
                                  screen.width(), screen.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()  # 直接可追问；Esc 仍由本窗 keyPressEvent 接住隐藏
        LOG.info("panel shown at (%d,%d) size=%dx%d sel=%s",
                 self.x(), self.y(), self.width(), self.height(), sel)
        if self._engine is not None:
            self._engine.new_capture_turn(image_path, supplement)

    def on_event(self, ev: dict):
        """统一事件入口（AnswerWindow 自己的事件 + 引擎事件）。"""
        t = ev.get("type")
        if t == "status":
            self.status.setText(STATUS_TEXT.get(ev.get("status", ""), ev.get("text", "")))
        elif t == "answer-start":
            # 占位「读题中…」：先复位管线再填 pending，走 200ms 节流统一渲染
            # （旧代码调用不存在的 _set_body，answer-start 必抛 AttributeError）
            self._start_md()
            self._md_pending = "*读题中…*"
            self._md_dirty = True
        elif t == "answer-delta":
            p = ev.get("preview") or ""
            why = ev.get("why", "")
            self._md_pending = (p + ("\n\n" + why if why else ""))
            self._md_dirty = True
        elif t == "think-delta":
            self._think_pending = ev.get("think", "")
            self._think_dirty = True
            if not self._md_timer.isActive():  # 兜底：verify_only 无 answer-start
                self._md_timer.start()
        elif t == "chat-start":
            self._start_md()
        elif t == "chat-delta":
            self._md_pending = ev.get("total", "")
            self._md_dirty = True
        elif t == "tool":
            self.tools_label.setVisible(True)
            cur = self.tools_label.text()
            brief = ev.get("brief", "")
            chip = ("读取 " if ev.get("name") == "web" else "检索 ") + brief
            self.tools_label.setText((cur + " · " + chip) if cur else chip)
        elif t == "verify-delta":
            self._on_verify(ev)
        elif t == "title":
            self.title.setText(ev.get("title", "Spore 作答"))
        elif t == "error":
            self.status.setText(f"出错：{ev.get('message', '')[:80]}")
            self.verify_label.setVisible(True)
            self.verify_label.setText(ev.get("message", ""))
        elif t == "turn-end":
            self.status.setText("已停止" if ev.get("aborted") else (
                "出错" if ev.get("error") else ""))
            self._flush_md()  # 收尾强制渲最后一次
            self._md_timer.stop()

    # ---------- 内部 ----------
    def _on_verify(self, ev: dict):
        if ev.get("done"):
            verdict = ev.get("verdict", "")
            note = ev.get("note", "")
            mark = {"OK": "✔ 核实通过", "FIX": "⚠ 已修正"}.get(
                verdict, "· 核实完成")
            self.verify_label.setVisible(True)
            self.verify_label.setText(f"{mark}　{note}")
            self.status.setText("")
        elif ev.get("pending"):
            self.verify_label.setVisible(True)
            self.verify_label.setText(ev.get("note", ""))
        elif ev.get("note") is not None and not ev.get("ran"):
            # 流式核实中：正文区尾部追加展示
            self._md_pending = (self._md_pending + "\n\n---\n\n"
                                + ev.get("note", ""))
            self._md_dirty = True

    def _start_md(self):
        self._md_pending = ""
        self._md_dirty = True
        self._think_pending = ""
        self._think_dirty = False
        self.body.clear()
        self.tools_label.clear()
        self.tools_label.setVisible(False)
        self.verify_label.setVisible(False)
        self.think_view.clear()
        self.think_view.setVisible(False)
        self.think_btn.setText("▸ 思考")
        self._md_timer.start()

    def _flush_md(self):
        if self._think_dirty:
            self._think_dirty = False
            self.think_view.setPlainText(self._think_pending)
            if self._think_pending:
                self.think_btn.setText("▾ 思考")
                self.think_view.setVisible(True)
        if not self._md_dirty:
            return
        self._md_dirty = False
        html = _md_html(self._md_pending)
        sb = self.body.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 4
        self.body.setHtml(html)
        if at_bottom:
            sb.setValue(sb.maximum())
        else:
            sb.setValue(sb.value())  # 保持原位（用户上翻时不打断）

    def _toggle_think(self):
        vis = not self.think_view.isVisible()
        self.think_view.setVisible(vis)
        self.think_btn.setText(("▾ " if vis else "▸ ") + "思考")

    def _toggle_pin(self):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, not self.pin_btn.isChecked())
        # setWindowFlag 会隐藏窗口，这里立刻恢复（置顶开关的通用写法）
        self.show()

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
        self._md_pending = ""
        self._md_dirty = False
        self._think_pending = ""
        self._think_dirty = False
        self.title.setText("Spore 作答")
        self.status.setText("")
        self.body.clear()
        self.think_view.clear()
        self.think_view.setVisible(False)
        self.think_btn.setText("▸ 思考")
        self.tools_label.clear()
        self.tools_label.setVisible(False)
        self.verify_label.clear()
        self.verify_label.setVisible(False)
        self.input.clear()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(ev)
