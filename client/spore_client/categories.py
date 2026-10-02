"""科目管理页：多级分类树 + 增删改/启停（评分表 1.5 分科目功能的客户端）。

树数据 GET /categories（02 接口：children 嵌套）；操作全走 REST。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QTreeWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ToolButton,
    TreeWidget,
)

from .api import ApiClient, ApiError, NetworkError


class _TreeTask(QThread):
    ok = Signal(list)
    failed = Signal(str)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api

    def run(self):
        try:
            data = self.api.category_tree()
            self.ok.emit(data or [])
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


class CategoriesPane(QWidget):
    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self._task: _TreeTask | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # ---- 输入行：新建科目 ----
        add_row = QHBoxLayout()
        self.name_input = LineEdit()
        self.name_input.setPlaceholderText("新科目名（留空选中的父级为其子级）")
        self.parent_label = CaptionLabel("父级：无（顶级）")
        add_btn = PrimaryPushButton("新增科目")
        add_btn.clicked.connect(self._create)
        self.name_input.returnPressed.connect(self._create)
        add_row.addWidget(self.name_input, 1)
        add_row.addWidget(self.parent_label)
        add_row.addWidget(add_btn)
        root.addLayout(add_row)

        # ---- 树 ----
        self.tree = TreeWidget(self)
        self.tree.setHeaderLabels(["科目", "状态", "内容数", ""])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 70)
        self.tree.setColumnWidth(2, 80)
        self.tree.itemSelectionChanged.connect(self._on_select)
        self.tree.setAlternatingRowColors(True)
        root.addWidget(self.tree, 1)

        # ---- 操作行 ----
        op = QHBoxLayout()
        self.rename_btn = PushButton("重命名")
        self.status_btn = PushButton("启停")
        self.delete_btn = PushButton("删除")
        self.refresh_btn = ToolButton(FluentIcon.SYNC)
        self.rename_btn.clicked.connect(self._rename)
        self.status_btn.clicked.connect(self._toggle_status)
        self.delete_btn.clicked.connect(self._delete)
        self.refresh_btn.clicked.connect(self.reload)
        op.addWidget(self.rename_btn)
        op.addWidget(self.status_btn)
        op.addWidget(self.delete_btn)
        op.addStretch(1)
        op.addWidget(self.refresh_btn)
        root.addLayout(op)

        self.status_label = CaptionLabel("")
        root.addWidget(self.status_label)
        self._nodes: dict[str, dict] = {}  # id → 节点原始数据

    # ---------- 数据 ----------
    def reload(self):
        if self._task is not None and self._task.isRunning():
            return
        self.status_label.setText("加载中…")
        self._task = _TreeTask(self.api, self)
        self._task.ok.connect(self._on_tree)
        self._task.failed.connect(
            lambda m: self.status_label.setText(f"加载失败：{m}"))
        self._task.start()

    def _on_tree(self, nodes: list):
        self.tree.clear()
        self._nodes.clear()
        for n in nodes:
            self._add_item(None, n)
        self.tree.expandAll()
        self.status_label.setText(f"共 {len(self._nodes)} 个科目")

    def _add_item(self, parent, node: dict):
        nid = str(node.get("id", ""))
        self._nodes[nid] = node
        status = "启用" if node.get("status", 1) == 1 else "停用"
        item = QTreeWidgetItem(
            [str(node.get("name", "")), status,
             str(node.get("articleCount", node.get("count", "")))])
        item.setData(0, Qt.UserRole, nid)
        if status == "停用":
            for i in range(4):
                item.setForeground(i, QColor("#999"))
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        for c in node.get("children") or []:
            self._add_item(item, c)

    # ---------- 交互 ----------
    def _selected(self) -> tuple[str, dict] | None:
        items = self.tree.selectedItems()
        if not items:
            return None
        nid = items[0].data(0, Qt.UserRole)
        return nid, self._nodes.get(nid, {})

    def _on_select(self):
        sel = self._selected()
        self.parent_label.setText(
            f"父级：{sel[1].get('name', '')}" if sel else "父级：无（顶级）")

    def _guard(self) -> tuple[str, dict] | None:
        sel = self._selected()
        if sel is None:
            self.status_label.setText("先在树里选一个科目")
        return sel

    def _create(self):
        name = self.name_input.text().strip()
        if not name:
            self.status_label.setText("科目名不能为空")
            return
        sel = self._selected()
        parent_id = sel[0] if sel else None
        try:
            self.api.create_category(name, parent_id)
            self.name_input.clear()
            self.reload()
        except (ApiError, NetworkError) as e:
            self.status_label.setText(f"新增失败：{e}")

    def _rename(self):
        """重命名 = 把输入框当编辑位（选中 → 输入框回填 → 确认），不另开弹窗。"""
        sel = self._guard()
        if not sel:
            return
        new_name = self.name_input.text().strip()
        if not new_name or new_name == sel[1].get("name"):
            # 第一次点：回填现名进输入框，让用户直接改
            self.name_input.setText(sel[1].get("name", ""))
            self.name_input.setFocus()
            self.name_input.selectAll()
            self.status_label.setText("改完再点一次「重命名」确认")
            return
        try:
            self.api.rename_category(sel[0], new_name)
            self.name_input.clear()
            self.reload()
        except (ApiError, NetworkError) as e:
            self.status_label.setText(f"改名失败：{e}")

    def _toggle_status(self):
        sel = self._guard()
        if not sel:
            return
        cur = sel[1].get("status", 1)
        try:
            self.api.change_category_status(sel[0], 0 if cur == 1 else 1)
            self.reload()
        except (ApiError, NetworkError) as e:
            self.status_label.setText(f"启停失败：{e}")

    def _delete(self):
        sel = self._guard()
        if not sel:
            return
        box = MessageBox(
            "删除科目", f"删除「{sel[1].get('name', '')}」？其下内容会回未分组。", self.window())
        if not box.exec():
            return
        try:
            self.api.delete_category(sel[0])
            self.reload()
        except (ApiError, NetworkError) as e:
            self.status_label.setText(f"删除失败：{e}")
