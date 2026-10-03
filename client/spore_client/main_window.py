"""主窗口：四页签 FluentWindow（搜题记录 / 日志 / 设置 / 帮助）。

页内实现见 records.py / log_page.py / settings.py（MV3 options/review 同构）；
截屏热键 Alt+S、回答面板 Alt+Z（与 MV3 drawer.js 同键位）挂在这里。
"""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
)
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
)

from .answer.engine import AgentEngine
from .answer.session import msgs_of, session_from_article
from .answer.settings import load_from_env
from .answer_window import AnswerWindow
from .api import ApiClient, ApiError, NetworkError
from .app_icon import app_icon
from .capture import CaptureController, HotkeyManager
from .help_page import HelpPane
from .log import get_logger
from .log_page import LogPane
from .pairing import LanTask, build_payload, initial_of, payload_image
from .records import RecordsPane
from .settings import SettingsPane
from .settings_store import apply_to_llm

LOG = get_logger()


class _MeTask(QThread):
    """取 /users/me（头像昵称首字母用）——主线程不发网络请求。"""

    ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api

    def run(self):
        try:
            self.ok.emit(self.api.me())
        except (ApiError, NetworkError) as e:
            self.failed.emit(str(e))


class MainWindow(FluentWindow):
    captureRequested = Signal()  # keyboard 钩子线程只许 emit，Qt 自动排队回主线程
    toggleAnswerRequested = Signal()  # Alt+Z 同理：钩子线程不许碰 widget
    # 引擎事件必须走真 Signal：普通 callable 从 worker 线程直接调用 = 在 worker
    # 线程里砸 widget（黑窗/卡顿/落库定时器建错线程的根因），AutoConnection 才会排队
    engineEvent = Signal(object)

    def __init__(self, api: ApiClient, parent=None):
        super().__init__(parent)
        self.api = api
        self.setWindowTitle("Spore")
        # 用户 2026-10-02：「GUI 应用的长宽都不够」——默认 1280×860，下限 1024×700
        self.resize(1280, 860)
        self.setMinimumSize(1024, 700)
        # 出生位置（2026-10-03 二改：不必紧贴左上，往右下一点，但必须完整在屏内）
        avail = QApplication.primaryScreen().availableGeometry()
        w, h = self.width(), self.height()
        x = max(avail.left(), min(avail.left() + 40, avail.right() - w + 1))
        y = max(avail.top(), min(avail.top() + 24, avail.bottom() - h + 1))
        self.move(x, y)

        # LLM 配置先行：环境变量为底，UI 设置文件补缺（env 显式设置者优先）
        self.llm_settings = apply_to_llm(load_from_env())
        self._delta_counts: dict[str, int] = {}
        self._t_turn = time.monotonic()  # 回合计时，_on_captured 时重置

        self.records = RecordsPane(api)
        self.log_page = LogPane()
        self.settings = SettingsPane(api, self.llm_settings)
        self.help_page = HelpPane()

        # 四页对齐左索引：搜题记录 / 日志 / 设置 / 帮助
        # （原「科目管理」页已并入搜题记录页侧栏 —— 用户 2026-10-02 拍板）
        self.addSubInterface(self.records, FluentIcon.CHAT, "搜题记录")
        self.addSubInterface(self.log_page, FluentIcon.HISTORY, "日志")
        self.addSubInterface(self.settings, FluentIcon.SETTING, "设置")
        self.addSubInterface(self.help_page, FluentIcon.HELP, "帮助")
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
        self.records.followupRequested.connect(self._records_followup)
        self.records.cancelRequested.connect(self.engine.cancel)
        self.records.verifyRequested.connect(self._records_verify)

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

        # ---- 左下角昵称头像（2026-10-03 反馈）：点出扫码配对二维码，
        # 取代设置页的二维码 + 手输 token（纯二维码，手输废弃） ----
        self.avatar_btn = QPushButton("?", self)
        self.avatar_btn.setFixedSize(40, 40)
        self.avatar_btn.setCursor(Qt.PointingHandCursor)
        self.avatar_btn.setToolTip("手机扫码配对")
        self.avatar_btn.setStyleSheet(
            "QPushButton{background:#ec4899; color:#ffffff; border:none;"
            " border-radius:20px; font-size:16px; font-weight:650;}"
            "QPushButton:hover{background:#db2777;}")
        self.avatar_btn.clicked.connect(self._toggle_qr_popup)
        self._qr_pop: QFrame | None = None   # 点开才建（点击外部自关）
        self._qr_hide_ts = 0.0               # 外部点击刚关过 → 别秒重开
        self._me_task = _MeTask(self.api, self)
        self._me_task.ok.connect(self._on_me)
        self._me_task.start()

        if self.llm_settings.errors:
            self._llm_errors = InfoBar.warning(  # 存引用防 GC
                "作答未就绪", "；".join(self.llm_settings.errors),
                parent=self, duration=8000, position=InfoBarPosition.TOP)

    # ---------- 页签懒加载 ----------
    def _on_tab_changed(self, idx):
        widget = self.stackedWidget.widget(idx)
        if widget is self.records:
            # 记录页每次切入都拉一次（内部有在途防抖）——2026-10-03 反馈
            # 「有时点进去狂点刷新都不显示」，不再只在首次进入加载
            self.records.load_categories()
            self.records.reload()
            return
        key = getattr(widget, "objectName", lambda: "")() or str(id(widget))
        if key in self._booted:
            return
        self._booted.add(key)
        if widget is self.log_page:
            self.log_page.refresh()
        elif widget is self.settings:
            self.settings.refresh()

    # ---------- 左下角头像 → 扫码配对（非模态弹窗，2026-10-03 反馈） ----------
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # super().__init__/布局阶段也会进这里，头像可能还没建
        btn = getattr(self, "avatar_btn", None)
        if btn is None:
            return
        # 头像恒贴窗口左下角（用户点名位置；窗口调大后也不跑偏）
        btn.move(6, self.height() - btn.height() - 6)

    def _on_me(self, me: dict):
        nick = str(me.get("nickname") or me.get("username") or "")
        self.avatar_btn.setText(initial_of(nick))
        if nick:
            self.avatar_btn.setToolTip(f"{nick} · 手机扫码配对")

    def eventFilter(self, obj, ev):
        # super().__init__ 期间 Qt 就会把事件送进来（qframeless 过滤器链），
        # 那时 _qr_pop 还没建——漏了这个守卫整个 FluentWindow 构造直接崩
        # （2026-10-03「客户端都跑不起来」根因）
        if obj is getattr(self, "_qr_pop", None) and ev.type() == QEvent.Hide:
            self._qr_hide_ts = time.monotonic()   # 外部点击把它收掉了
        return super().eventFilter(obj, ev)

    def _toggle_qr_popup(self):
        if self._qr_pop is not None and self._qr_pop.isVisible():
            self._qr_pop.hide()
            return
        if time.monotonic() - self._qr_hide_ts < 0.4:
            # 刚被「点外部」收掉：同一轮点击的后半程落在头像上，
            # 这里再开会变成永远关不上（2026-10-03 反馈：要点击显示再点击关闭）
            return
        self._show_qr_popup()

    def _show_qr_popup(self):
        pop = self._qr_pop
        if pop is None:
            # 非模态、点外部自关。半透明**外窗**只当透明画布——顶层 QSS 背景
            # 在 translucent 下不画（2026-10-03 反馈：整窗透了、圆角也没了），
            # 白底+圆角+描边都画在**内层卡片**上
            pop = QFrame(self, Qt.Popup | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
            pop.setAttribute(Qt.WA_TranslucentBackground, True)
            pop.installEventFilter(self)
            card = QFrame(pop)
            card.setObjectName("qrCard")
            card.setStyleSheet(
                "#qrCard{background:#ffffff; border:1px solid #e6e8f2;"
                " border-radius:14px;}")
            outer = QVBoxLayout(pop)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(card)
            box = QVBoxLayout(card)
            box.setContentsMargins(14, 12, 14, 12)
            box.setSpacing(8)
            self._qr_img = QLabel("取 token…")
            self._qr_img.setFixedSize(180, 180)
            self._qr_img.setAlignment(Qt.AlignCenter)
            self._qr_img.setStyleSheet(
                "border:1px solid #e6e8f2; border-radius:8px;"
                " background:#ffffff; color:#7c819c; font-size:13px;")
            box.addWidget(self._qr_img)
            tip = CaptionLabel("手机扫码配对 · 10 分钟内扫")
            tip.setStyleSheet("color:#7c819c;")
            box.addWidget(tip)
            self._qr_pop = pop
        pop.adjustSize()
        top = self.avatar_btn.mapToGlobal(QPoint(0, 0))  # 弹在按钮上方
        pop.move(top.x() - 8, top.y() - pop.height() - 8)
        pop.show()
        self._qr_img.setText("取 token…")
        self._qr_lan = LanTask(self.api, self)  # 每次点开取新鲜 token
        self._qr_lan.ok.connect(self._on_qr_token)
        self._qr_lan.failed.connect(
            lambda m: self._qr_img.setText(f"失败：{m}"))
        self._qr_lan.start()

    def _on_qr_token(self, token: str):
        if self._qr_pop is None or not self._qr_pop.isVisible():
            return  # 等 token 期间被收掉了就别再刷
        try:
            self._qr_img.setPixmap(
                payload_image(build_payload(self.api.base, token)))
        except ImportError:
            self._qr_img.setText("缺 qrcode 库")

    # ---------- 热键 ----------
    def _toggle_answer_window(self):
        # 只显隐浮窗；截屏走 captureRequested，两者绝不能串线（显隐带渐变）
        aw = self.answer_window
        if aw.isVisible():
            aw.hide_fade()
            LOG.info("alt+z → panel fading out")
        else:
            aw.show_fade()
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

    def _records_followup(self, art_id: str, text: str):
        """记录页「接着问」：收编该会话给引擎，回答直播在记录页右栏——不开浮窗
        （2026-10-03 用户点名）。落库走 PUT 更新原会话（backend_id，§8-2 同链）；
        引擎正忙时拒发且**不清输入框**，文字留住等下一次。"""
        if self.engine.is_busy():
            self._notify("warning", "稍等", "当前回合还没结束", 2500)
            return
        row = next((r for r in self.records.rows
                    if str(r.get("id")) == art_id), None)
        if row is None:
            return
        sess = session_from_article(row, msgs_of(row))
        if not (self.engine.load_session(sess)
                and self.engine.send_followup(text)):
            self._notify("warning", "稍等", "当前回合还没结束", 2500)
            return
        self.records.follow_turn(sess)
        self.records.followup_input.clear()

    def _records_verify(self, art_id: str):
        """记录页「核实一下」锚点：收编该会话 → 手动跑阶段B，结果直播右栏。"""
        if self.engine.is_busy():
            self._notify("warning", "稍等", "当前回合还没结束", 2500)
            return
        row = next((r for r in self.records.rows
                    if str(r.get("id")) == art_id), None)
        if row is None:
            return
        if str(self.engine.session.backend_id) != art_id:
            sess = session_from_article(row, msgs_of(row))
            if not self.engine.load_session(sess):
                self._notify("warning", "稍等", "当前回合还没结束", 2500)
                return
        if not self.engine.verify_only():
            self._notify("warning", "没法核实",
                         "这条会话没有可核实的回答", 2500)
            return
        self.records.follow_turn(self.engine.session)  # 核实流直播进右栏

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
        self.records.on_engine_event(self.engine.session, ev)  # 记录页直播（§ 反馈）
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
            self.records.reload()  # 记录页随后看到接续落库后的新消息/状态
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
        # PySide6 6.10：ActivationReason.DoubleTrigger 改名 DoubleClick
        #（旧名 AttributeError，托盘点击 2026-10-03 日志实锤）
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
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
