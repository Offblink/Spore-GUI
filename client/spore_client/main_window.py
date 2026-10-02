"""主窗口：三页签 FluentWindow（搜题记录 / 科目管理 / 设置）。

页内实现见 records.py / categories.py / settings.py；
截屏热键 Alt+S、回答面板 Alt+Z（与 MV3 drawer.js 同键位）挂在这里。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
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

        # 关闭 → 托盘（2026-10-02 用户拍板）：窗口收起、进程与热键常驻，
        # 托盘菜单「退出」才真正注销热键退进程
        self._quitting = False
        self._tray_notified = False
        tray = QSystemTrayIcon(FluentIcon.SEARCH.icon(QColor("#00b7c3")), self)
        tray.setToolTip("Spore 搜题——双击打开，右键退出")
        self._tray_menu = QMenu()  # 防 GC
        self._tray_menu.addAction("打开主界面", self._show_main)
        self._tray_menu.addAction("退出 Spore", self._really_quit)
        tray.setContextMenu(self._tray_menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray  # 防 GC

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

    # ---------- 提示（主窗隐藏时 InfoBar 没人看得见 → 改走托盘气泡） ----------
    def _notify(self, level: str, title: str, msg: str,
                duration: int = 6000):
        if self.isVisible():
            (InfoBar.error if level == "error" else InfoBar.warning)(
                title, msg, parent=self, duration=duration,
                position=InfoBarPosition.TOP)
        else:
            icon = (QSystemTrayIcon.MessageIcon.Critical if level == "error"
                    else QSystemTrayIcon.MessageIcon.Warning)
            self._tray.showMessage(title, msg, icon, duration)

    # ---------- 截屏 → 作答 ----------
    def _on_captured(self, path: str,
                     sel: tuple[float, float, float, float]):
        if not self.llm_settings.ready:
            self._notify("error", "无法作答",
                         "缺少 LLM key，截图已存盘：" + path, 6000)
            return
        self.answer_window.new_turn(path, sel=sel)

    def _followup(self, text: str):
        if not self.engine.send_followup(text):
            self._notify("warning", "稍等", "当前回合还没结束", 2500)

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
            self._notify("warning", "落库失败", str(e), 5000)

    # ---------- 托盘/单例唤醒（关闭 = 收起，不是退出） ----------
    def _show_main(self):
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleTrigger):
            self._show_main()

    def _really_quit(self):
        self._quitting = True
        self.close()  # closeEvent 走真退分支：注销热键、停引擎
        QApplication.instance().quit()

    def closeEvent(self, ev):
        if not self._quitting:
            ev.ignore()
            self.hide()
            self.answer_window.hide()
            if not self._tray_notified:
                self._tray_notified = True
                self._tray.showMessage(
                    "Spore 仍在运行", "已收进托盘：双击托盘图标打开，右键退出",
                    QSystemTrayIcon.MessageIcon.Information, 3000)
            return
        for h in self._hotkeys:
            h.close()
        self._capture.shutdown()
        self.engine.cancel()
        self.answer_window.close()
        super().closeEvent(ev)
