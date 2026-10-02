"""搜题记录页——照 MV3 `review.html` 重设计（用户 2026-10-02 拍板）。

左栏 280px：搜索 → `全部/收藏` 分段 → `＋ 新建科目` → 分类树（点选即筛选，
hover 出 ✎/×，右键 重命名·启停·删除）。右栏：**会话卡片**列表（★ 标题 时间
✎ ×）+ 分页。原「科目管理」页已并入本页侧栏 —— 一页涵盖原两页。

纪律（MV3 design.md / 用户拍板）：
- **收藏只标记不置顶**：列表恒为最新在前，「只看收藏」交给分段筛选。
- 星标用字符 `★` + 自给 color，**绝不用 `⭐`**（系统 emoji 渲染色不可控）。
- 行内按钮 hover 才显，点按钮不顺手打开会话（各自独立 widget，天然不冒泡）。
- **思考（reason）不渲染**：详情里 think 字段直接丢弃。
- 所有网络请求走 QThread（`_QueryTask`），主线程不发请求。
"""

from __future__ import annotations

import json
import re

import markdown
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QEnterEvent, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    SearchLineEdit,
    StrongBodyLabel,
    ToolButton,
)

from .api import ApiClient, ApiError, NetworkError

PAGE_SIZE = 20
ACCENT = "#ec4899"

STATUS_LABEL = {
    "done": "完成", "error": "出错", "aborted": "已停止",
    "answering": "作答中", "verifying": "核实中",
}


def _md(text: str) -> str:
    # 不加 math 扩展：markdown≥3.6 已移除，引用即每次渲染必抛
    return markdown.markdown(str(text or ""),
                             extensions=["fenced_code", "tables", "nl2br"])


def _fmt_stamp(value) -> str:
    """MV3 review.js:37-42 fmtStamp → `MM-DD HH:mm`。"""
    s = str(value or "")
    return s[5:16] if len(s) >= 16 else s[:16]


def _no_head(no: object) -> str:
    digits = re.sub(r"\D", "", str(no or ""))
    return f"第{digits}题 " if digits else ""


# ---------------------------------------------------------------- 后台取数
class _QueryTask(QThread):
    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, api: ApiClient, params: dict, parent=None):
        super().__init__(parent)
        self.api, self.params = api, params

    def run(self):
        try:
            self.ok.emit(self.api.articles(**self.params))
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------- 输入模态
class _InputDialog(QDialog):
    """MV3 review.html:317-346 同款：居中、340px、Enter 保存 / Esc 取消。"""

    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setFixedWidth(340)
        self.setStyleSheet(
            "QDialog{background:#ffffff; border-radius:16px;}"
            "QLineEdit{border:1px solid #e6e8f2; border-radius:10px;"
            " padding:9px 11px; background:#fafbfe; font-size:14px;}"
            "QLineEdit:focus{border:1px solid #ec4899; background:#ffffff;}"
            "QPushButton{border:none; border-radius:11px; padding:9px 20px;"
            " font-weight:600; font-size:14px;}"
            "QPushButton#cancel{background:#f1f3fb; color:#4a4f6b;}"
            "QPushButton#cancel:hover{background:#e8ebf7;}"
            "QPushButton#ok{background:#ff3b5c; color:#ffffff;}"
            "QPushButton#ok:hover{background:#ef1f45;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 20, 18)
        root.setSpacing(14)
        head = QLabel(title)
        head.setStyleSheet("QLabel{font-size:16px; font-weight:650;"
                           " color:#1a1d2e; background:transparent;}")
        root.addWidget(head)
        self.edit = QLineEdit(value)
        root.addWidget(self.edit)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        btns.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("cancel")
        ok = QPushButton("保存")
        ok.setObjectName("ok")
        btns.addWidget(cancel)
        btns.addWidget(ok)
        root.addLayout(btns)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)
        self.edit.returnPressed.connect(self.accept)

    def showEvent(self, ev):
        super().showEvent(ev)
        self.edit.setFocus()
        self.edit.selectAll()

    @staticmethod
    def get_text(title: str, value: str, parent=None) -> str | None:
        dlg = _InputDialog(title, value, parent)
        return dlg.edit.text().strip() if dlg.exec() == QDialog.Accepted else None


