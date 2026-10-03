"""搜题记录页——照 MV3 `review.html` 重设计（用户 2026-10-02 二轮拍板）。

**左栏 280px**：即时检索（去搜索按钮，键入即过滤；命中时进**第二形态**——
只平铺命中会话、不摆科目）→ `全部/收藏` 分段（初始选中「全部」）→
`＋ 新建科目` → **会话列表**（开机自动加载、每次切入标签页自动刷新，无刷新钮）：
- 分类行（hover `✎ ×`：改名 / 删除；「停用」2026-10-03 用户点名没用已移除）
  **点击 = 展开/收起**其下会话；
- 已分类会话只在所属科目展开时缩进挂在行下；**未分类会话排在所有科目行之后**；
- 会话行 `★ ✎ ⇄ ×`（hover 才显，⇄ = 移入科目·点开**模态框**选）+ 标题 +
  `MM-DD HH:mm`，点行 = 右栏显示内容；标题超宽右侧省略号，不挤行尾按钮；
- **无右键菜单**（2026-10-03 用户死命令：行内操作全按钮化，§8-3）；
- `收藏` 分段平铺全部收藏会话、不摆科目（MV3 review.js:173-196）。

**右栏 = 选中会话的内容区**：标题 + ★ 收藏 + 状态/时间小字 + 截图（点击用
系统默认程序打开；attachmentPath 空时回退消息里的题图路径）+ markdown 消息流
+ 底部「接着问」输入行——追问收编给引擎、**回答在本页右栏直播**（200ms 节流，
不开悬浮窗），落库更新本会话（turn-end 后本页自动刷新）；
未选中时右侧居中提示，零记录给引导文案。

纪律（MV3 design.md / 用户拍板）：
- 一次 `articles(page=1, size=200)` 拉全量（后端 size 上限 200），分组/关键词/
  收藏全在客户端过滤，**无分页 footer**（MV3 同样没有分页）。
- 星标用字符 `★` + 自给 color，**绝不用 `⭐`**（系统 emoji 渲染色不可控）。
- 行内按钮 hover 才显，点按钮不顺手打开会话（各自独立 widget，天然不冒泡）。
- **思考（reason/think）不渲染**：消息流里 think 字段直接丢弃。
- 所有网络请求走 QThread（`_QueryTask`），主线程不发请求。
"""

from __future__ import annotations

import json
import re
from contextlib import suppress
from pathlib import Path

import markdown
from PySide6.QtCore import QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QEnterEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
    MessageBox,
    PrimaryPushButton,
    SearchLineEdit,
)

from .answer.session import Session, msgs_of
from .api import ApiClient, ApiError, NetworkError

FETCH_SIZE = 200        # 后端 size 上限 200：一次拉全量，客户端分组/过滤
ACCENT = "#ec4899"

STATUS_LABEL = {
    "done": "完成", "error": "出错", "aborted": "已停止",
    "answering": "作答中", "verifying": "核实中",
}


def _md(text: str) -> str:
    # 不加 math 扩展：markdown≥3.6 已移除，引用即每次渲染必抛。
    # `<<` 先转义：模型协议标记（<<ok>> 等）会被富文本当标签吃掉，
    # 「ok」直接消失（2026-10-03 用户截图实锤）
    return markdown.markdown(str(text or "").replace("<<", "&lt;&lt;"),
                             extensions=["fenced_code", "tables", "nl2br"])


def _md_inline(text: str) -> str:
    """markdown 结果只剥掉**唯一**外层 <p>——检索小票要图标与文本同一行。

    `<p>` 是块级元素，`⌕ <p>检索 …</p>` 会渲成 `⌕` 独占一行、文本另起一行
    （2026-10-03 §8-1 用户贴的分行现场）；多段时不剥，宁可保持原样。
    """
    out = _md(text)
    if out.startswith("<p>") and out.endswith("</p>") and out.count("<p>") == 1:
        return out[3:-4]
    return out


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


class _CatTask(QThread):
    """分类树后台取数——load_categories 从前是主线程同步请求，后端半死时
    UI 卡 15s（用户「点进去狂点刷新都不显示」的嫌疑之一，2026-10-03）。"""

    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api

    def run(self):
        try:
            self.ok.emit(_flatten(self.api.category_tree() or []))
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------- 圆形单选
class _CircleRadio(QRadioButton):
    """圆形指示器 + 选中打√（2026-10-03 用户截图：QSS 的 checked 态
    16px+5px 边渲成了圆角方块，且两个行样式不一致——改为自绘）。"""

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = 16.0
        x0 = 1.0
        box = QRectF(x0, (self.height() - d) / 2, d, d)
        if self.isChecked():
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ec4899"))
            p.drawEllipse(box)
            p.setPen(QPen(QColor("#ffffff"), 2.0, Qt.SolidLine,
                          Qt.RoundCap, Qt.RoundJoin))
            p.drawLine(x0 + 4.4, box.y() + 8.4, x0 + 7.0, box.y() + 11.2)
            p.drawLine(x0 + 7.0, box.y() + 11.2, x0 + 11.6, box.y() + 5.8)
        else:
            p.setPen(QPen(QColor("#c4c9db"), 1.5))
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(box)
        p.setPen(QColor("#2b2f4a"))
        p.setFont(self.font())
        p.drawText(QRectF(24, 0, max(0.0, self.width() - 24), self.height()),
                   int(Qt.AlignVCenter | Qt.AlignLeft), self.text())


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


