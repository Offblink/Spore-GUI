"""主窗口：三页签 FluentWindow（搜题记录 / 科目管理 / 设置）。

页内实现见 records.py / categories.py / settings.py；
截屏热键 Alt+S、回答面板 Alt+Z（与 MV3 drawer.js 同键位）挂在这里。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from qfluentwidgets import FluentIcon, FluentWindow, InfoBar, InfoBarPosition

from .answer.engine import AgentEngine
from .answer.settings import load_from_env
from .answer_window import AnswerWindow
from .api import ApiClient
from .capture import CaptureController, HotkeyManager
from .categories import CategoriesPane
from .records import RecordsPane
from .settings import SettingsPane


class MainWindow(FluentWindow):
    captureRequested = Signal()  # keyboard 钩子线程只许 emit，Qt 自动排队回主线程
    toggleAnswerRequested = Signal()  # Alt+Z 同理：钩子线程不许碰 widget

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Spore 搜题内容管理系统")

        # LLM 配置先行：设置页要展示它
        self.llm_settings = load_from_env()

        self.records = RecordsPane(api)
        self.categories = CategoriesPane(api)
        self.settings = SettingsPane(api, self.llm_settings)

        self.addSubInterface(self.records, FluentIcon.DOCUMENT, "搜题记录")
        self.addSubInterface(self.categories, FluentIcon.FOLDER, "科目管理")
        self.addSubInterface(self.settings, FluentIcon.SETTING, "设置")
        # 每页首次切入拉一次数据（lazy，失败不阻断）
        # 实测：本 flavor 的 FluentWindow 无 tabBar，切页信号在 stackedWidget 上
        self._booted: set[str] = set()
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

        # ---- 期5：作答内核 + 浮窗 + 热键 ----
        self.engine = AgentEngine(self.llm_settings, self._engine_event)
        self.answer_window = AnswerWindow(self.llm_settings)
        self.answer_window.attach_engine(self.engine)
        self.answer_window.followupRequested.connect(self._followup)

        # 截屏完成 → 喂给作答浮窗（P3 只落盘的那一步现在接上了）
        self._capture = CaptureController(self._on_captured)
        self.captureRequested.connect(self._capture.start)

        self._hotkeys: list[HotkeyManager] = [
            HotkeyManager(self.captureRequested.emit, "alt+s"),
            HotkeyManager(self.toggleAnswerRequested.emit, "alt+z"),
        ]
        self.toggleAnswerRequested.connect(self._toggle_answer_window)
        if self.llm_settings.errors:
            self._llm_errors = InfoBar.warning(  # 存引用防 GC
                "作答未就绪", "；".join(self.llm_settings.errors),
                parent=self, duration=8000, position=InfoBarPosition.TOP)

    # ---------- 页签懒加载 ----------
    def _on_tab_changed(self, idx: int):
        widget = self.stackedWidget.widget(idx)
        key = getattr(widget, "objectName", lambda: "")() or str(id(widget))
        if key in self._booted:
            return
        self._booted.add(key)
        if widget is self.records:
            self.records.load_categories()
            self.records.reload()
        elif widget is self.categories:
            self.categories.reload()
        elif widget is self.settings:
            self.settings.refresh()

    # ---------- 热键 ----------
    def _toggle_answer_window(self):
        # 只显隐浮窗；截屏走 captureRequested，两者绝不能串线
        aw = self.answer_window
        if aw.isVisible():
            aw.hide()
        else:
            aw.show()
            aw.raise_()

    # ---------- 截屏 → 作答 ----------
    def _on_captured(self, path: str):
        if not self.llm_settings.ready:
            InfoBar.error("无法作答", "缺少 LLM key，截图已存盘：" + path,
                          parent=self, duration=6000,
                          position=InfoBarPosition.TOP)
            return
        self.answer_window.new_turn(path)

    def _followup(self, text: str):
        if not self.engine.send_followup(text):
            InfoBar.warning("稍等", "当前回合还没结束", parent=self,
                            duration=2500, position=InfoBarPosition.TOP)

    # ---------- 引擎事件（后台线程 emit → Qt 自动队列回主线程） ----------
    def _engine_event(self, ev: dict):
        self.answer_window.on_event(ev)
        if ev.get("type") == "turn-end" and not ev.get("error") \
                and not ev.get("aborted"):
            self._persist_turn()

    def _persist_turn(self):
        """回合结束落库：POST /articles + 题图 push-attachment（REST 铁律）。"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._persist_turn_sync)

    def _persist_turn_sync(self):
        sess = self.engine.session
        if not any(m.role == "assistant" for m in sess.messages):
            return
        try:
            body = {
                "title": sess.title,
                "status": sess.status or "done",
                "messages": [m.to_dict() for m in sess.messages],
            }
            art = self.api.create_article(body)
            art_id = art.get("id") if isinstance(art, dict) else None
            if art_id and sess.image_path:
                self.api.push_attachment(art_id, sess.image_path)
        except Exception as e:  # noqa: BLE001 —— 落库失败提示即可，不掀桌
            InfoBar.warning("落库失败", str(e), parent=self, duration=5000,
                            position=InfoBarPosition.TOP)

    def closeEvent(self, ev):
        for h in self._hotkeys:
            h.close()
        self._capture.shutdown()
        self.engine.cancel()
        self.answer_window.close()
        super().closeEvent(ev)