# ---------------------------------------------------------------- 会话卡片
class SessionCard(QFrame):
    """MV3 review.html:50-83 + review.js:71-133 行解剖。"""

    opened = Signal(str)                 # 点行 → 看详情
    renameRequested = Signal(str, str)   # id, 标题
    deleteRequested = Signal(str, str)   # id, 标题
    favToggled = Signal(str, bool)       # id, 当前 fav
    contextRequested = Signal(str, object)  # id, QCursor.globalPos()

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionCard")
        self._id = str(row.get("id", ""))
        self._title = str(row.get("title", "") or "新会话")
        self._fav = bool(row.get("fav"))

        h = QHBoxLayout(self)
        h.setContentsMargins(10, 9, 10, 9)
        h.setSpacing(10)

        self.star = QPushButton("★")  # U+2605，字符+color，绝不用 ⭐
        self.star.setFixedSize(24, 24)
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.setToolTip("收藏")
        self.star.clicked.connect(
            lambda: self.favToggled.emit(self._id, self._fav))

        col = QVBoxLayout()
        col.setSpacing(3)
        col.setContentsMargins(0, 0, 0, 0)
        self.title_lbl = QLabel(self._title)
        self.title_lbl.setStyleSheet(
            "QLabel{font-size:14px; color:#2b2f4a; background:transparent;}")
        self.title_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.time_lbl = QLabel(_fmt_stamp(row.get("updateTime")))
        self.time_lbl.setStyleSheet(
            "QLabel{font-size:11.5px; color:#a3a8c2; background:transparent;}")
        col.addWidget(self.title_lbl)
        col.addWidget(self.time_lbl)

        self.rename_btn = QPushButton("✎")   # U+270E
        self.rename_btn.setFixedSize(24, 24)
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.clicked.connect(
            lambda: self.renameRequested.emit(self._id, self._title))
        self.del_btn = QPushButton("×")       # U+00D7
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(
            lambda: self.deleteRequested.emit(self._id, self._title))

        h.addWidget(self.star)
        h.addLayout(col, 1)
        h.addWidget(self.rename_btn)
        h.addWidget(self.del_btn)
        self._hover = False
        self._apply()

    # ---- 悬停显隐（macOS 式行内操作） ----
    def enterEvent(self, ev: QEnterEvent):
        self._hover = True
        self._apply()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._apply()
        super().leaveEvent(ev)

    def set_fav(self, fav: bool):
        self._fav = fav
        self._apply()

    def _apply(self):
        bg = "#fff9ea" if self._fav else "transparent"
        self.setStyleSheet(
            f"QFrame#sessionCard{{background:{bg}; border-radius:12px;}}"
            "QFrame#sessionCard:hover{background:#f5f7fd;}")
        star_fg = "#ec4899" if self._fav else "#b3b8cd"
        self.star.setStyleSheet(
            f"QPushButton{{background:transparent; border:none;"
            f" color:{star_fg}; font-size:17px; border-radius:6px;}}"
            "QPushButton:hover{color:#db2777;}")
        # 收藏常显，未收藏 hover 才显（MV3 review.html:60-69）
        self.star.setVisible(self._fav or self._hover)
        for btn in (self.rename_btn, self.del_btn):
            btn.setVisible(self._hover)
        self.rename_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:14px;"
            " color:#a3a8c2; border-radius:6px;}"
            "QPushButton:hover{background:#eef1fa; color:#4a4f6b;}")
        self.del_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:15px;"
            " color:#a3a8c2; border-radius:6px;}"
            "QPushButton:hover{background:#fdecef; color:#d02747;}")

    # ---- 整行点开 / 右键 ----
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.opened.emit(self._id)
        elif ev.button() == Qt.RightButton:
            self.contextRequested.emit(self._id, ev.globalPos())
        super().mousePressEvent(ev)