# ---------------------------------------------------------------- 移入科目模态框
class _MoveDialog(QDialog):
    """「移入科目」模态框（2026-10-03 用户点名：不要弹出菜单，要模态）。

    科目单选（按层级缩进）+「未分组」；预选当前归属，取消 = None。
    """

    def __init__(self, cats: list[dict], current: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("移入科目")
        self.setModal(True)
        self.setFixedWidth(340)
        self.setStyleSheet(
            "QDialog{background:#ffffff; border-radius:16px;}"
            "QRadioButton{font-size:14px; color:#2b2f4a; spacing:8px;"
            " padding:4px 0;}"     # 指示器由 _CircleRadio 自绘（圆圈+√）
            "QPushButton{border:none; border-radius:11px; padding:9px 20px;"
            " font-weight:600; font-size:14px;}"
            "QPushButton#cancel{background:#f1f3fb; color:#4a4f6b;}"
            "QPushButton#cancel:hover{background:#e8ebf7;}"
            "QPushButton#ok{background:#ff3b5c; color:#ffffff;}"
            "QPushButton#ok:hover{background:#ef1f45;}")
        self._targets: list[str] = []
        self._radios: list[QRadioButton] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 20, 18)
        root.setSpacing(12)
        head = QLabel("移入科目")
        head.setStyleSheet("QLabel{font-size:16px; font-weight:650;"
                           " color:#1a1d2e; background:transparent;}")
        root.addWidget(head)
        opts = QVBoxLayout()
        opts.setSpacing(6)
        rows = [("", "未分组")] + [
            (str(c["id"]), "　" * int(c.get("depth", 0)) + str(c["name"]))
            for c in cats]
        for cid, label in rows:
            rb = _CircleRadio(label)
            self._radios.append(rb)
            self._targets.append(cid)
            opts.addWidget(rb)
        root.addLayout(opts)
        checked = (self._targets.index(current)
                   if current in self._targets else 0)  # 归属失效 → 落回未分组
        self._radios[checked].setChecked(True)
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

    def _selected(self) -> str:
        """选中的目标科目 id；「未分组」与无选中都是空串。"""
        for cid, rb in zip(self._targets, self._radios, strict=False):
            if rb.isChecked():
                return cid
        return ""

    @staticmethod
    def get_target(cats: list[dict], current: str,
                   parent=None) -> str | None:
        dlg = _MoveDialog(cats, current, parent)
        return dlg._selected() if dlg.exec() == QDialog.Accepted else None


