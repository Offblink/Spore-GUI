"""日志页：MV3 options.html 卡四 —— client.log 末尾 300 行 + 刷新/复制/清空。

- 深色终端块（底 #12162a 字 #bfe9d0）max-height 260 滚动；
- 4 秒自动刷新，内容没变不重设（避免滚动跳位）；
- 文件可能几 MB，只从尾部读 256KB，绝不整读；
- 「清空」= 截断文件；RotatingFileHandler 持有句柄，拒绝写时收敛到提示不抛。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import PushButton

from .log import LOG_DIR, get_logger
from .settings import BTN2_STYLE, build_card, hint_label

LOG = get_logger()

LOG_FILE: Path = LOG_DIR / "client.log"
_TAIL_BYTES = 262_144          # 256KB 足够截出末 300 行
_TAIL_LINES = 300
_EMPTY = "（还没有日志）"
_LOGBOX_STYLE = (
    "QPlainTextEdit { background: #12162a; color: #bfe9d0;"
    " border: 1px solid #12162a; border-radius: 10px; padding: 10px 12px;"
    " font-family: 'Cascadia Code', Consolas, 'Courier New', monospace;"
    " font-size: 12px; selection-background-color: #2a3350;"
    " selection-color: #ffffff; }"
)


def tail_text(path: Path, max_lines: int = _TAIL_LINES,
              max_bytes: int = _TAIL_BYTES) -> str:
    """日志末尾 max_lines 行；文件缺失/不可读 → ""（不抛）。"""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            start = max(0, f.tell() - max_bytes)
            f.seek(start)
            data = f.read()
    except OSError:
        return ""
    lines = data.decode("utf-8", errors="replace").splitlines()[-max_lines:]
    if start > 0 and lines:
        lines = lines[1:]      # 起点落在行中间，首行是残片，丢掉
    return "\n".join(lines)


class LogPane(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("logPage")  # FluentWindow.addSubInterface 要求非空

        btns = QWidget()
        btn_box = QHBoxLayout(btns)
        btn_box.setContentsMargins(0, 0, 0, 0)
        btn_box.setSpacing(8)
        self.btn_refresh = PushButton("刷新")
        self.btn_refresh.setObjectName("btnLogRefresh")
        self.btn_copy = PushButton("复制")
        self.btn_copy.setObjectName("btnLogCopy")
        self.btn_clear = PushButton("清空")
        self.btn_clear.setObjectName("btnLogClear")
        for b in (self.btn_refresh, self.btn_copy, self.btn_clear):
            b.setStyleSheet(BTN2_STYLE)
        btn_box.addWidget(self.btn_refresh)
        btn_box.addWidget(self.btn_copy)
        btn_box.addWidget(self.btn_clear)

        card, lay, _title = build_card("日志（最近 300 条，排错用）", trailing=btns)
        self.view = QPlainTextEdit()
        self.view.setObjectName("logView")
        self.view.setReadOnly(True)
        self.view.setMaximumHeight(260)     # 深色块滚动（options.html .logbox）
        self.view.setStyleSheet(_LOGBOX_STYLE)
        self.view.setPlainText(_EMPTY)
        lay.addWidget(self.view)
        lay.addWidget(hint_label(
            "框选 / 起名 / 回答 / 镜像四条链路的事件都在这里（每 4 秒自动刷新）。"
            "出问题先点「复制」把末尾几十行发出来，别猜。"))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)
        root.addWidget(card)
        self.ops_note = QLabel("")
        self.ops_note.setObjectName("logOpsNote")
        self.ops_note.setStyleSheet("font-size: 12.5px; color: #7c819c;")
        root.addWidget(self.ops_note)
        root.addStretch(1)

        self.btn_refresh.clicked.connect(self.refresh)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_clear.clicked.connect(self._clear)

        self._timer = QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ---------- 展示 ----------
    def refresh(self) -> None:
        """读末 300 行；内容没变就不动控件（保滚动位置）。"""
        text = tail_text(LOG_FILE) or _EMPTY
        if text != self.view.toPlainText():
            self.view.setPlainText(text)

    def showEvent(self, ev):
        LOG.info("log page opened")
        self.refresh()
        super().showEvent(ev)

    def _copy(self):
        QGuiApplication.clipboard().setText(self.view.toPlainText())
        self.ops_note.setText("已复制到剪贴板（含末尾 300 条）")
        QTimer.singleShot(2200, self._clear_note)

    def _clear(self):
        try:
            with LOG_FILE.open("r+b") as f:
                f.truncate(0)
        except FileNotFoundError:
            pass
        except OSError as e:  # RotatingFileHandler 持句柄，可能拒绝（权限/占用）
            self.ops_note.setText(f"清空失败：{e}")
            return
        self.view.setPlainText(_EMPTY)
        self.ops_note.setText("日志已清空")

    def _clear_note(self):
        if self.ops_note.text() == "已复制到剪贴板（含末尾 300 条）":
            self.ops_note.setText("")