# ---------------------------------------------------------------- 分类行
class CatRow(QFrame):
    """MV3 review.js:136-171 buildFolder：纸夹图标 + 名称 + hover ✎/×。"""

    selected = Signal(str, str)            # id, name（id 空串=全部科目）
    renameRequested = Signal(str, str)
    deleteRequested = Signal(str, str)
    statusRequested = Signal(str, int)     # id, 目标 status(1/0)

    def __init__(self, cat_id: str, name: str, depth: int,
                 status: int = 1, parent=None):
        super().__init__(parent)
        self.setObjectName("catRow")
        self._id, self._name, self._depth, self._status = cat_id, name, depth, status
        self._sel = False
        self._hover = False
        h = QHBoxLayout(self)
        h.setContentsMargins(8 + depth * 14, 6, 6, 6)
        h.setSpacing(7)
        self.folder = QLabel()
        self.folder.setFixedSize(15, 11)   # MV3 纯 CSS 纸夹 .fi 15×11 #f9b6d5
        self.folder.setStyleSheet(
            "background:#f9b6d5; border-radius:2px;")
        self.name_lbl = QLabel(name)
        if status != 1:
            self.name_lbl.setStyleSheet(
                "QLabel{color:#a3a8c2; background:transparent; font-size:13.5px;}")
        self.name_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.rename_btn = QPushButton("✎")
        self.rename_btn.setFixedSize(22, 22)
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.clicked.connect(
            lambda: self.renameRequested.emit(self._id, self._name))
        self.del_btn = QPushButton("×")
        self.del_btn.setFixedSize(22, 22)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(
            lambda: self.deleteRequested.emit(self._id, self._name))
        h.addWidget(self.folder)
        h.addWidget(self.name_lbl, 1)
        h.addWidget(self.rename_btn)
        h.addWidget(self.del_btn)
        self._apply()

    @property
    def status(self) -> int:
        return self._status

    def set_selected(self, on: bool):
        self._sel = on
        self._apply()

    def set_status(self, status: int):
        self._status = status
        self._apply()

    def enterEvent(self, ev: QEnterEvent):
        self._hover = True
        self._apply()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self._hover = False
        self._apply()
        super().leaveEvent(ev)

    def _apply(self):
        if self._sel:
            bg, fg = "#ffeef7", "#c2185b"
        elif self._status != 1:
            bg, fg = "transparent", "#a3a8c2"
        else:
            bg, fg = "transparent", "#40455f"
        self.setStyleSheet(
            f"QFrame#catRow{{background:{bg}; border-radius:10px;}}"
            "QFrame#catRow:hover{background:#f2f4fb;}")
        self.name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.name_lbl.setStyleSheet(
            f"QLabel{{color:{fg}; background:transparent; font-size:13.5px;"
            f" font-weight:600;}}")
        for btn in (self.rename_btn, self.del_btn):
            btn.setVisible(self._hover)
        self.rename_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:13px;"
            " color:#a3a8c2; border-radius:6px;}"
            "QPushButton:hover{background:#eef1fa; color:#4a4f6b;}")
        self.del_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:14px;"
            " color:#a3a8c2; border-radius:6px;}"
            "QPushButton:hover{background:#fdecef; color:#d02747;}")

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.selected.emit(self._id, self._name)
        elif ev.button() == Qt.RightButton:
            self.rename_btn.setVisible(True)
            self.del_btn.setVisible(True)
            menu = QMenu(self)
            menu.addAction("重命名…",
                           lambda: self.renameRequested.emit(self._id, self._name))
            toggled = 0 if self._status == 1 else 1
            menu.addAction("停用" if self._status == 1 else "启用",
                           lambda: self.statusRequested.emit(self._id, toggled))
            menu.addAction("删除…",
                           lambda: self.deleteRequested.emit(self._id, self._name))
            menu.exec(ev.globalPos())
        super().mousePressEvent(ev)


