"""主窗口：三页签 FluentWindow（搜题记录 / 日志 / 设置）。

页内实现见 records.py / log_page.py / settings.py（MV3 options/review 同构）；
截屏热键 Alt+S、回答面板 Alt+Z（与 MV3 drawer.js 同键位）挂在这里。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
from qfluentwidgets import FluentIcon, FluentWindow, InfoBar, InfoBarPosition

from .answer.engine import AgentEngine
from .answer.settings import load_from_env
from .answer_window import AnswerWindow
from .api import ApiClient
from .app_icon import app_icon
from .capture import CaptureController, HotkeyManager
from .log import get_logger
from .log_page import LogPane
from .records import RecordsPane
from .settings import SettingsPane
from .settings_store import apply_to_llm

LOG = get_logger()


class MainWindow(FluentWindow):
    captureRequested = Signal()  # keyboard 钩子线程只许 emit，Qt 自动排队回主线程
    toggleAnswerRequested = Signal()  # Alt+Z 同理：钩子线程不许碰 widget
    # 引擎事件必须走真 Signal：普通 callable 从 worker 线程直接调用 = 在 worker
    # 线程里砸 widget（黑窗/卡顿/落库定时器建错线程的根因），AutoConnection 才会排队
    engineEvent = Signal(object)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Spore 搜题内容管理系统")
        # 用户 2026-10-02：「GUI 应用的长宽都不够」——默认 1280×860，下限 1024×700
        self.resize(1280, 860)
        self.setMinimumSize(1024, 700)

        # LLM 配置先行：环境变量为底，UI 设置文件补缺（env 显式设置者优先）
        self.llm_settings = apply_to_llm(load_from_env())
        self._delta_counts: dict[str, int] = {}
        self._t_turn = time.monotonic()  # 回合计时，_on_captured 时重置

        self.records = RecordsPane(api)
        self.log_page = LogPane()
        self.settings = SettingsPane(api, self.llm_settings)

        # 三页对齐 MV3 options 左索引：搜题记录 / 日志 / 设置
        # （原「科目管理」页已并入搜题记录页侧栏 —— 用户 2026-10-02 拍板）
        self.addSubInterface(self.records, FluentIcon.DOCUMENT, "搜题记录")
        self.addSubInterface(self.log_page, FluentIcon.HISTORY, "日志")
        self.addSubInterface(self.settings, FluentIcon.SETTING, "设置")
        # 每页首次切入拉一次数据（lazy，失败不阻断）
        # 实测：本 flavor 的 FluentWindow 无 tabBar，切页信号在 stackedWidget 上
        self._booted: set[str] = set()
        self.stackedWidget.currentChanged.connect(self._on_tab_changed)

        # ---- 期5：作答内核 + 浮窗 + 热键 ----
        self.engineEvent.connect(self._engine_event)  # 队列化到主线程
        self.engine = AgentEngine(self.llm_settings, self.engineEvent.emit)
        self.answer_window = AnswerWindow(self.llm_settings)
        self.answer_window.attach_engine(self.engine)
        self.answer_window.attach_api(api)  # 面板 💬 会话列表 / ★ 收藏要打后端
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
        tray = QSystemTrayIcon(app_icon(), self)
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
        elif widget is self.log_page:
            self.log_page.refresh()
        elif widget is self.settings:
            self.settings.refresh()

    # ---------- 热键 ----------
    def _toggle_answer_window(self):
        # 只显隐浮窗；截屏走 captureRequested，两者绝不能串线
        aw = self.answer_window
        if aw.isVisible():
            aw.hide()
            LOG.info("alt+z → panel hidden")
        else:
            aw.show()
            aw.raise_()
            LOG.info("alt+z → panel shown at (%d,%d)", aw.x(), aw.y())

    # ---------- 提示（主窗隐藏时 InfoBar 没人看得见 → 改走托盘气泡） ----------
    def _notify(self, level: str, title: str, msg: str,
                duration: int = 6000):
        LOG.info("notify %s/%s: %s", level, title, str(msg)[:120])
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
        self._t_turn = time.monotonic()
        LOG.info("captured %s sel=%s ready=%s",
                 Path(path).name, tuple(round(v) for v in sel),
                 self.llm_settings.ready)
        if not self.llm_settings.ready:
            self._notify("error", "无法作答",
                         "缺少 LLM key，截图已存盘：" + path, 6000)
            return
        self.answer_window.new_turn(path, sel=sel)

    def _followup(self, text: str):
        if not self.engine.send_followup(text):
            self._notify("warning", "稍等", "当前回合还没结束", 2500)

    # ---------- 引擎事件（worker 线程 emit → engineEvent 队列回主线程） ----------
    _DELTA_TYPES = {"answer-delta", "chat-delta", "think-delta", "verify-delta"}

    def _engine_event(self, ev: dict):
        t = ev.get("type")
        # 先记日志再处理：处理阶段若致命，日志必须已经落盘（崩溃定位用）
        if t in self._DELTA_TYPES:  # 流式 delta 只计数，逐条记会把日志刷爆
            self._delta_counts[t] = self._delta_counts.get(t, 0) + 1
        elif t == "error":
            LOG.error("engine error: %s", str(ev.get("message", ""))[:200])
        else:
            extra = (ev.get("status") or ev.get("brief") or ev.get("title")
                     or "")
            LOG.info("engine event %s %s", t, extra)
        self.answer_window.on_event(ev)
        if t == "turn-end":
            LOG.info("turn-end in %.1fs deltas=%s",
                     time.monotonic() - self._t_turn, self._delta_counts)
            self._delta_counts = {}
            if not ev.get("error") and not ev.get("aborted"):
                self._persist_turn()

    def _persist_turn(self):
        """回合结束落库：新回合 POST /articles，接续历史 PUT /articles/{id}。"""
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._persist_turn_sync)

    def _persist_turn_sync(self):
        sess = self.engine.session
        if not any(m.role == "assistant" for m in sess.messages):
            return
        t0 = time.monotonic()
        try:
            messages = [m.to_dict() for m in sess.messages]
            if sess.backend_id:
                # 历史接续回合：后端 ArticleReq.messages 非 null 即重写正文（§8-2）；
                # 接续会话不带新题图，题图只在新回合 POST 后上推
                art = self.api.update_article(
                    sess.backend_id, title=sess.title,
                    status=sess.status or "done", messages=messages)
                art_id = sess.backend_id
            else:
                art = self.api.create_article({
                    "title": sess.title,
                    "status": sess.status or "done",
                    "messages": messages,
                })
                art_id = art.get("id") if isinstance(art, dict) else None
                if art_id and sess.image_path:
                    self.api.push_attachment(art_id, sess.image_path)
            if art_id:  # 落库后才有 id：面板 ★ 才知道收藏对象
                self.answer_window.set_current_article(
                    art_id, bool(art.get("fav")) if isinstance(art, dict)
                    else False)
            LOG.info("persisted turn id=%s put=%s in %.0fms", art_id,
                     bool(sess.backend_id), (time.monotonic() - t0) * 1000)
        except Exception as e:  # noqa: BLE001 —— 落库失败提示即可，不掀桌
            LOG.error("persist failed in %.0fms: %s",
                      (time.monotonic() - t0) * 1000, e)
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
            LOG.info("close → tray (hotkeys stay)")
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
        LOG.info("really quit (hotkeys unregistered)")
        super().closeEvent(ev)
