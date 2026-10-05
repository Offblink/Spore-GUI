"""设置页：MV3 options.html 的卡片结构（模型 / 快捷键 / 题库目录）。

扫码配对已迁出（2026-10-03）：设置页不再有二维码/手输 token，改为主窗
左下角昵称头像点出二维码（见 pairing.py 与 main_window._qr_popup）。

卡片与字段样式照 options.html（白底、1px #e6e8f2、圆角 16、字段 label 11.5px
muted、hint 12.5px、输入圆角 10 底 #fafbfe focus 边 #ec4899）。Qt 样式表不支持
letter-spacing / text-transform / box-shadow：字距用字号+颜色近似，
阴影用 QGraphicsDropShadowEffect。

字段改动 → 600ms 防抖自动保存（options.js scheduleSave 同款）：写 settings_store
之余同时改内存里的 llm 对象——主窗与引擎持同一实例，即改即生效，无保存按钮。

红线（2026-10-03 拍板改版）：api_key 只依赖 config（LOCALAPPDATA/Spore/
ui_settings.json），环境变量废除；输入框不回显，只显示「（已设置）」，
粘贴新值回车即覆盖。
简报 §1：半圆小角（hideToggle）不移植，快捷键卡只有两个 kbd 徽标。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    LineEdit,
    PushButton,
    SpinBox,
    SwitchButton,
)

from . import settings_store
from .answer.llm import stream_chat
from .answer.settings import LlmSettings
from .api import ApiClient, ApiError, NetworkError

# ---- 卡片/字段样式（options.html :44-97 同款） ----
CARD_STYLE = (
    "QFrame#card { background: #fff; border: 1px solid #e6e8f2;"
    " border-radius: 16px; }"
)
INPUT_STYLE = (
    "LineEdit { border: 1px solid #e6e8f2; border-radius: 10px;"
    " background: #fafbfe; padding: 5px 9px; font-size: 13.5px; color: #1a1d2e; }"
    "LineEdit:focus { border: 1px solid #ec4899; background: #fff; }"
    "LineEdit:read-only { color: #4a4f6b; }"
)
BTN2_STYLE = (
    "QPushButton { background: #f1f3fb; color: #4a4f6b; border: none;"
    " border-radius: 10px; padding: 7px 18px; font-weight: 600; font-size: 13px; }"
    "QPushButton:hover { background: #e8ebf7; }"
    "QPushButton:pressed { background: #dde1f2; }"
    "QPushButton:disabled { background: #f4f5fa; color: #a3a8c2; }"
)
TITLE_STYLE = "font-size: 16px; font-weight: 650; color: #1a1d2e;"
LABEL_STYLE = "font-size: 11.5px; color: #7c819c; font-weight: 600;"
HINT_STYLE = "font-size: 12.5px; color: #7c819c;"
SUBHEAD_STYLE = "font-size: 13.5px; font-weight: 650; color: #2b2f4a;"


def build_card(title: str, hint: str | None = None,
               trailing: QWidget | None = None):
    """白底圆角卡 → (card, layout, title_label)；trailing = 卡头右侧控件。"""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(CARD_STYLE)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(22, 20, 22, 20)
    lay.setSpacing(10)
    t = QLabel(title)
    t.setStyleSheet(TITLE_STYLE)
    h = None
    if hint:
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setStyleSheet(HINT_STYLE)
    if trailing is None:
        lay.addWidget(t)
        if h is not None:
            lay.addWidget(h)
    else:
        head = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(3)
        col.addWidget(t)
        if h is not None:
            col.addWidget(h)
        head.addLayout(col, 1)
        head.addWidget(trailing, 0, Qt.AlignTop | Qt.AlignRight)
        lay.addLayout(head)
    # Qt 样式表无 box-shadow → 用图形效果近似（options.html 卡片阴影同参数）
    shadow = QGraphicsDropShadowEffect(card)
    shadow.setBlurRadius(52)
    shadow.setOffset(0, 8)
    shadow.setColor(QColor(20, 24, 48, 13))
    card.setGraphicsEffect(shadow)
    return card, lay, t


def field_label(text: str) -> QLabel:
    """字段 label：11.5px muted（options.html label 同款）。"""
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(LABEL_STYLE)
    return lab


def hint_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(HINT_STYLE)
    return lab


def setting_label(text: str) -> QLabel:
    """开关行左侧标题（2026-10-03 反馈：灰色小字不对，用正常正文字号字色）。"""
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("font-size: 13.5px; color: #2b2f4a; font-weight: 400;")
    return lab


def kbd_badge(text: str) -> QLabel:
    """kbd 徽标：底 #f4f6fd、1px 边框、底边 2px、圆角 6、等宽 12px。"""
    lab = QLabel(text)
    lab.setStyleSheet(
        "QLabel { background: #f4f6fd; border: 1px solid #e6e8f2;"
        " border-bottom: 2px solid #e6e8f2; border-radius: 6px;"
        " padding: 2px 7px; color: #1a1d2e;"
        " font-family: 'Cascadia Code', Consolas, monospace; font-size: 12px; }")
    return lab


