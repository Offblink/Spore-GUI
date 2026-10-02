"""搜题记录页：分页列表 + 关键词/科目检索 + 详情 + 删除/移动科目。

数据全走 REST（GET /articles?...&page&size）；详情弹窗展示内容 JSON 的可读渲染。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QMenu, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    FluentIcon,
    MessageBox,
    PushButton,
    SearchLineEdit,
    TableWidget,
    ToolButton,
)

from .api import ApiClient, ApiError, NetworkError

PAGE_SIZE = 20

STATUS_LABEL = {
    "done": "完成", "error": "出错", "aborted": "已停止",
    "answering": "作答中", "verifying": "核实中",
}


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


class RecordsPane(QWidget):
    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.page = 1
        self.keyword = ""
        self.category_id = ""
        self.rows: list[dict] = []
        self._task: _QueryTask | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ---- 工具行 ----
        bar = QHBoxLayout()
        self.search = SearchLineEdit()
        self.search.setPlaceholderText("按标题检索…")
        self.search.setFixedWidth(240)
        self.search.searchButton.clicked.connect(self._do_search)
        self.search.returnPressed.connect(self._do_search)
        self.cat_box = ComboBox()
        self.cat_box.addItem("全部科目")
        self.cat_box.setFixedWidth(160)
        self.cat_box.currentIndexChanged.connect(self._cat_changed)
        self.refresh_btn = ToolButton(FluentIcon.SYNC)
        self.refresh_btn.setToolTip("刷新")
        self.refresh_btn.clicked.connect(self.reload)
        bar.addWidget(self.search)
        bar.addWidget(self.cat_box)
        bar.addWidget(self.refresh_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        # ---- 表格 ----
        self.table = TableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["标题", "状态", "科目", "更新时间", ""])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 120)
        self.table.setColumnWidth(3, 150)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda _: self._show_detail())
        root.addWidget(self.table, 1)

        # ---- 翻页 ----
        foot = QHBoxLayout()
        self.prev = PushButton("上一页")
        self.next = PushButton("下一页")
        self.page_label = CaptionLabel("第 1 页")
        self.prev.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        foot.addStretch(1)
        foot.addWidget(self.prev)
        foot.addWidget(self.page_label)
        foot.addWidget(self.next)
        foot.addStretch(1)
        root.addLayout(foot)

        self._cats: list[dict] = []

    # ---------- 数据 ----------
    def reload(self):
        if self._task is not None and self._task.isRunning():
            return
        self.page_label.setText("加载中…")
        self._task = _QueryTask(self.api, {
            "page": self.page, "size": PAGE_SIZE,
            "keyword": self.keyword or None,
            "category_id": self.category_id or None,
        }, self)
        self._task.ok.connect(self._on_rows)
        self._task.failed.connect(self._on_error)
        self._task.start()

    def load_categories(self):
        """科目下拉的数据（首次进来/科目页改动后调）。"""
        try:
            data = self.api.category_tree()
            self._cats = _flatten(data or [])
            self.cat_box.blockSignals(True)
            self.cat_box.clear()
            self.cat_box.addItem("全部科目")
            for c in self._cats:
                self.cat_box.addItem(c["label"])
            self.cat_box.setCurrentIndex(0)
            self.cat_box.blockSignals(False)
        except (ApiError, NetworkError):
            pass  # 下拉拿不到不阻断列表

    def _on_rows(self, data: dict):
        self.rows = data.get("list", [])
        total = data.get("total", 0)
        pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        self.page_label.setText(f"第 {self.page} / {pages} 页 · 共 {total} 条")
        self.table.setRowCount(len(self.rows))
        name_of = {c["id"]: c["label"] for c in self._cats}
        for r, row in enumerate(self.rows):
            self.table.setItem(r, 0, _cell(row.get("title", "")))
            self.table.setItem(
                r, 1, _cell(STATUS_LABEL.get(row.get("status", ""),
                                             row.get("status", ""))))
            self.table.setItem(r, 2,
                               _cell(name_of.get(row.get("categoryId") or "",
                                                 "未分组")))
            self.table.setItem(r, 3, _cell(str(row.get("updateTime", ""))[:19]))
            art_id = row.get("id")
            btn = PushButton("删除")
            btn.clicked.connect(lambda _, i=art_id: self._delete(i))
            self.table.setCellWidget(r, 4, btn)

    def _on_error(self, msg: str):
        self.page_label.setText(f"加载失败：{msg}")

    # ---------- 交互 ----------
    def _do_search(self):
        self.keyword = self.search.text().strip()
        self.page = 1
        self.reload()

    def _cat_changed(self, idx: int):
        self.category_id = "" if idx <= 0 else self._cats[idx - 1]["id"]
        self.page = 1
        self.reload()

    def _go(self, delta: int):
        self.page = max(1, self.page + delta)
        self.reload()

    def _selected_id(self) -> str | None:
        r = self.table.currentRow()
        if 0 <= r < len(self.rows):
            return self.rows[r].get("id")
        return None

    def _show_detail(self):
        art_id = self._selected_id()
        if not art_id:
            return
        try:
            art = self.api.article(art_id)
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"详情失败：{e}")
            return
        box = MessageBox(art.get("title", "详情"), self.window())
        box.contentLabel.setWordWrap(True)
        box.contentLabel.setText(_render_content(art))
        box.exec()

    def _delete(self, art_id: str):
        if not art_id:
            return
        box = MessageBox("删除这条记录？", "删除后手机端会同步移除（墓碑）。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_article(art_id)
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"删除失败：{e}")

    def contextMenuEvent(self, ev):
        art_id = self._selected_id()
        if not art_id or not self._cats:
            return
        menu = QMenu(self)
        move = menu.addMenu("移动到科目")
        for c in self._cats:
            act = move.addAction(c["label"])
            act.triggered.connect(
                lambda _, cid=c["id"], aid=art_id: self._move(aid, cid))
        menu.exec(ev.globalPos())

    def _move(self, art_id: str, cat_id: str):
        try:
            self.api.move_article(art_id, cat_id)
            self.reload()
        except (ApiError, NetworkError) as e:
            self.page_label.setText(f"移动失败：{e}")


def _cell(text: str):
    from PySide6.QtWidgets import QTableWidgetItem
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    return item


def _flatten(nodes: list[dict], depth: int = 0) -> list[dict]:
    """分类树 → 扁平列表（带缩进标签）；children 键随 02 接口。"""
    out: list[dict] = []
    for n in nodes:
        label = "　" * depth + str(n.get("name", ""))
        out.append({"id": n.get("id"), "label": label})
        out.extend(_flatten(n.get("children") or [], depth + 1))
    return out


def _render_content(art: dict) -> str:
    """content.messages → 人话（详情弹窗用）。"""
    content = art.get("content") or {}
    msgs = content.get("messages") if isinstance(content, dict) else content
    if isinstance(content, str):
        try:
            import json
            content = json.loads(content)
            msgs = content.get("messages", [])
        except (ValueError, TypeError):
            msgs = [{"role": "?", "text": content}]
    lines: list[str] = []
    for m in msgs or []:
        role = m.get("role", "")
        if role == "user":
            img = " [题图]" if m.get("hasImage") else ""
            lines.append(f"【题】{m.get('text') or '（截图）'}{img}")
        elif m.get("kind") == "answer":
            head = f"第{m['no']}题 " if m.get("no") else ""
            lines.append(f"【答案】{head}{m.get('ans', '')}")
            if m.get("why"):
                lines.append(f"解析：{m['why']}")
            if m.get("verifyNote"):
                mark = {"OK": "✔", "FIX": "⚠"}.get(
                    m.get("verifyVerdict", ""), "·")
                lines.append(f"{mark} 核实：{m['verifyNote']}")
        elif m.get("text"):
            lines.append(f"【追】{m['text']}")
    return "\n\n".join(lines) or "（空会话）"
