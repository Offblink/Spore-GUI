"""回答浮窗——照 MV3 `src/content/drawer.js` 重设计（用户 2026-10-02 拍板）。

结构自上而下：标题条（💬 会话列表 · ★ 收藏 · 标题·状态药丸·×）→ 题目截图 → 初答
→ 工具调用（每条一行）→ 核实框（chip + markdown 正文）→ 追问输入（↑ 发送 · 🚫 中止）。
追问**追加**在下方，不覆盖初答（同 MV3 renderMsgs 语义）。
用户自己发的追问（`chat-start.text` / 截屏补充）画成用户气泡（MV3 `.utext`：
纯文本不走 markdown、底 `#f2f4fb`）。

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

import json
import re
from pathlib import Path

import markdown
from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFontMetrics, QPixmap
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
from qfluentwidgets import (
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    StrongBodyLabel,
)

from .answer.engine import AgentEngine
from .answer.session import Msg, Session
from .answer.settings import LlmSettings
from .api import ApiError, NetworkError
from .log import get_logger
from .records import _InputDialog

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

_PLACEHOLDER = "接着问…（Enter 发送）"
_HIST_PLACEHOLDER = "历史会话（只读）· 按 Alt+S 开始新题"


def _fmt_stamp(value) -> str:
    """MV3 review.js:37-42 fmtStamp → `MM-DD HH:mm`。"""
    s = str(value or "")
    return s[5:16] if len(s) >= 16 else s[:16]


def _star_style(fav: bool, size: int = 14) -> str:
    """★ 必须自给 color（字形本身无上色）：收藏粉 / 未收藏灰，hover #db2777。"""
    base = "#ec4899" if fav else "#b3b8cd"
    return (f"QPushButton{{background:transparent; border:none; color:{base};"
            f" font-size:{size}px; border-radius:6px;}}"
            "QPushButton:hover{background:#ffeef7; color:#db2777;}")


def _msgs_of(article: dict) -> list:
    """ArticleVO.messages（后端 toVo 顶层直带）；兼容详情 content.messages/JSON 串。"""
    msgs = article.get("messages")
    if isinstance(msgs, list):
        return msgs
    content = article.get("content")
    if isinstance(content, dict):
        msgs = content.get("messages")
        return msgs if isinstance(msgs, list) else []
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except (ValueError, TypeError):
            return []
        msgs = data.get("messages") if isinstance(data, dict) else None
        return msgs if isinstance(msgs, list) else []
    return []


_MSG_FIELDS = ("role", "kind", "text", "no", "title", "ans", "why",
               "verifyVerdict", "verifyNote", "hasImage", "imagePath",
               "verifyRan", "verifySkipped", "verifyPending", "tools", "ts")


def _session_from_article(article: dict, msgs: list) -> Session:
    """ArticleVO → 可接续的 Session：backend_id 带上，turn-end 落库走 PUT（§8-2）。

    只搬 Msg.to_dict 会落库的字段（think 不渲染也不进上下文，不搬）；
    缺键走 Msg 默认值，缺 role 的畸形行直接跳过。
    """
    sess = Session(
        title=str(article.get("title") or "新会话"),
        backend_id=str(article.get("id") or ""),
        fav=bool(article.get("fav")),
        status=str(article.get("status") or ""),
    )
    for m in msgs:
        if not isinstance(m, dict) or "role" not in m:
            continue
        kw = {k: m[k] for k in _MSG_FIELDS if k in m and m[k] not in (None, "")}
        sess.messages.append(Msg(**kw))
    return sess


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


def _mini_btn(text: str, tip: str, accent: bool = True) -> QPushButton:
    """顶栏小按钮。默认 accent hover（#ffeef7/#ec4899，同 MV3 💬/★）；
    关闭 × 与中止 🚫 传 accent=False 保留危险红 hover。"""
    hover_bg, hover_fg = ("#ffeef7", "#ec4899") if accent else ("#fdecef", "#d02747")
    b = QPushButton(text)
    b.setToolTip(tip)
    b.setFixedSize(30, 30)
    b.setCursor(Qt.PointingHandCursor)
    b.setStyleSheet(
        "QPushButton{background:transparent; border:none; font-size:15px;"
        " color:#a3a8c2; border-radius:6px;}"
        f"QPushButton:hover{{background:{hover_bg}; color:{hover_fg};"
        " border-radius:6px;}}")
    return b


def _sec_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet("QLabel{color:#9aa0bb; font-size:11.5px; font-weight:600;}")
    return lab