def _divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background: #e6e8f2;")
    return line


def _sub_head(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setStyleSheet(SUBHEAD_STYLE)
    return lab


def _b(v, default: bool) -> bool:
    return v if isinstance(v, bool) else default


class _NoWheelSpinBox(SpinBox):
    """滚轮不改数值（2026-10-03 反馈：点过输入框后焦点还在，滚动页面
    时数字被顺手改掉）——事件 ignore 冒泡给滚动区，页面照滚。"""

    def wheelEvent(self, ev):
        ev.ignore()


class _ProbeTask(QThread):
    """测试连接：QThread 里打一次真端点，回显首字耗时（options.js probe 同款文案）。"""

    done = Signal(str, bool)  # (消息, 是否成功)

    def __init__(self, endpoint: str, api_key: str, model: str, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model

    def run(self):
        t0 = time.monotonic()
        first: dict[str, float] = {}

        def on_delta(kind: str, chunk: str, acc: dict):
            if chunk and "t0" not in first:
                first["t0"] = time.monotonic()

        try:
            res = stream_chat(
                endpoint=self.endpoint, api_key=self.api_key, model=self.model,
                max_tokens=8,
                messages=[{"role": "user", "content": "只回一个字：通"}],
                on_delta=on_delta)
            if "t0" in first:
                self.done.emit(f"通了，首字 {first['t0'] - t0:.2f}s", True)
            elif str(res.get("content") or "").strip():
                self.done.emit(f"通了，首字 {time.monotonic() - t0:.2f}s", True)
            else:
                self.done.emit("连上了但没有流式响应", False)
        except Exception as e:  # noqa: BLE001 —— 超时/异常一律收敛到 label，不弹栈
            self.done.emit(f"失败：{e}", False)


class SettingsPane(QWidget):
    def __init__(self, api: ApiClient, llm: LlmSettings, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")  # FluentWindow.addSubInterface 要求非空
        self.api = api
        self.llm = llm
        self._ready = False                # 回填门闩：回填期间的事件不许触发保存
        self._probe_task: _ProbeTask | None = None

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)  # options.js 防抖同款
        self._save_timer.timeout.connect(self._save)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet("QWidget { background: transparent; }")
        stack = QVBoxLayout(body)
        stack.setContentsMargins(0, 0, 6, 0)
        stack.setSpacing(16)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.cards: dict[str, QLabel] = {}

        # ================= 卡一：模型 =================
        card, lay, title = build_card("模型")
        self.cards["model"] = title

        lay.addWidget(field_label("模型 endpoint（OpenAI 兼容）"))
        self.endpoint_edit = LineEdit()
        self.endpoint_edit.setObjectName("endpointEdit")
        self.endpoint_edit.setStyleSheet(INPUT_STYLE)
        self.endpoint_edit.textChanged.connect(
            lambda t: self._model_changed("endpoint", t.strip()))
        lay.addWidget(self.endpoint_edit)

        lay.addWidget(field_label("API Key"))
        # 输入框永不回显旧值：只在敲入期间持有新值，回车即覆盖保存；
        # 状态句子直接做占位符（2026-10-03 反馈：别在框下面再挂一行字）
        self.key_edit = LineEdit()
        self.key_edit.setObjectName("keyEdit")
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setStyleSheet(INPUT_STYLE)
        self.key_edit.returnPressed.connect(self._save_key)
        lay.addWidget(self.key_edit)

        lay.addWidget(field_label("模型名"))
        self.model_edit = LineEdit()
        self.model_edit.setObjectName("modelEdit")
        self.model_edit.setStyleSheet(INPUT_STYLE)
        self.model_edit.textChanged.connect(
            lambda t: self._model_changed("model", t.strip()))
        lay.addWidget(self.model_edit)

        lay.addWidget(field_label(
            "检索轮数上限（自动核实阶段用；0 = 不自动核实，追问仍可查 1 轮）"))
        self.rounds_spin = _NoWheelSpinBox()
        self.rounds_spin.setObjectName("roundsSpin")
        self.rounds_spin.setRange(0, 10)          # MV3 options.js:43
        self.rounds_spin.valueChanged.connect(
            lambda v: self._model_changed("max_tool_rounds", v))
        lay.addWidget(self.rounds_spin)

        lay.addWidget(field_label("检索代理（可选）"))
        self.proxy_edit = LineEdit()
        self.proxy_edit.setObjectName("proxyEdit")
        self.proxy_edit.setStyleSheet(INPUT_STYLE)
        self.proxy_edit.setPlaceholderText("如 127.0.0.1:7897")
        self.proxy_edit.textChanged.connect(
            lambda t: self._model_changed("proxy", t.strip()))
        lay.addWidget(self.proxy_edit)
        lay.addWidget(hint_label(
            "填了 → 引擎链 DDG→BING→BRAVE；留空 → 只走 BING"))

        self.auto_switch = SwitchButton()
        self.auto_switch.setObjectName("autoVerifySwitch")
        self.auto_switch.checkedChanged.connect(
            lambda on: self._model_changed("auto_verify", on))
        row = QHBoxLayout()
        row.addWidget(setting_label(
            "自动核实（答完自动联网核实；关掉后回答里出现「核实一下」按钮，点它才核实）"), 1)
        row.addWidget(self.auto_switch)
        lay.addLayout(row)

        self.fast_switch = SwitchButton()
        self.fast_switch.setObjectName("fastNoThinkSwitch")
        self.fast_switch.checkedChanged.connect(
            lambda on: self._model_changed("fast_no_think", on))
        row = QHBoxLayout()
        row.addWidget(setting_label("初答直接作答、不写推理（更快）"), 1)
        row.addWidget(self.fast_switch)
        lay.addLayout(row)

        # 回答面板出生位（2026-10-05 用户点名）：默认开 = 记住上次位置，
        # 下次还在那儿 born；关掉 = 回到旧行为（出现在截选/鼠标附近）。
        # 不进 LlmSettings：面板每次 new_turn 直接读 settings_store。
        self.panel_switch = SwitchButton()
        self.panel_switch.setObjectName("panelFixedSwitch")
        self.panel_switch.checkedChanged.connect(self._panel_fixed_changed)
        row = QHBoxLayout()
        row.addWidget(setting_label(
            "回答面板位置固定（记住上次位置，下次还在那里出现）"), 1)
        row.addWidget(self.panel_switch)
        lay.addLayout(row)

        lay.addWidget(field_label("上下文保留条数"))
        self.history_spin = _NoWheelSpinBox()
        self.history_spin.setObjectName("historySpin")
        self.history_spin.setRange(2, 50)         # MV3 options.js:45
        self.history_spin.valueChanged.connect(
            lambda v: self._model_changed("history_limit", v))
        lay.addWidget(self.history_spin)
        lay.addWidget(hint_label(
            "发给模型的最近消息条数（对话上下文，不是会话数量）；"
            "会话列表本身全部显示、可滚动"))

        row = QHBoxLayout()
        self.probe_btn = PushButton("测试连接")
        self.probe_btn.setObjectName("probeBtn")
        self.probe_btn.clicked.connect(self._probe)
        self.probe_msg = QLabel("")
        self.probe_msg.setObjectName("probeMsg")
        self.probe_msg.setWordWrap(True)
        self.probe_msg.setStyleSheet(HINT_STYLE)
        row.addWidget(self.probe_btn)
        row.addWidget(self.probe_msg, 1)
        lay.addLayout(row)

        if self.llm.errors:
            err = hint_label("；".join(self.llm.errors))
            err.setStyleSheet("font-size: 12.5px; color: #d02747;")
            lay.addWidget(err)
        stack.addWidget(card)

        # ================= 卡三：快捷键 =================
        card, lay, title = build_card("快捷键")
        self.cards["keys"] = title
        for cap, key in (("截图快捷键：", "Alt+S"), ("浮窗快捷键：", "Alt+Z")):
            row = QHBoxLayout()
            row.addWidget(CaptionLabel(cap))
            row.addWidget(kbd_badge(key))
            row.addStretch(1)
            lay.addLayout(row)
        lay.addWidget(hint_label(
            "全局热键随进程常驻；关窗收进托盘后仍可用，托盘右键退出才注销。"))
        stack.addWidget(card)

        # ================= 卡四：题库目录 =================
        card, lay, title = build_card("题库目录")
        self.cards["dir"] = title
        dir_row = QHBoxLayout()
        self.dir_edit = LineEdit()
        self.dir_edit.setObjectName("dirEdit")
        self.dir_edit.setReadOnly(True)
        self.dir_edit.setStyleSheet(INPUT_STYLE)
        self.dir_btn = PushButton("切换…")
        self.dir_btn.clicked.connect(self._switch_dir)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(self.dir_btn)
        lay.addLayout(dir_row)
        self.dir_info = CaptionLabel("")
        lay.addWidget(self.dir_info)
        stack.addWidget(card)
        stack.addStretch(1)

        # 操作状态（配对/目录/自动保存提示）—— 放滚动区外，始终可见
        self.status = CaptionLabel("")
        root.addWidget(self.status)

        # ---------- 回填（门闩关着，信号不触发保存） ----------
        self.endpoint_edit.setText(self.llm.endpoint)
        self.model_edit.setText(self.llm.model)
        self.proxy_edit.setText(self.llm.proxy)
        self.rounds_spin.setValue(int(self.llm.max_tool_rounds))
        self.history_spin.setValue(int(self.llm.history_limit))
        self.auto_switch.setChecked(bool(self.llm.auto_verify))
        self.fast_switch.setChecked(bool(self.llm.fast_no_think))
        # 默认开（键缺失 = True，用户拍板的默认值）
        self.panel_switch.setChecked(
            bool(settings_store.read().get("panelFixed", True)))
        self._sync_key_ui()

        self._ready = True
        self._sync_probe_btn()

    # ---------- 自动保存（600ms 防抖） ----------
    def _model_changed(self, field: str, value):
        setattr(self.llm, field, value)   # 即改即生效（主窗/引擎持同一实例）
        self._sync_probe_btn()
        self._touch()

    def _touch(self):
        if not self._ready:
            return
        self._save_timer.start()          # 连续敲键只落最后一次

    def _panel_fixed_changed(self, on: bool):
        """面板固定开关：不走 LlmSettings/_collect，直接白名单落盘。"""
        if not self._ready:
            return                        # 回填 setChecked 触发的那次不保存
        data = settings_store.read()
        data["panelFixed"] = bool(on)
        settings_store.write(data)
        self.status.setText("已自动保存")
        QTimer.singleShot(2200, self._clear_saved_hint)

    def _save_key(self):
        """粘贴新 key 回车 → 覆盖保存（永不回显；空输入只刷新状态行）。"""
        val = self.key_edit.text().strip()
        if val:
            self.llm.api_key = val        # 即改即生效（主窗/引擎持同一实例）
            self.key_edit.clear()
            self._sync_key_ui()
            self._sync_probe_btn()
            self._touch()
        self.status.setText("已自动保存")
        QTimer.singleShot(2200, self._clear_saved_hint)

    def _sync_key_ui(self):
        """状态句子进占位符（2026-10-03 反馈：不再单独挂一行灰字）。"""
        if self.llm.api_key:
            self.key_edit.setPlaceholderText("已设置 ✓（不回显；粘贴新值回车即覆盖）")
        else:
            self.key_edit.setPlaceholderText("未设置 ✗（粘贴 API key 后回车保存）")

    def _collect(self) -> dict:
        return {
            "endpoint": self.llm.endpoint,
            "model": self.llm.model,
            "maxToolRounds": self.llm.max_tool_rounds,
            "historyLimit": self.llm.history_limit,
            "proxy": self.llm.proxy,
            "fastNoThink": self.llm.fast_no_think,
            "autoVerify": self.llm.auto_verify,
            "apiKey": self.llm.api_key,   # 只依赖 config（2026-10-03 拍板）
        }

    def _save(self):
        data = settings_store.read()
        data.update(self._collect())
        settings_store.write(data)        # 白名单落盘（含 apiKey，2026-10-03 拍板）
        self.status.setText("已自动保存")
        QTimer.singleShot(2200, self._clear_saved_hint)

    def _clear_saved_hint(self):
        if self.status.text() == "已自动保存":
            self.status.setText("")

    # ---------- 测试连接 ----------
    def _sync_probe_btn(self):
        # endpoint / api_key / model 三者非空才可点（options.js:77 同款）
        self.probe_btn.setEnabled(
            bool(self.llm.endpoint and self.llm.api_key and self.llm.model))

    def _set_probe_msg(self, text: str, color: str):
        self.probe_msg.setStyleSheet(f"font-size: 12.5px; color: {color};")
        self.probe_msg.setText(text)

    def _probe(self):
        if self._probe_task is not None and self._probe_task.isRunning():
            return                       # 上一发还在飞，忽略连点
        if not (self.llm.endpoint and self.llm.api_key and self.llm.model):
            self._set_probe_msg("endpoint / key / model 都要填", "#d02747")
            return
        self._set_probe_msg("探测中…", "#7c819c")
        self._probe_task = _ProbeTask(self.llm.endpoint, self.llm.api_key,
                                 self.llm.model, self)
        self._probe_task.done.connect(
            lambda msg, ok: self._set_probe_msg(
                msg, "#0f9d58" if ok else "#d02747"))
        self._probe_task.start()

    # ---------- 目录 ----------
    def _switch_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择题库目录")
        if not d:
            return
        self._switch_to(d)

    def _switch_to(self, d: str):
        """切换 = 拷贝→校验→切配置→删旧（后端 StorageService 全做，客户端只发请求）。"""
        self.status.setText("切换中…（拷贝→校验→切配置→删旧）")
        try:
            info = self.api.switch_storage(d)
            data = info if isinstance(info, dict) else {}
            # 后端 StorageServiceImpl.info/switchTo 的键是 path/fileCount/bytes
            self.dir_edit.setText(str(data.get("path", d)))
            self.dir_info.setText(
                f"{data.get('fileCount', '?')} 个文件 ·"
                f" {data.get('bytes', '?')} 字节")
            self.status.setText("题库目录已切换")
        except (ApiError, NetworkError) as e:
            self.status.setText(f"切换失败：{e}")

    def refresh(self):
        """进入本页时拉一次目录现状（构造期不发网络请求）。"""
        try:
            info = self.api.storage_info()
            # 旧代码读 dir/files 两个不存在的键 → 输入框恒空、统计恒 ?（反馈）
            self.dir_edit.setText(str(info.get("path", "")))
            self.dir_info.setText(
                f"{info.get('fileCount', '?')} 个文件 ·"
                f" {info.get('bytes', '?')} 字节")
        except (ApiError, NetworkError):
            self.status.setText("读取题库目录失败（后端未启动？）")