# ---------------------------------------------------------------- 详情
def _detail_html(art: dict) -> str:
    """content.messages → markdown HTML（不渲染 think；截图另用 QPixmap 展示）。"""
    content = art.get("content") or {}
    msgs = content.get("messages") if isinstance(content, dict) else content
    if isinstance(content, str):
        try:
            content = json.loads(content)
            msgs = content.get("messages", [])
        except (ValueError, TypeError):
            msgs = [{"role": "?", "text": content}]
    parts: list[str] = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        role, kind = m.get("role"), m.get("kind", "")
        if role == "user":
            txt = m.get("text") or ""
            if txt:
                parts.append(
                    '<div style="background:#f2f4fb; border-radius:12px;'
                    ' padding:10px 10px 10px 3px; color:#1a1d2e;'
                    f' font-size:14.5px;">{_md(txt)}</div>')
            continue
        if kind == "answer":
            head = _no_head(m.get("no"))
            ans, why = m.get("ans") or "", m.get("why") or ""
            blk = ['<div style="border-left:3px solid #ec4899;'
                   ' padding-left:12px;">']
            blk.append('<div style="color:#9aa0bb; font-size:11.5px;'
                       ' font-weight:600;">初答</div>')
            blk.append(f'<div style="color:#1a1d2e; font-size:17px;'
                       f' font-weight:650;">{_md(head + ans)}</div>')
            if why:
                blk.append(f'<div style="color:#4a4f6b; font-size:15px;'
                           f'">{_md(why)}</div>')
            tools = m.get("tools") or []
            if tools:
                blk.append('<div style="margin-top:6px;">')
                for t in tools:
                    blk.append(
                        '<div style="background:#f6f7fc; border-radius:7px;'
                        ' padding:3px 8px; color:#7b81a0; font-size:13px;'
                        f' margin-bottom:4px;">⌕ {_md(str(t))}</div>')
                blk.append("</div>")
            if m.get("verifyRan") or m.get("verifySkipped"):
                verdict = str(m.get("verifyVerdict") or "")
                note = m.get("verifyNote") or ""
                if m.get("verifySkipped"):
                    kind_c, txt_c, chip = "#f1f2f8", "#7b81a0", "⏭ 已跳过 · 初答自评确定"
                elif verdict == "FIX":
                    kind_c, txt_c, chip = "#ffeced", "#d02747", "❌ 初答有误"
                else:
                    kind_c, txt_c, chip = "#e7f8ef", "#0f9d58", "✅ 与初答一致"
                blk.append(
                    '<div style="border:1px solid #e6e8f2; background:#fbfcff;'
                    ' border-radius:10px; padding:9px 11px; margin-top:9px;">'
                    '<div style="color:#9aa0bb; font-size:11.5px;'
                    ' font-weight:600;">核实　'
                    f'<span style="background:{kind_c}; color:{txt_c};'
                    ' border-radius:999px; padding:1px 8px;">'
                    f"{chip}</span></div>"
                    f'<div style="color:#3d4260; font-size:15px;">'
                    f"{_md(note)}</div></div>")
            blk.append("</div>")
            parts.append("".join(blk))
        else:  # chat
            txt = m.get("text") or ""
            blk = ['<div style="border-left:3px solid #ec4899;'
                   ' padding-left:12px;">']
            for t in (m.get("tools") or []):
                blk.append(
                    '<div style="background:#f6f7fc; border-radius:7px;'
                    ' padding:3px 8px; color:#7b81a0; font-size:13px;'
                    f' margin-bottom:4px;">⌕ {_md(str(t))}</div>')
            blk.append(f'<div style="color:#14172a; font-size:15px;">'
                       f"{_md(txt)}</div></div>")
            parts.append("".join(blk))
    return "".join(parts) or '<span style="color:#a3a8c2;">（空会话）</span>'


def _attachment_file(art: dict) -> str:
    """attachmentPath → 本机绝对路径（题库目录内），取不到返回空串。"""
    raw = str(art.get("attachmentPath") or "")
    if not raw:
        return ""
    from pathlib import Path
    p = Path(raw)
    if p.is_file():
        return str(p)
    return ""


class DetailDialog(QDialog):
    """MV3 review 右栏历史的只读版：截图 + markdown 消息流。"""

    def __init__(self, art: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(str(art.get("title") or "详情"))
        self.setStyleSheet("QDialog{background:#ffffff;}")
        self.resize(760, 680)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 18, 22, 16)
        root.setSpacing(10)
        head = QHBoxLayout()
        title = StrongBodyLabel(str(art.get("title") or "详情"))
        head.addWidget(title, 1)
        meta = CaptionLabel(
            f"{STATUS_LABEL.get(art.get('status', ''), art.get('status', ''))}"
            f" · {_fmt_stamp(art.get('updateTime'))}")
        head.addWidget(meta)
        root.addLayout(head)

        shot = _attachment_file(art)
        if shot:
            pm = QPixmap(shot)
            if not pm.isNull():
                lab = QLabel()
                lab.setAlignment(Qt.AlignCenter)
                lab.setPixmap(pm.scaled(680, 260, Qt.KeepAspectRatio,
                                        Qt.SmoothTransformation))
                lab.setStyleSheet("border:1px solid #e6e8f2;"
                                  " border-radius:12px; background:#f7f8fc;")
                root.addWidget(lab)

        body = QTextBrowser()
        body.setOpenExternalLinks(True)
        body.setHtml(
            '<div style="font-size:15px; line-height:1.6; color:#1a1d2e;">'
            f"{_detail_html(art)}</div>")
        body.setStyleSheet("QTextBrowser{background:#ffffff; border:none;}")
        root.addWidget(body, 1)

        close = PrimaryPushButton("关闭")
        close.setFixedWidth(120)
        close.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        root.addLayout(row)