# ---------------------------------------------------------------- 会话行（左栏）
class SessionCard(QFrame):
    """MV3 review.html:50-83 + review.js:71-133 行剖：★ 标题 时间 ✎ ⇄ ×。

    左栏列表里的一行；`depth>0` 表示挂在科目行下（缩进一层）。
    """

    opened = Signal(str)                 # 点行 → 右栏显示内容
    renameRequested = Signal(str, str)   # id, 标题
    deleteRequested = Signal(str, str)   # id, 标题
    favToggled = Signal(str, bool)       # id, 当前 fav
    moveRequested = Signal(str)          # id → 打开「移入科目」模态框

    def __init__(self, row: dict, depth: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("sessionCard")
        self._id = str(row.get("id", ""))
        self._title = str(row.get("title", "") or "新会话")
        self._fav = bool(row.get("fav"))
        self._sel = False

        h = QHBoxLayout(self)
        h.setContentsMargins(10 + depth * 14, 7, 8, 7)
        h.setSpacing(9)

        self.star = QPushButton("★")  # U+2605，字符+color，绝不用 ⭐
        self.star.setFixedSize(24, 24)
        self.star.setCursor(Qt.PointingHandCursor)
        self.star.setToolTip("收藏")
        self.star.clicked.connect(
            lambda: self.favToggled.emit(self._id, self._fav))

        col = QVBoxLayout()
        col.setSpacing(2)
        col.setContentsMargins(0, 0, 0, 0)
        # 标题定长：_ElidedLabel 最小宽 60 + 超宽省略号——长标题不再把行尾
        # 按钮挤出行外（2026-10-03 用户反馈「只显示了两个按钮」）；
        # 也不设 TextSelectableByMouse：label 吞按下事件会开不了会话（§8-4）
        self.title_lbl = _ElidedLabel(self._title, "#2b2f4a")
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
        self.move_btn = QPushButton("⇄")     # U+21C4：移入科目（原右键菜单按钮化）
        self.move_btn.setFixedSize(24, 24)
        self.move_btn.setCursor(Qt.PointingHandCursor)
        self.move_btn.setToolTip("移入科目")
        self.move_btn.clicked.connect(
            lambda: self.moveRequested.emit(self._id))
        self.del_btn = QPushButton("×")       # U+00D7
        self.del_btn.setFixedSize(24, 24)
        self.del_btn.setCursor(Qt.PointingHandCursor)
        self.del_btn.clicked.connect(
            lambda: self.deleteRequested.emit(self._id, self._title))

        h.addWidget(self.star)
        h.addLayout(col, 1)
        h.addWidget(self.rename_btn)
        h.addWidget(self.move_btn)
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

    def set_selected(self, on: bool):
        self._sel = on
        self._apply()

    def _apply(self):
        if self._sel:
            bg, hover = "#ffeef7", "#ffe4f1"   # 选中：右栏正看这条
        elif self._fav:
            bg, hover = "#fff9ea", "#f5f7fd"   # 收藏行底
        else:
            bg, hover = "transparent", "#f5f7fd"
        self.setStyleSheet(
            f"QFrame#sessionCard{{background:{bg}; border-radius:12px;}}"
            f"QFrame#sessionCard:hover{{background:{hover};}}")
        star_fg = ACCENT if self._fav else "#b3b8cd"
        self.star.setStyleSheet(
            f"QPushButton{{background:transparent; border:none;"
            f" color:{star_fg}; font-size:16px; border-radius:6px;}}"
            "QPushButton:hover{color:#db2777;}")
        # 收藏/选中常显，其余 hover 才显（MV3 review.html:60-69）
        self.star.setVisible(self._fav or self._sel or self._hover)
        for btn in (self.rename_btn, self.move_btn, self.del_btn):
            btn.setVisible(self._hover or self._sel)
        title_fg = "#c2185b" if self._sel else "#2b2f4a"
        title_w = "600" if self._sel else "normal"
        self.title_lbl.set_color(title_fg)   # 自绘走 _color，样式表色管不到
        self.title_lbl.setStyleSheet(
            f"QLabel{{font-size:13.5px; color:{title_fg}; font-weight:{title_w};"
            " background:transparent;}")
        for btn in (self.rename_btn, self.move_btn):
            btn.setStyleSheet(
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
        # 右键不再弹菜单（2026-10-03 死命令：菜单一律按钮化，§8-3）
        super().mousePressEvent(ev)


# ---------------------------------------------------------------- 分类行（左栏）
class CatRow(QFrame):
    """MV3 review.js:136-171 buildFolder：纸夹图标 + 名称 + hover ✎ ×。

    与 MV3 同语义：**点击 = 展开/收起该科目下的会话**（selected 信号即展开请求，
    展开态记在 RecordsPane._expanded 里，不改右栏内容）。
    """

    selected = Signal(str, str)            # id, name → 请求展开/收起
    renameRequested = Signal(str, str)
    deleteRequested = Signal(str, str)

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
        # 定长省略同会话行：长科目名也不能把 ✎× 挤出行外（同批反馈）
        self.name_lbl = _ElidedLabel(name, "#40455f")
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

    def set_selected(self, on: bool):
        self._sel = on
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
        if self._sel:   # 展开中（沿用选中底色，MV3 .sub.open）
            bg, fg = "#ffeef7", "#c2185b"
        elif self._status != 1:
            bg, fg = "transparent", "#a3a8c2"
        else:
            bg, fg = "transparent", "#40455f"
        self.setStyleSheet(
            f"QFrame#catRow{{background:{bg}; border-radius:10px;}}"
            "QFrame#catRow:hover{background:#f2f4fb;}")
        self.name_lbl.setTextFormat(Qt.TextFormat.PlainText)
        self.name_lbl.set_color(fg)         # 自绘走 _color，样式表色管不到
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
        # 无右键菜单（§8-3）；「停用」按钮 2026-10-03 用户点名没用已移除
        super().mousePressEvent(ev)


# ---------------------------------------------------------------- 消息流 / 截图
def _detail_html(art: dict) -> str:
    """content.messages → markdown HTML（不渲染 think；截图在右栏单独展示）。

    列表 VO 直接带 `messages[]`（后端 toVo 直接带），详情接口包在 `content`
    里（dict 或 JSON 字符串）——两种形状都吃。
    """
    msgs = art.get("messages")
    if not isinstance(msgs, list):
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
                # 追问小节标：灰字在用户追问气泡**上方**（2026-10-03 反馈）；
                # 截屏补充（kind=answer）不是追问，不加
                if kind == "chat":
                    parts.append(
                        '<div style="color:#9aa0bb; font-size:11.5px;'
                        ' font-weight:600; margin-bottom:3px;">追问</div>')
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
                        f' margin-bottom:4px;">⌕ {_md_inline(str(t))}</div>')
                blk.append("</div>")
            if (m.get("verifyRan") or m.get("verifySkipped")
                    or m.get("verifyPending")):
                verdict = str(m.get("verifyVerdict") or "")
                note = m.get("verifyNote") or ""
                if m.get("verifySkipped"):
                    kind_c, txt_c, chip = "#f1f2f8", "#7b81a0", "⏭ 已跳过 · 初答自评确定"
                elif not m.get("verifyRan"):
                    kind_c, txt_c, chip = "#f1f2f8", "#7b81a0", "⏳ 待核实"
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
                if (m.get("verifyPending") and not m.get("verifyRan")
                        and not m.get("verifySkipped")):
                    # 「核实一下」按钮（2026-10-03 反馈：关自动核实后没地方
                    # 点核实）——QTextBrowser 里用锚实现，走 spore:// 协议
                    blk.append(
                        '<div style="margin-top:8px;"><a href="spore://verify"'
                        ' style="background:#ec4899; color:#ffffff;'
                        ' border-radius:10px; padding:6px 14px;'
                        ' text-decoration:none; font-weight:600;'
                        ' font-size:13.5px;">🔍 核实一下</a></div>')
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
                    f' margin-bottom:4px;">⌕ {_md_inline(str(t))}</div>')
            blk.append(f'<div style="color:#14172a; font-size:15px;">'
                       f"{_md(txt)}</div></div>")
            parts.append("".join(blk))
    return "".join(parts) or '<span style="color:#a3a8c2;">（空会话）</span>'