class _SessionsTask(QThread):
    """💬 列表取数走后台线程（主线程不发网络请求）。"""

    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api

    def run(self):
        try:
            data = self.api.articles(page=1, size=60)
            rows = data.get("list", []) if isinstance(data, dict) else []
            self.ok.emit(list(rows))
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


class _SessionRow(QFrame):
    """💬 列表行：★ 标题/时间 + hover 才显的 ✎ ×（与记录页会话行同交互，§8-6）。"""

    opened = Signal(object)               # art → 打开会话
    renameRequested = Signal(object)      # art
    deleteRequested = Signal(object)      # art
    favToggled = Signal(object, object)   # art, row（行自己换星色）

    def __init__(self, art: dict, avail: int, parent=None):
        super().__init__(parent)
        self._art = art
        self.setObjectName("sessRow")
        self.setStyleSheet("#sessRow{border-radius:10px;}"
                           "#sessRow:hover{background:#f5f7fd;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 6, 6)
        h.setSpacing(8)
        title = str(art.get("title") or "新会话")
        t = QLabel(QFontMetrics(QApplication.font()).elidedText(
            title, Qt.TextElideMode.ElideRight, avail))
        t.setStyleSheet("QLabel{color:#2b2f4a; font-size:14px;"
                        " background:transparent;}")
        ts = QLabel(_fmt_stamp(art.get("updateTime")))
        ts.setStyleSheet("QLabel{color:#a3a8c2; font-size:11.5px;"
                         " background:transparent;}")
        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(t)
        col.addWidget(ts)
        self.star = QPushButton("★")
        self.star.setFixedSize(24, 24)
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.setStyleSheet(_star_style(bool(art.get("fav"))))
        self.star.clicked.connect(
            lambda: self.favToggled.emit(self._art, self))
        self.rename_btn = QPushButton("✎")   # U+270E
        self.rename_btn.setFixedSize(24, 24)
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.setToolTip("重命名")
        self.rename_btn.clicked.connect(
            lambda: self.renameRequested.emit(self._art))
        self.del_btn = QPushButton("×")       # U+00D7
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.setToolTip("删除")
        self.del_btn.clicked.connect(
            lambda: self.deleteRequested.emit(self._art))
        for b in (self.rename_btn, self.del_btn):
            b.setStyleSheet(
                "QPushButton{background:transparent; border:none; font-size:14px;"
                " color:#a3a8c2; border-radius:6px;}"
                "QPushButton:hover{background:#eef1fa; color:#4a4f6b;}")
        self.del_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:15px;"
            " color:#a3a8c2; border-radius:6px;}"
            "QPushButton:hover{background:#fdecef; color:#d02747;}")
        h.addWidget(self.star)
        h.addLayout(col, 1)
        h.addWidget(self.rename_btn)
        h.addWidget(self.del_btn)
        self._hover = False
        self._apply()

    def set_fav(self, on: bool):
        self.star.setStyleSheet(_star_style(on))

    def enterEvent(self, ev):
        self._hover = True
        self._apply()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._apply()
        super().leaveEvent(ev)

    def _apply(self):
        self.rename_btn.setVisible(self._hover)
        self.del_btn.setVisible(self._hover)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.opened.emit(self._art)
        super().mousePressEvent(ev)