# ---------------------------------------------------------------- 主页面
class RecordsPane(QWidget):
    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.setObjectName("recordsPage")  # FluentWindow.addSubInterface 要求非空
        self.api = api
        self.page = 1
        self.keyword = ""
        self.category_id = ""
        self.fav = 0                      # 0=全部 1=只看收藏
        self.rows: list[dict] = []
        self._task: _QueryTask | None = None
        self._cats: list[dict] = []
        self._cat_rows: list[CatRow] = []

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 左栏 ----------
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(280)
        side.setStyleSheet("#sidebar{background:#ffffff;"
                           " border-right:1px solid #e6e8f2;}")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 14, 12, 12)
        sv.setSpacing(10)

        self.search = SearchLineEdit()
        self.search.setPlaceholderText("按标题检索…")
        self.search.searchButton.clicked.connect(self._do_search)
        self.search.returnPressed.connect(self._do_search)
        sv.addWidget(self.search)

        seg = QFrame()
        seg.setObjectName("segBox")
        seg.setStyleSheet("#segBox{background:#f2f4fb; border-radius:10px;}")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(0)
        self.seg_all = QPushButton("全部")
        self.seg_fav = QPushButton("收藏")
        for b in (self.seg_all, self.seg_fav):
            b.setFixedHeight(28)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, fav=b is self.seg_fav:
                              self._set_seg(fav))
        sh.addWidget(self.seg_all)
        sh.addWidget(self.seg_fav)
        sv.addWidget(seg)

        self.new_cat_btn = QPushButton("＋ 新建科目")
        self.new_cat_btn.setCursor(Qt.PointingHandCursor)
        self.new_cat_btn.setStyleSheet(
            "QPushButton{border:1px dashed #e6e8f2; border-radius:10px;"
            " padding:8px; color:#4a4f6b; font-size:13.5px;"
            " background:transparent;}"
            "QPushButton:hover{background:#ffeef7; border-color:#ec4899;"
            " color:#ec4899;}")
        self.new_cat_btn.clicked.connect(self._new_category)
        sv.addWidget(self.new_cat_btn)

        cat_scroll = QScrollArea()
        cat_scroll.setWidgetResizable(True)
        cat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cat_box_widget = QWidget()
        self._cat_box = QVBoxLayout(self._cat_box_widget)
        self._cat_box.setContentsMargins(0, 0, 0, 0)
        self._cat_box.setSpacing(2)
        self._cat_box.addStretch(1)
        cat_scroll.setWidget(self._cat_box_widget)
        sv.addWidget(cat_scroll, 1)

        # ---------- 右栏 ----------
        main = QFrame()
        main.setObjectName("mainBox")
        main.setStyleSheet("#mainBox{background:#f7f8fc;}")
        mv = QVBoxLayout(main)
        mv.setContentsMargins(18, 14, 18, 12)
        mv.setSpacing(10)

        head = QHBoxLayout()
        self.filter_lbl = StrongBodyLabel("全部科目")
        head.addWidget(self.filter_lbl, 1)
        self.refresh_btn = ToolButton(FluentIcon.SYNC)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(self.reload)
        head.addWidget(self.refresh_btn)
        mv.addLayout(head)

        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setStyleSheet("QScrollArea{background:transparent;"
                                  " border:none;}")
        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("QWidget{background:transparent;}")
        self._list_box = QVBoxLayout(self._list_widget)
        self._list_box.setContentsMargins(0, 0, 0, 0)
        self._list_box.setSpacing(4)
        self.empty_lbl = QLabel("还没有搜题记录。\n回网页按 Alt+S 截一道题。")
        self.empty_lbl.setStyleSheet(
            "QLabel{color:#a3a8c2; font-size:13.5px; background:transparent;"
            " padding:40px 0;}")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        self._list_box.addWidget(self.empty_lbl)
        self._list_box.addStretch(1)
        list_scroll.setWidget(self._list_widget)
        mv.addWidget(list_scroll, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self.prev = PushButton("上一页")
        self.page_label = CaptionLabel("第 1 页")
        self.next = PushButton("下一页")
        self.prev.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        foot.addWidget(self.prev)
        foot.addWidget(self.page_label)
        foot.addWidget(self.next)
        foot.addStretch(1)
        mv.addLayout(foot)

        root.addWidget(side)
        root.addWidget(main, 1)

    # ---------- 数据 ----------
    def reload(self):
        if self._task is not None and self._task.isRunning():
            return
        self.page_label.setText("加载中…")
        params: dict = {
            "page": self.page, "size": PAGE_SIZE,
            "keyword": self.keyword or None,
            # 收藏视图平铺，不叠分类筛选（MV3 review.js:173-196）
            "category_id": None if self.fav else (self.category_id or None),
            "fav": 1 if self.fav else None,
        }
        self._task = _QueryTask(self.api, params, self)
        self._task.ok.connect(self._on_rows)
        self._task.failed.connect(self._on_error)
        self._task.start()

    def load_categories(self):
        """分类树数据（首次进来/科目改动后调）。"""
        try:
            self._cats = _flatten(self.api.category_tree() or [])
        except (ApiError, NetworkError):
            self._cats = []  # 拿不到不阻断列表
        self._render_cats()

    def _on_rows(self, data: dict):
        self.rows = data.get("list", [])
        total = data.get("total", 0)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"第 {self.page} / {pages} 页 · 共 {total} 条")
        self._render_rows()

    def _on_error(self, msg: str):
        self.page_label.setText(f"加载失败：{msg}")

    # ---------- 渲染 ----------
    def _clear_box(self, box: QVBoxLayout, keep_stretch: bool = True):
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        if keep_stretch:
            box.addStretch(1)

    def _render_rows(self):
        self._clear_box(self._list_box)
        self.empty_lbl = QLabel(
            "没有收藏的会话。\n点行内 ★ 收藏，这里只留收藏的。" if self.fav
            else "还没有搜题记录。\n回网页按 Alt+S 截一道题。")
        self.empty_lbl.setStyleSheet(
            "QLabel{color:#a3a8c2; font-size:13.5px; background:transparent;"
            " padding:40px 0;}")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        if not self.rows:
            self._list_box.insertWidget(0, self.empty_lbl)
            self.empty_lbl.show()
            return
        for row in self.rows:
            card = SessionCard(row)
            card.opened.connect(self._show_detail)
            card.renameRequested.connect(self._rename_session)
            card.deleteRequested.connect(self._delete_session)
            card.favToggled.connect(self._toggle_fav)
            card.contextRequested.connect(self._card_menu)
            self._list_box.insertWidget(self._list_box.count() - 1, card)

    def _render_cats(self):
        self._clear_box(self._cat_box)
        self._cat_rows = []
        all_row = CatRow("", "全部科目", 0)
        all_row.set_selected(not self.category_id)
        all_row.selected.connect(lambda _i, _n: self._pick_category(""))
        self._cat_box.insertWidget(self._cat_box.count() - 1, all_row)
        for c in self._cats:
            row = CatRow(str(c["id"]), c["name"], c["depth"],
                         int(c.get("status", 1) or 1))
            row.set_selected(self.category_id == str(c["id"]))
            row.selected.connect(self._pick_category)
            row.renameRequested.connect(self._rename_category)
            row.deleteRequested.connect(self._delete_category)
            row.statusRequested.connect(self._toggle_category)
            self._cat_box.insertWidget(self._cat_box.count() - 1, row)
            self._cat_rows.append(row)

    def _sync_cat_selection(self):
        for row in self._cat_rows:
            row.set_selected(self.category_id == row._id)
        if self._cat_box.count():
            first = self._cat_box.itemAt(0).widget()
            if isinstance(first, CatRow):
                first.set_selected(not self.category_id)

    # ---------- 交互：分段 / 检索 / 分页 ----------
    def _set_seg(self, fav: bool):
        self.fav = 1 if fav else 0
        self.page = 1
        for btn, on in ((self.seg_all, not fav), (self.seg_fav, fav)):
            bg = "#ffffff" if on else "transparent"
            fg = "#14162a" if on else "#4a5070"
            btn.setStyleSheet(
                f"QPushButton{{background:{bg}; color:{fg}; border:none;"
                " border-radius:8px; font-size:13px; font-weight:600;}")
        self._sync_cat_selection()
        self.reload()

    def _do_search(self):
        self.keyword = self.search.text().strip()
        self.page = 1
        self.reload()

    def _pick_category(self, cat_id: str, _name: str = ""):
        self.category_id = cat_id
        if self.fav:
            self._set_seg(False)
            return
        self.page = 1
        self.filter_lbl.setText(
            next((c["name"] for c in self._cats if str(c["id"]) == cat_id),
                 "全部科目"))
        self._sync_cat_selection()
        self.reload()

    def _go(self, delta: int):
        self.page = max(1, self.page + delta)
        self.reload()

    # ---------- 会话：详情 / 重命名 / 删除 / 收藏 / 移动 ----------
    def _show_detail(self, art_id: str):
        try:
            art = self.api.article(art_id)
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"详情失败：{e}")
            return
        DetailDialog(art, self.window()).exec()

    def _rename_session(self, art_id: str, title: str):
        new = _InputDialog.get_text("重命名会话", title, self.window())
        if not new or new == title:
            return
        try:
            self.api.update_article(art_id, title=new)
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"重命名失败：{e}")

    def _delete_session(self, art_id: str, title: str):
        box = MessageBox("删除这个会话？",
                         f"确定删除「{title}」吗？截图、回答与核实记录会一并"
                         "删除，不可恢复。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_article(art_id)
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"删除失败：{e}")

    def _toggle_fav(self, art_id: str, cur: bool):
        try:
            self.api.update_article(art_id, fav=0 if cur else 1)
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"收藏失败：{e}")
            return
        # 乐观更新 + toast（MV3 review.js:261-268）；收藏不重排
        for row in self.rows:
            if str(row.get("id")) == art_id:
                row["fav"] = 0 if cur else 1
        for i in range(self._list_box.count()):
            w = self._list_box.itemAt(i).widget()
            if isinstance(w, SessionCard) and w._id == art_id:
                w.set_fav(not cur)
        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.success("已收藏" if not cur else "已取消收藏",
                        "会话列表里会标出这颗星" if not cur else "已取消标记",
                        parent=self, duration=2200,
                        position=InfoBarPosition.TOP)

    def _card_menu(self, art_id: str, pos):
        if not self._cats:
            return
        menu = QMenu(self)
        move = menu.addMenu("移动到科目")
        for c in self._cats:
            act = move.addAction(c["label"])
            act.triggered.connect(
                lambda _=False, cid=c["id"], aid=art_id: self._move(aid, cid))
        menu.addAction("移出科目（未分组）",
                       lambda aid=art_id: self._move(aid, ""))
        menu.exec(pos if hasattr(pos, "x") else self.mapToGlobal(pos))

    def _move(self, art_id: str, cat_id: str):
        try:
            self.api.update_article(art_id,
                                    category_id=cat_id or None) if cat_id \
                else self.api.update_article(art_id, category_id="")
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"移动失败：{e}")

    # ---------- 分类：新建 / 重命名 / 启停 / 删除 ----------
    def _new_category(self):
        name = _InputDialog.get_text("新建科目", "", self.window())
        if not name:
            return
        try:
            self.api.create_category(name)
            self.load_categories()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"新建失败：{e}")

    def _rename_category(self, cat_id: str, name: str):
        new = _InputDialog.get_text("重命名科目", name, self.window())
        if not new or new == name:
            return
        try:
            self.api.rename_category(cat_id, new)
            self.load_categories()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"改名失败：{e}")

    def _toggle_category(self, cat_id: str, status: int):
        try:
            self.api.change_category_status(cat_id, status)
            self.load_categories()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"启停失败：{e}")

    def _delete_category(self, cat_id: str, name: str):
        box = MessageBox("删除这个科目？",
                         f"确定删除「{name}」吗？其下会话会被置为未分组，"
                         "不会删除会话本身。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_category(cat_id)
            if self.category_id == cat_id:
                self.category_id = ""
                self.filter_lbl.setText("全部科目")
                self.page = 1
            self.load_categories()
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"删除失败：{e}")

    def contextMenuEvent(self, ev):
        # 兼容旧行为：无卡片命中时不做事（移动已挂到卡片右键）
        super().contextMenuEvent(ev)


def _flatten(nodes: list[dict], depth: int = 0) -> list[dict]:
    """分类树 → 扁平列表（带缩进层级与 status），children 键随 02 接口。"""
    out: list[dict] = []
    for n in nodes:
        out.append({"id": n.get("id"), "name": str(n.get("name", "")),
                    "depth": depth, "status": n.get("status", 1)})
        out.extend(_flatten(n.get("children") or [], depth + 1))
    return out