def article_shot(article: dict, api: ApiClient) -> str:
    """题图定位：attachmentPath 优先，落空回退最后一条带图消息的 imagePath。

    实测 push-attachment 只把文件存进题库目录、**没回写 article 行**
    （SyncController 注释声称写回但代码没写）——GUI 建的会话 attachmentPath
    恒空，光解析相对路径永远显示不出来（2026-10-03 用户复测「还是没有截图」）；
    消息里的 imagePath 是绝对路径，resolve_attachment 直接认（§8-5 同链）。
    """
    shot = api.resolve_attachment(str(article.get("attachmentPath") or ""))
    if shot:
        return shot
    for m in reversed(msgs_of(article)):
        if isinstance(m, dict) and m.get("imagePath"):
            shot = api.resolve_attachment(str(m["imagePath"]))
            if shot:
                return shot
    return ""


def purge_article_files(article: dict, api: ApiClient) -> None:
    """删除会话后连带删题图（2026-10-03 反馈）。

    删两类：题库目录里的附件 `<id>.*`（push-attachment 的落盘名）+ 本机
    captures 里的原图（消息 imagePath 绝对路径）。**只碰这两个安全目录**，
    消息里的野路径一律不动；同机部署（默认）即删即净。
    """
    art_id = str(article.get("id") or "")
    if not art_id:
        return
    base = api.storage_dir()
    if base:
        for f in Path(base).glob(f"{art_id}.*"):
            with suppress(OSError):
                f.unlink()
    from .capture import CAPTURE_DIR  # 惰性 import：PIL 只在删除时才拉
    cap = Path(CAPTURE_DIR).resolve()
    for m in msgs_of(article):
        if not isinstance(m, dict):
            continue
        p = Path(str(m.get("imagePath") or ""))
        if not p.is_absolute():
            continue  # 相对路径 = 题库目录，上面已按 id 删过
        try:
            p.resolve().relative_to(cap)
        except ValueError:
            continue  # 不在截图目录 → 不碰（防野路径）
        with suppress(OSError):
            p.unlink(missing_ok=True)


class _ClickableLabel(QLabel):
    """可点 QLabel：截图点击 → 系统默认程序打开（不做自绘放大层）。"""

    clicked = Signal()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class _ElidedLabel(QLabel):
    """单行标题：超宽右侧省略号（右栏会话标题用）。"""

    def __init__(self, text: str = "", color: str = "#1a1d2e", parent=None):
        super().__init__(text, parent)
        self._color = color
        self.setStyleSheet(
            f"QLabel{{font-size:15px; font-weight:600; color:{self._color};"
            " background:transparent;}")

    def set_color(self, color: str):
        """换自绘字色（paintEvent 不走样式表的 color，得手动同步）。"""
        self._color = color
        self.update()

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(min(hint.width(), 340), hint.height())

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(60, hint.height())

    def paintEvent(self, ev):
        painter = QPainter(self)
        painter.setPen(QColor(self._color))
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight,
                                             self.width())
        painter.drawText(self.rect(),
                         int(Qt.AlignLeft | Qt.AlignVCenter), text)