class AnswerWindow(QWidget):
    """单窗复用：一题一会话；新截屏清空重来（04 §五.6 一个 WebView 复用语义）。"""

    followupRequested = Signal(str)  # 主窗接：engine.send_followup

    def __init__(self, settings: LlmSettings, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self._drag_pos = None
        self._engine: AgentEngine | None = None
        self._api = None                      # attach_api() 注入，未注入则安全跳过
        self._current_article_id: str | None = None
        self._current_fav = False
        self._readonly = False                # 正在看历史会话（追问禁用）
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
        # MV3 drawer.js:255-263 顶栏顺序：💬 会话 · ★ 收藏 · 标题 · 状态 · ×
        self.sessions_btn = _mini_btn("💬", "会话列表")
        self.fav_btn = _mini_btn("★", "收藏")
        self.fav_btn.setStyleSheet(_star_style(False))
        self.close_btn = _mini_btn("×", "关闭（Alt+Z 可再呼出）", accent=False)
        bar.addWidget(self.sessions_btn)
        bar.addWidget(self.fav_btn)
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
        self.sessions_btn.clicked.connect(self._toggle_sessions)
        self.fav_btn.clicked.connect(self._toggle_fav)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.cancel_btn.clicked.connect(self._cancel)
        self._build_sessions_popup()

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
        if supplement:
            self._append_user(supplement)  # 截屏补充也画成用户气泡
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
            text = str(ev.get("text") or "")
            if text:
                # 用户自己发的那条：先画气泡，再画助理回复（MV3 顺序）
                self._append_user(text)
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
        else:
            avail = max(120, self.width() - 40)
            self._shot.setPixmap(pm.scaled(avail, 200, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
            self._shot.setVisible(True)
        # 诊断（§8-7）：面板截图空白时先看这三列——文件没读到 / 没设上 / 没可见
        LOG.info("shot path=%s null=%s visible=%s", path, pm.isNull(),
                 self._shot.isVisible())

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
        """建一个消息块 widget，插在 stretch 之前。

        assistant 块 = MV3 `.msg.bot` 左粉竖条；user 块 = `.utext` 气泡（无竖条）。
        """
        frame = QFrame()
        if kind == "user":
            frame.setObjectName("userBubble")
            frame.setStyleSheet(
                "#userBubble{background:#f2f4fb; border-radius:12px;}")
        else:
            frame.setObjectName("msgBlock")
            frame.setStyleSheet(
                "#msgBlock{border-left:3px solid #ec4899;"
                " padding:2px 0 2px 12px;}")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        b: dict = {"kind": kind, "frame": frame, "tools_box": None,
                   "verify_frame": None, "chip": None, "note": None,
                   "verify_btn": None, "ans_lbl": None, "why_lbl": None,
                   "text_lbl": None, "user_lbl": None, "err_lbl": None,
                   "tools": [],
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
        elif kind == "chat":  # MV3 drawer.js:1012-1018 tools 排在正文之前
            b["tools_box"] = QVBoxLayout()
            b["tools_box"].setSpacing(4)
            lay.addLayout(b["tools_box"])
            lay.addWidget(_sec_label("追问"))
            b["text_lbl"] = self._md_label()
            lay.addWidget(b["text_lbl"])
        else:  # user 气泡：MV3 div.utext —— 纯文本，不走 markdown
            lay.setContentsMargins(10, 8, 10, 8)
            b["user_lbl"] = QLabel()
            b["user_lbl"].setWordWrap(True)
            b["user_lbl"].setTextFormat(Qt.TextFormat.PlainText)
            b["user_lbl"].setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            b["user_lbl"].setStyleSheet(
                "QLabel{color:#1a1d2e; font-size:14.5px; background:transparent;}")
            lay.addWidget(b["user_lbl"])

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
        elif blk["kind"] == "chat":
            blk["text_lbl"].setText(
                _md_div(str(blk.get("text") or ""), "#14172a", 15)
                if blk.get("text") else "")
        elif blk["user_lbl"] is not None:  # 用户气泡：纯文本
            blk["user_lbl"].setText(str(blk.get("text") or ""))

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
        self._set_readonly(False)
        self._current_article_id = None   # 新题未落库前 ★ 没有对象
        self._current_fav = False
        self._sync_fav_btn()
        if getattr(self, "_pop", None) is not None:
            self._pop.setVisible(False)
        self._reset_layout()

    # ---------- 会话：💬 列表 / ★ 收藏 / 历史只读 ----------
    def attach_api(self, api) -> None:
        """主窗 ctor 调；💬 列表与 ★ 收藏要打后端。未注入时相关路径安全跳过。"""
        self._api = api

    def set_current_article(self, article_id: str | None,
                            fav: bool = False) -> None:
        """落库后主窗调（传后端 id 与收藏态）；开新题时主窗传 None。"""
        self._current_article_id = article_id or None
        self._current_fav = bool(fav)
        self._sync_fav_btn()

    def _sync_fav_btn(self):
        self.fav_btn.setStyleSheet(_star_style(self._current_fav))
        self.fav_btn.setToolTip("取消收藏" if self._current_fav else "收藏")

    def _toast(self, ok: bool, title: str, content: str, ms: int = 2200):
        fn = InfoBar.success if ok else InfoBar.warning
        fn(title, content, parent=self, duration=ms,
           position=InfoBarPosition.TOP)

    def _toggle_fav(self):
        if self._api is None or not self._current_article_id:
            self._toast(False, "还没有会话", "先按 Alt+S 截一道题，落库后才能收藏")
            return
        want = 0 if self._current_fav else 1
        try:
            self._api.update_article(self._current_article_id, fav=want)
        except (ApiError, NetworkError) as e:
            self._toast(False, "收藏失败", str(e), 2600)
            return
        self._current_fav = want == 1
        self._sync_fav_btn()
        self._toast(True, "已收藏" if self._current_fav else "已取消收藏",
                    "会话列表里会标出这颗星" if self._current_fav else "已取消标记")

    def _set_readonly(self, on: bool):
        """禁追问：历史会话没被引擎收编时（引擎正忙，load_session 拒绝）才只读。"""
        self._readonly = on
        self.input.setEnabled(not on)
        self.send_btn.setEnabled(not on)
        self.input.setPlaceholderText(
            _HIST_PLACEHOLDER if on else _PLACEHOLDER)

    def _append_user(self, text: str) -> dict:
        blk = self._append_block("user")
        blk["text"] = str(text)
        self._paint(blk)
        return blk

    # ---- 💬 会话列表浮层（MV3 drawer #listpop：点外/Esc/再点 💬 关闭） ----
    def _build_sessions_popup(self):
        self._pop = QFrame(self)
        self._pop.setObjectName("sessionPop")
        self._pop.setStyleSheet(
            "#sessionPop{background:#ffffff; border:1px solid #e6e8f2;"
            " border-radius:16px;}")
        self._pop.setVisible(False)
        lay = QVBoxLayout(self._pop)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(_sec_label("会话"))
        head.addStretch(1)
        self._pop_reload = _mini_btn("↻", "刷新列表")
        head.addWidget(self._pop_reload)
        lay.addLayout(head)
        self._pop_scroll = QScrollArea()
        self._pop_scroll.setWidgetResizable(True)
        self._pop_scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        host.setStyleSheet("QWidget{background:transparent;}")
        self._pop_box = QVBoxLayout(host)
        self._pop_box.setContentsMargins(0, 0, 0, 0)
        self._pop_box.setSpacing(2)
        self._pop_box.addStretch(1)
        self._pop_scroll.setWidget(host)
        lay.addWidget(self._pop_scroll, 1)
        self._pop_reload.clicked.connect(self._load_sessions)
        self._sess_task: _SessionsTask | None = None

    def _toggle_sessions(self):
        if self._pop.isVisible():
            self._pop.setVisible(False)
            return
        h = max(180, min(int(self.height() * 0.64), 420))
        self._pop.setGeometry(12, 44, max(220, self.width() - 24), h)
        self._pop.raise_()
        self._pop.setVisible(True)
        self._load_sessions()

    def _load_sessions(self):
        if self._api is None:
            self._render_sessions([], "未连接后端")
            return
        if self._sess_task is not None and self._sess_task.isRunning():
            return
        self._sess_task = _SessionsTask(self._api, self)
        self._sess_task.ok.connect(self._render_sessions)
        self._sess_task.failed.connect(lambda m: self._render_sessions([], m))
        self._sess_task.start()

    def _clear_pop_box(self):
        while self._pop_box.count():
            item = self._pop_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self._pop_box.addStretch(1)

    def _render_sessions(self, rows: list, err: str = ""):
        self._clear_pop_box()
        if err or not rows:
            tip = QLabel(err or "还没有会话\n按 Alt+S 框选截图提问")
            tip.setStyleSheet("QLabel{color:#a3a8c2; font-size:13.5px;"
                              " background:transparent;}")
            tip.setWordWrap(True)
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._pop_box.insertWidget(0, tip)
            return
        # 行内预留：pop 边距 24 + 行边距 14 + ★✎× 72 + 间距 24 ≈ 150
        avail = max(120, self.width() - 24 - 16 - 110)
        idx = self._pop_box.count() - 1
        for art in rows:
            row = _SessionRow(art, avail)
            row.opened.connect(self._open_from_list)
            row.renameRequested.connect(self._rename_row)
            row.deleteRequested.connect(self._delete_row)
            row.favToggled.connect(self._row_fav)
            self._pop_box.insertWidget(idx, row)

    def _row_fav(self, art: dict, row: _SessionRow):
        if self._api is None:
            return
        want = 0 if art.get("fav") else 1
        try:
            self._api.update_article(str(art.get("id") or ""), fav=want)
        except (ApiError, NetworkError) as e:
            self._toast(False, "收藏失败", str(e), 2600)
            return
        art["fav"] = want
        row.set_fav(want == 1)
        if str(art.get("id") or "") == self._current_article_id:
            self._current_fav = want == 1
            self._sync_fav_btn()
        self._toast(True, "已收藏" if want else "已取消收藏",
                    "会话列表里会标出这颗星" if want else "已取消标记")

    def _rename_row(self, art: dict):
        """行内 ✎ 重命名——与记录页同款对话框，成功后刷新列表（§8-6）。"""
        if self._api is None:
            return
        art_id = str(art.get("id") or "")
        title = str(art.get("title") or "新会话")
        new = _InputDialog.get_text("重命名会话", title, self.window())
        if not new or new == title:
            return
        try:
            self._api.update_article(art_id, title=new)
        except (ApiError, NetworkError) as e:
            self._toast(False, "重命名失败", str(e), 2600)
            return
        if art_id and art_id == self._current_article_id:
            self.title.setText(new)
        self._load_sessions()

    def _delete_row(self, art: dict):
        """行内 × 删除——确认后刷新；删的是正看着的会话就回空面板（§8-6）。"""
        if self._api is None:
            return
        art_id = str(art.get("id") or "")
        title = str(art.get("title") or "新会话")
        box = MessageBox("删除这个会话？",
                         f"确定删除「{title}」吗？截图、回答与核实记录会一并"
                         "删除，不可恢复。", self.window())
        if not box.exec():
            return
        try:
            self._api.delete_article(art_id)
        except (ApiError, NetworkError) as e:
            self._toast(False, "删除失败", str(e), 2600)
            return
        if art_id and art_id == self._current_article_id:
            if self._engine is not None:
                self._engine.load_session(Session())  # 引擎别再指着已删会话
            keep = self._pop.isVisible()
            self._clear()   # 正看着的会话被删 → 回空面板
            if keep:
                self._pop.setVisible(True)
        self._load_sessions()

    def _open_from_list(self, art: dict):
        self._pop.setVisible(False)
        self.load_history(art)

    # ---- 历史视图（可接续，§8-2） ----
    def _resolve_shot(self, raw: str) -> str:
        """题图路径 → 本机存在才显示；相对路径按题库目录拼（§8-5 同根）。"""
        if not raw:
            return ""
        if self._api is not None:
            return self._api.resolve_attachment(raw)
        p = Path(raw)  # 未接后端（纯本地路径）时也别把绝对路径丢了
        return str(p) if p.is_file() else ""

    def load_history(self, article: dict) -> None:
        """渲染一条历史会话，并收编给引擎——下一条追问在其上接续（§8-2）。

        引擎正忙时收编失败 → 退回只读（与旧行为一致），不把两场对话串线。
        """
        self._clear()
        self._current_article_id = str(article.get("id") or "") or None
        self._current_fav = bool(article.get("fav"))
        self._sync_fav_btn()
        self.title.setText(str(article.get("title") or "Spore"))
        shot = self._resolve_shot(str(article.get("attachmentPath") or ""))
        if shot:
            self._show_shot(shot)
        msgs = _msgs_of(article)
        for m in msgs:
            self._add_history_msg(m)
        adopted = False
        if self._engine is not None:
            adopted = self._engine.load_session(
                _session_from_article(article, msgs))
        self._set_readonly(not adopted)
        self.show()
        self.raise_()
        self.activateWindow()
        LOG.info("history loaded id=%s msgs=%d fav=%s adopted=%s",
                 self._current_article_id, len(msgs), self._current_fav,
                 adopted)

    def _add_history_msg(self, m: dict) -> None:
        if not isinstance(m, dict):
            return
        if m.get("role") == "user":
            if m.get("text"):
                self._append_user(m["text"])
            return
        kind = "answer" if m.get("kind") == "answer" else "chat"
        blk = self._append_block(kind)
        if kind == "answer":
            blk.update({"no": m.get("no", ""), "title": m.get("title", ""),
                        "ans": m.get("ans", ""), "why": m.get("why", ""),
                        "placeholder": False})
        else:
            blk["text"] = m.get("text") or ""
        for t in (m.get("tools") or []):
            self._add_tool(blk, str(t))
        if (m.get("verifyPending") or m.get("verifyRan")
                or m.get("verifySkipped")):
            if m.get("verifyPending"):
                vk = "pending"
            elif m.get("verifySkipped"):
                vk = "skipped"
            elif str(m.get("verifyVerdict") or "") == "FIX":
                vk = "fix"
            else:
                vk = "ok"
            blk["verify"] = {"kind": vk, "note": m.get("verifyNote") or "",
                             "done": True}
            self._paint_verify(blk)
        self._paint(blk)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            if getattr(self, "_pop", None) is not None and self._pop.isVisible():
                self._pop.setVisible(False)  # 先关会话列表，再关才是藏窗口
                return
            self.hide()
        else:
            super().keyPressEvent(ev)