# ---------------------------------------------------------------- 主页面
class RecordsPane(QWidget):
    followupRequested = Signal(str, str)   # art_id, 追问原文 → 主窗收编+代发
    cancelRequested = Signal()             # 🚫 停止当前回合 → 主窗 engine.cancel
    verifyRequested = Signal(str)          # 「核实一下」锚点 → 主窗收编+核实

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.setObjectName("recordsPage")  # FluentWindow.addSubInterface 要求非空
        self.api = api
        self.keyword = ""
        self.fav = 0                      # 0=全部 1=只看收藏（分段）
        self.rows: list[dict] = []        # 一次拉全量（size=FETCH_SIZE）的原始列表
        self.current_id = ""              # 右栏正在看的会话
        self._task: _QueryTask | None = None
        self._cats: list[dict] = []
        self._expanded: set[str] = set()  # 展开中的科目 id（点分类行翻转）
        self._session_cards: list[SessionCard] = []
        self._shot_path = ""
        self._shot_pm = QPixmap()
        self._cat_task: _CatTask | None = None
        self._live: Session | None = None  # 记录页直播中的接续回合（engine.session）
        self._live_timer = QTimer(self)    # 流式重渲节流（面板同款 200ms）
        self._live_timer.setInterval(200)
        self._live_timer.timeout.connect(self._flush_live)
        # turn-end 的自动刷新用库里终稿重渲后，跟随一次底部（别把视线弹回顶）
        self._scroll_bottom_once = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- 左栏：搜索 + 分段 + 新建科目 + 会话列表 ----------
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
        self.search.searchButton.hide()          # 搜索按钮去掉（2026-10-03 反馈）
        self.search.setTextMargins(0, 0, 34, 0)  # 只给清除按钮留位
        self.search.textChanged.connect(self._do_search)  # 即时过滤，不等回车
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
        self.seg_all.clicked.connect(lambda: self._set_seg(False))
        self.seg_fav.clicked.connect(lambda: self._set_seg(True))
        sh.addWidget(self.seg_all)
        sh.addWidget(self.seg_fav)
        sv.addWidget(seg)

        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        self.new_cat_btn = QPushButton("＋ 新建科目")
        self.new_cat_btn.setCursor(Qt.PointingHandCursor)
        self.new_cat_btn.setStyleSheet(
            "QPushButton{border:1px dashed #e6e8f2; border-radius:10px;"
            " padding:8px; color:#4a4f6b; font-size:13.5px;"
            " background:transparent;}"
            "QPushButton:hover{background:#ffeef7; border-color:#ec4899;"
            " color:#ec4899;}")
        self.new_cat_btn.clicked.connect(self._new_category)
        cat_row.addWidget(self.new_cat_btn, 1)
        sv.addLayout(cat_row)

        tree_scroll = QScrollArea()
        tree_scroll.setWidgetResizable(True)
        tree_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tree_scroll.setStyleSheet("QScrollArea{background:transparent;"
                                  " border:none;}")
        self._tree_widget = QWidget()
        self._tree_widget.setStyleSheet("QWidget{background:transparent;}")
        self._tree_box = QVBoxLayout(self._tree_widget)
        self._tree_box.setContentsMargins(0, 0, 0, 0)
        self._tree_box.setSpacing(2)
        self._tree_box.addStretch(1)
        tree_scroll.setWidget(self._tree_widget)
        sv.addWidget(tree_scroll, 1)

        # ---------- 右栏：选中会话的内容区 ----------
        self.main_box = QFrame()
        self.main_box.setObjectName("mainBox")
        self.main_box.setStyleSheet("#mainBox{background:#f7f8fc;}")
        mv = QVBoxLayout(self.main_box)
        mv.setContentsMargins(20, 14, 20, 12)
        mv.setSpacing(10)

        self.hint_lbl = QLabel("还没有搜题记录。\n回软件按 Alt+S 截一道题。")
        self.hint_lbl.setStyleSheet(
            "QLabel{color:#a3a8c2; font-size:14px; background:transparent;"
            " padding:40px 0;}")
        self.hint_lbl.setAlignment(Qt.AlignCenter)
        mv.addWidget(self.hint_lbl, 1)

        self.detail_box = QWidget()
        self.detail_box.setObjectName("detailBox")
        dv = QVBoxLayout(self.detail_box)
        dv.setContentsMargins(0, 0, 0, 0)
        dv.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        self.title_lbl = _ElidedLabel("")
        self.meta_lbl = CaptionLabel("")
        self.star_btn = QPushButton("★")   # U+2605 + 自给 color，绝不用 ⭐
        self.star_btn.setFixedSize(28, 28)
        self.star_btn.setCursor(Qt.PointingHandCursor)
        self.star_btn.clicked.connect(self._star_clicked)
        head.addWidget(self.title_lbl, 1)
        head.addWidget(self.meta_lbl)
        head.addWidget(self.star_btn)
        dv.addLayout(head)

        self.shot_lbl = _ClickableLabel()
        self.shot_lbl.setAlignment(Qt.AlignCenter)
        self.shot_lbl.setCursor(Qt.PointingHandCursor)
        self.shot_lbl.setToolTip("点击用系统默认程序打开")
        self.shot_lbl.setStyleSheet(
            "border:1px solid #e6e8f2; border-radius:12px;"
            " background:#f7f8fc;")
        self.shot_lbl.clicked.connect(self._open_shot)
        self.shot_lbl.hide()
        dv.addWidget(self.shot_lbl)

        self.body = QTextBrowser()
        # 内链 spore:// 自己接（核实按钮锚点），外链走系统浏览器
        self.body.setOpenLinks(False)
        self.body.setOpenExternalLinks(False)
        self.body.anchorClicked.connect(self._on_anchor)
        self.body.setStyleSheet("QTextBrowser{background:#ffffff; border:none;}")
        dv.addWidget(self.body, 1)

        # 接续对话输入行（2026-10-03 用户点名：记录页历史会话要能追问）
        # 发出后主窗把该会话收编给引擎，回答在作答浮窗流式继续，落库更新本会话
        foot = QHBoxLayout()
        foot.setSpacing(8)
        self.followup_input = QLineEdit()
        self.followup_input.setPlaceholderText(
            "接着问…（Enter 发送 · 回答在作答浮窗继续）")
        self.followup_send = PrimaryPushButton("↑")
        self.followup_send.setFixedSize(40, 40)
        self.followup_send.setToolTip("发送")
        foot.addWidget(self.followup_input, 1)
        foot.addWidget(self.followup_send)
        # 🚫 中止（2026-10-03 反馈：只有发送没有禁用按钮）——与面板 🚫 同语义
        self.cancel_btn = QPushButton("🚫")
        self.cancel_btn.setFixedSize(40, 40)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setToolTip("停止本回合")
        self.cancel_btn.setStyleSheet(
            "QPushButton{background:transparent; border:none; font-size:16px;"
            " color:#a3a8c2; border-radius:10px;}"
            "QPushButton:hover{background:#fdecef; color:#d02747;}")
        foot.addWidget(self.cancel_btn)
        dv.addLayout(foot)
        self.followup_send.clicked.connect(self._send_followup)
        self.followup_input.returnPressed.connect(self._send_followup)
        self.cancel_btn.clicked.connect(self._emit_cancel)
        mv.addWidget(self.detail_box, 1)
        self.detail_box.hide()

        root.addWidget(side)
        root.addWidget(self.main_box, 1)

        # 初始选中「全部」（2026-10-03 反馈：两个都不选中看着诡异）
        self._set_seg(False)
        # 自动加载（2026-10-03 反馈）：以前只在首次切入标签页拉一次，
        # 点进去可能空白、狂点刷新也不显示——开机即拉，标签页每次切入再拉
        self.load_categories()
        self.reload()

    def _emit_cancel(self):
        self.cancelRequested.emit()

    def _on_anchor(self, url: QUrl):
        href = url.toString()
        if href.startswith("spore://"):
            if href == "spore://verify" and self.current_id:
                self.verifyRequested.emit(self.current_id)
            return
        QDesktopServices.openUrl(url)   # 普通链接照旧外开

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not self._shot_pm.isNull():   # 窗口尺寸变了重裁截图
            self._scale_shot()

    # ---------- 数据 ----------
    def reload(self):
        """一次拉全量（size=200 上限），分组/过滤全在客户端做。"""
        if self._task is not None and self._task.isRunning():
            return
        if self._current_row() is None:
            self.hint_lbl.setText("加载中…")
        self._task = _QueryTask(self.api, {"page": 1, "size": FETCH_SIZE}, self)
        self._task.ok.connect(self._on_rows)
        self._task.failed.connect(self._on_error)
        self._task.start()

    def load_categories(self):
        """分类树数据（后台取；到达后重画，拿不到不阻断列表）。

        从前是主线程同步请求——后端半死时 UI 卡 15s、点啥都没反应（§ 反馈）。
        """
        if self._cat_task is not None and self._cat_task.isRunning():
            return
        self._cat_task = _CatTask(self.api, self)
        self._cat_task.ok.connect(self._on_cats)
        self._cat_task.failed.connect(lambda _m: self._render_tree())  # 维持现状
        self._cat_task.start()

    def _on_cats(self, cats: list[dict]):
        self._cats = cats
        self._render_tree()

    def _on_rows(self, data: dict):
        self.rows = data.get("list", [])
        ids = {str(r.get("id")) for r in self.rows}
        if self.current_id not in ids:
            self.current_id = ""
        self._render_tree()
        row = self._current_row()
        if row is not None:
            self._render_detail(row)
        self._update_hint()

    def _on_error(self, msg: str):
        self._err(f"加载失败：{msg}")
        self._update_hint()

    def _err(self, msg: str):
        InfoBar.error("操作失败", msg, parent=self, duration=3200,
                      position=InfoBarPosition.TOP)

    # ---------- 左栏渲染：科目行 + 会话行 ----------
    def _clear_box(self, box: QVBoxLayout, keep_stretch: bool = True):
        while box.count():
            item = box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        if keep_stretch:
            box.addStretch(1)

    @staticmethod
    def _tree_hint(text: str) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setStyleSheet(
            "QLabel{color:#a3a8c2; font-size:12.5px; background:transparent;"
            " padding:14px 6px;}")
        return lab

    def _filtered(self) -> list[dict]:
        """客户端过滤：关键词（标题）+ 收藏分段。"""
        kw = self.keyword.lower()
        out: list[dict] = []
        for r in self.rows:
            if self.fav and not r.get("fav"):
                continue
            if kw and kw not in str(r.get("title") or "").lower():
                continue
            out.append(r)
        return out

    def _add_session(self, art: dict, depth: int):
        card = SessionCard(art, depth)
        card.set_selected(str(art.get("id")) == self.current_id)
        card.opened.connect(self._select_session)
        card.renameRequested.connect(self._rename_session)
        card.deleteRequested.connect(self._delete_session)
        card.favToggled.connect(self._toggle_fav)
        card.moveRequested.connect(self._move_dialog)
        self._tree_box.insertWidget(self._tree_box.count() - 1, card)
        self._session_cards.append(card)

    def _render_tree(self):
        """左栏列表：科目行（展开时挂会话）+ 未分类会话殿后；收藏视图平铺。"""
        self._clear_box(self._tree_box)
        self._session_cards = []
        rows = self._filtered()

        if self.fav or self.keyword:
            # 第二形态（2026-10-03 反馈）：收藏分段 / 检索态都平铺命中会话、
            # 不摆科目（收藏沿 MV3 review.js:173-196，检索同款）
            if not rows:
                hint = (f"没有匹配「{self.keyword}」的会话。"
                        if self.keyword else
                        "没有收藏的会话。\n点行内 ★ 收藏，这里只留收藏的。")
                self._tree_box.insertWidget(self._tree_box.count() - 1,
                                             self._tree_hint(hint))
            for art in rows:
                self._add_session(art, 0)
            return

        if not rows and not self._cats:
            self._tree_box.insertWidget(
                self._tree_box.count() - 1,
                self._tree_hint("还没有搜题记录。\n回软件按 Alt+S 截一道题。"))
            return

        cat_ids = {str(c["id"]) for c in self._cats}
        grouped: dict[str, list[dict]] = {}
        loose: list[dict] = []          # 未分类（categoryId 空/已失效）
        for art in rows:
            cid = str(art.get("categoryId") or "")
            if cid and cid in cat_ids:
                grouped.setdefault(cid, []).append(art)
            else:
                loose.append(art)

        for c in self._cats:
            cid = str(c["id"])
            opened = cid in self._expanded
            row = CatRow(cid, str(c["name"]), int(c["depth"]),
                         int(c.get("status", 1) or 1))
            row.set_selected(opened)     # 展开中高亮（沿用选中底色）
            row.selected.connect(self._toggle_expand)
            row.renameRequested.connect(self._rename_category)
            row.deleteRequested.connect(self._delete_category)
            self._tree_box.insertWidget(self._tree_box.count() - 1, row)
            if opened:
                members = grouped.get(cid) or []
                if not members:
                    self._tree_box.insertWidget(self._tree_box.count() - 1,
                                                self._tree_hint("（空）"))
                for art in members:
                    self._add_session(art, int(c["depth"]) + 1)

        for art in loose:   # 未分类会话排在所有科目行之后（顶层）
            self._add_session(art, 0)

    # ---------- 右栏渲染：选中会话 ----------
    def _current_row(self) -> dict | None:
        if not self.current_id:
            return None
        for r in self.rows:
            if str(r.get("id")) == self.current_id:
                return r
        return None

    def _update_hint(self):
        if self._current_row() is not None:
            self.hint_lbl.hide()
            self.detail_box.show()
            return
        self.detail_box.hide()
        self.hint_lbl.setText(
            "还没有搜题记录。\n回软件按 Alt+S 截一道题。" if not self.rows
            else "左侧选一条会话查看内容")
        self.hint_lbl.show()

    def _render_detail(self, art: dict, keep_shot: bool = False):
        self.title_lbl.setText(str(art.get("title") or "新会话"))
        status = str(art.get("status") or "")
        self.meta_lbl.setText(
            f"{STATUS_LABEL.get(status, status)} · {_fmt_stamp(art.get('updateTime'))}")
        self._sync_star()
        # 截图：本地图等比缩放（最大高 320），点击用系统默认程序打开。
        # attachmentPath 恒空时回退消息里的题图（push-attachment 不回写行）；
        # 直播重渲（keep_shot）不动截图，别每 200ms 重解码一遍题图
        if not (keep_shot and not self._shot_pm.isNull()):
            self._shot_path = article_shot(art, self.api)
            self._shot_pm = (QPixmap(self._shot_path)
                             if self._shot_path else QPixmap())
            if self._shot_pm.isNull():
                self.shot_lbl.clear()
                self.shot_lbl.hide()
            else:
                self._scale_shot()
                self.shot_lbl.show()
        # 消息流：markdown HTML（think 绝不渲染）
        self.body.setHtml(
            '<div style="font-size:15px; line-height:1.6; color:#1a1d2e;">'
            f"{_detail_html(art)}</div>")
        bar = self.body.verticalScrollBar()
        if self._scroll_bottom_once:   # 接续 turn-end 后的首次重渲：留在底部
            self._scroll_bottom_once = False
            bar.setValue(bar.maximum())
        else:
            bar.setValue(0)

    def _scale_shot(self):
        if self._shot_pm.isNull():
            return
        avail = self.width() - 324       # 280 左栏 + 右栏左右留白
        if avail < 200:                  # 还没布局好 → 兜底宽度
            avail = 860
        self.shot_lbl.setPixmap(
            self._shot_pm.scaled(avail, 320, Qt.KeepAspectRatio,
                                 Qt.SmoothTransformation))

    def _open_shot(self):
        if self._shot_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._shot_path))

    def _sync_star(self):
        on = bool((self._current_row() or {}).get("fav"))
        fg = ACCENT if on else "#b3b8cd"
        self.star_btn.setStyleSheet(
            f"QPushButton{{background:transparent; border:none; color:{fg};"
            " font-size:18px; border-radius:6px;}"
            "QPushButton:hover{background:#f1f3fb; color:#db2777;}")
        self.star_btn.setToolTip("取消收藏" if on else "收藏此会话")

    def _star_clicked(self):
        row = self._current_row()
        if row is not None:
            self._toggle_fav(str(row.get("id")), bool(row.get("fav")))

    def _send_followup(self):
        """记录页接续追问：带当前会话 id 交给主窗（回答在**本页右栏**直播）。

        这里不清输入框——主窗判定可发（引擎没在跑别的回合）成功后才清，
        被拒时文字留住。
        """
        text = self.followup_input.text().strip()
        if text and self.current_id:
            self.followupRequested.emit(self.current_id, text)

    # ---------- 接续直播（2026-10-03 反馈：追问就地渲染，不开悬浮窗） ----------
    def follow_turn(self, sess: Session):
        """记录页发起的接续回合开跑：右栏直播 engine.session，200ms 节流重渲。"""
        self._live = sess

    def on_engine_event(self, sess: Session, ev: dict):
        """引擎事件 → 直播重渲。只认自己那场（sess 必须 is _live）——
        别的回合（Alt+S 截屏等）绝不能灌进本页视图。"""
        if sess is not self._live:
            return
        if ev.get("type") == "think-delta":
            return  # think 不渲染（全应用纪律）
        if ev.get("type") == "turn-end":
            self._flush_live()    # 收尾强制渲最后一次
            self._live = None     # 终稿交给 turn-end 后的 reload 用库里数据覆盖
            self._scroll_bottom_once = True
            return
        if not self._live_timer.isActive():
            self._live_timer.start()

    def _flush_live(self):
        self._live_timer.stop()
        if self._live is None or str(self._live.backend_id) != self.current_id:
            return   # 用户已切走：不许把直播灌进别的会话视图
        self._render_detail(self._live_art(), keep_shot=True)
        bar = self.body.verticalScrollBar()
        bar.setValue(bar.maximum())   # 流式期间跟随底部

    def _live_art(self) -> dict:
        """当前选中行 + 直播会话实时状态 → _render_detail 认的 art 形状。"""
        art = dict(self._current_row() or {})
        art["title"] = self._live.title
        art["status"] = self._live.status
        art["messages"] = [m.to_dict() for m in self._live.messages]
        return art

    # ---------- 交互：分段 / 检索 / 展开 ----------
    def _set_seg(self, fav: bool):
        self.fav = 1 if fav else 0
        for btn, on in ((self.seg_all, not fav), (self.seg_fav, fav)):
            bg = "#ffffff" if on else "transparent"
            fg = "#14162a" if on else "#4a5070"
            btn.setStyleSheet(
                f"QPushButton{{background:{bg}; color:{fg}; border:none;"
                " border-radius:8px; font-size:13px; font-weight:600;}")
        self._render_tree()

    def _do_search(self):
        self.keyword = self.search.text().strip()
        self._render_tree()

    def _toggle_expand(self, cat_id: str, _name: str = ""):
        """分类行点击 = 展开该科目下的会话，再点 = 收起（不改右栏内容）。"""
        if cat_id in self._expanded:
            self._expanded.discard(cat_id)
        else:
            self._expanded.add(cat_id)
        self._render_tree()

    # ---------- 会话：选中 / 重命名 / 删除 / 收藏 / 移动 ----------
    def _select_session(self, art_id: str):
        row = next((r for r in self.rows if str(r.get("id")) == art_id), None)
        if row is None:
            return
        self.current_id = art_id
        self._scroll_bottom_once = False   # 手动点开：照旧从顶部读
        for card in self._session_cards:
            card.set_selected(card._id == art_id)
        self._render_detail(row)
        self._update_hint()

    def _rename_session(self, art_id: str, title: str):
        new = _InputDialog.get_text("重命名会话", title, self.window())
        if not new or new == title:
            return
        try:
            self.api.update_article(art_id, title=new)
            self.reload()
        except (ApiError, NetworkError) as e:
            self._err(f"重命名失败：{e}")

    def _delete_session(self, art_id: str, title: str):
        box = MessageBox("删除这个会话？",
                         f"确定删除「{title}」吗？截图、回答与核实记录会一并"
                         "删除，不可恢复。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_article(art_id)
            row = next((r for r in self.rows
                        if str(r.get("id")) == art_id), None)
            if row is not None:
                purge_article_files(row, self.api)  # 删会话连带删题图
            self.reload()
        except (ApiError, NetworkError) as e:
            self._err(f"删除失败：{e}")

    def _toggle_fav(self, art_id: str, cur: bool):
        try:
            self.api.update_article(art_id, fav=0 if cur else 1)
        except (ApiError, NetworkError) as e:
            self._err(f"收藏失败：{e}")
            return
        # 乐观更新 + toast（MV3 review.js:261-268）；收藏不重排
        for row in self.rows:
            if str(row.get("id")) == art_id:
                row["fav"] = 0 if cur else 1
        for card in self._session_cards:
            if card._id == art_id:
                card.set_fav(not cur)
        if art_id == self.current_id:
            self._sync_star()
        InfoBar.success("已收藏" if not cur else "已取消收藏",
                        "会话列表里会标出这颗星" if not cur else "已取消标记",
                        parent=self, duration=2200,
                        position=InfoBarPosition.TOP)

    def _move_dialog(self, art_id: str):
        """会话行 ⇄ 按钮 → 「移入科目」模态框（2026-10-03 用户点名不要菜单）。"""
        if not self._cats:
            InfoBar.warning("还没有科目", "先点「＋ 新建科目」，再把会话移进去",
                            parent=self, duration=2600,
                            position=InfoBarPosition.TOP)
            return
        cur = next((str(r.get("categoryId") or "") for r in self.rows
                    if str(r.get("id")) == art_id), "")
        target = _MoveDialog.get_target(self._cats, cur, self.window())
        if target is None or target == cur:
            return          # 取消，或本来就在这个科目
        self._move(art_id, target)

    def _move(self, art_id: str, cat_id: str):
        try:
            if cat_id:
                self.api.update_article(art_id, category_id=cat_id)
            else:
                self.api.update_article(art_id, category_id="")
            self.load_categories()   # 分组变了：科目树 + 列表都重画
            self.reload()
        except (ApiError, NetworkError) as e:
            self._err(f"移动失败：{e}")

    # ---------- 分类：新建 / 重命名 / 启停 / 删除 ----------
    def _new_category(self):
        name = _InputDialog.get_text("新建科目", "", self.window())
        if not name:
            return
        try:
            self.api.create_category(name)
            self.load_categories()
        except (ApiError, NetworkError) as e:
            self._err(f"新建失败：{e}")

    def _rename_category(self, cat_id: str, name: str):
        new = _InputDialog.get_text("重命名科目", name, self.window())
        if not new or new == name:
            return
        try:
            self.api.rename_category(cat_id, new)
            self.load_categories()
        except (ApiError, NetworkError) as e:
            self._err(f"改名失败：{e}")

    def _delete_category(self, cat_id: str, name: str):
        box = MessageBox("删除这个科目？",
                         f"确定删除「{name}」吗？其下会话会被置为未分组，"
                         "不会删除会话本身。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_category(cat_id)
            self._expanded.discard(cat_id)
            self.load_categories()
            self.reload()
        except (ApiError, NetworkError) as e:
            self._err(f"删除失败：{e}")

def _flatten(nodes: list[dict], depth: int = 0) -> list[dict]:
    """分类树 → 扁平列表（带缩进层级与 status），children 键随 02 接口。"""
    out: list[dict] = []
    for n in nodes:
        out.append({"id": n.get("id"), "name": str(n.get("name", "")),
                    "depth": depth, "status": n.get("status", 1)})
        out.extend(_flatten(n.get("children") or [], depth + 1))
    return out
