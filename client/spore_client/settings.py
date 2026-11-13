"""设置页：MV3 options.html 的卡片结构（模型与检索）。

卡片与字段样式照 options.html（白底、1px #e6e8f2、圆角 16、字段 label 11.5px
muted、hint 12.5px、输入圆角 10 底 #fafbfe focus 边 #ec4899）。Qt 样式表不支持
letter-spacing / text-transform / box-shadow：字距用字号+颜色近似，
阴影用 QGraphicsDropShadowEffect。

字段改动 → 600ms 防抖自动保存（options.js scheduleSave 同款）：写 settings_store
之余同时改内存里的 llm 对象——主窗与引擎持同一实例，即改即生效，无保存按钮。

红线（2026-10-03 拍板改版）：api_key 只依赖 config（LOCALAPPDATA/Spore/
ui_settings.json），环境变量废除；输入框不回显，只显示「（已设置）」，
粘贴新值回车即覆盖。
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
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
    SegmentedWidget,
    SpinBox,
    SwitchButton,
)

from . import settings_store, theme
from .answer.llm import stream_chat
from .answer.settings import LlmSettings
from .store import Store


# ---- 卡片/字段样式（options.html :44-97 同款；色号一律走 theme 调色板） ----
def card_style(c: theme.Palette) -> str:
    return theme.qss("QFrame#card { background: $surface;"
                     " border: 1px solid $line; border-radius: 16px; }", c)


def input_style(c: theme.Palette) -> str:
    return theme.qss(
        "LineEdit { border: 1px solid $line; border-radius: 10px;"
        " background: $input_bg; padding: 5px 9px; font-size: 13.5px;"
        " color: $ink; }"
        "LineEdit:focus { border: 1px solid $accent; background: $surface; }"
        "LineEdit:read-only { color: $ink_3; }", c)


def btn2_style(c: theme.Palette) -> str:
    return theme.qss(
        "QPushButton { background: $surface_3; color: $ink_3; border: none;"
        " border-radius: 10px; padding: 7px 18px; font-weight: 600;"
        " font-size: 13px; }"
        "QPushButton:hover { background: $surface_4; }"
        "QPushButton:pressed { background: $surface_press; }"
        "QPushButton:disabled { background: $surface_disabled;"
        " color: $ink_5; }", c)


def title_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 16px; font-weight: 650; color: $ink;", c)


def label_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 11.5px; color: $ink_4;"
                     " font-weight: 600;", c)


def hint_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 12.5px; color: $ink_4;", c)


def subhead_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 13.5px; font-weight: 650; color: $ink_2;", c)


def setting_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 13.5px; color: $ink_2;"
                     " font-weight: 400;", c)


def kbd_style(c: theme.Palette) -> str:
    return theme.qss(
        "QLabel { background: $surface_2; border: 1px solid $line;"
        " border-bottom: 2px solid $line; border-radius: 6px;"
        " padding: 2px 7px; color: $ink;"
        " font-family: 'Cascadia Code', Consolas, monospace;"
        " font-size: 12px; }", c)


def divider_style(c: theme.Palette) -> str:
    return theme.qss("background: $line;", c)


def msg_style(c: theme.Palette, kind: bool | None) -> str:
    """测试连接回显：True 成功 / False 失败 / None 中性（探测中）。"""
    if kind is True:
        color = c.success
    elif kind is False:
        color = c.danger
    else:
        color = c.ink_4
    return theme.qss("font-size: 12.5px; color: $color;", c, color=color)


def danger_hint_style(c: theme.Palette) -> str:
    return theme.qss("font-size: 12.5px; color: $danger;", c)


def build_card(title: str, hint: str | None = None,
               trailing: QWidget | None = None):
    """白底圆角卡 → (card, layout, title_label)；trailing = 卡头右侧控件。"""
    card = QFrame()
    card.setObjectName("card")
    theme.style(card, card_style)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(22, 20, 22, 20)
    lay.setSpacing(10)
    t = QLabel(title)
    theme.style(t, title_style)
    h = None
    if hint:
        h = QLabel(hint)
        h.setWordWrap(True)
        theme.style(h, hint_style)
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
    shadow.setColor(QColor(*theme.current().shadow))
    card.setGraphicsEffect(shadow)
    theme.hook(card, lambda: shadow.setColor(QColor(*theme.current().shadow)))
    return card, lay, t


def field_label(text: str) -> QLabel:
    """字段 label：11.5px muted（options.html label 同款）。"""
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.style(lab, label_style)
    return lab


def hint_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.style(lab, hint_style)
    return lab


def setting_label(text: str) -> QLabel:
    """开关行左侧标题（2026-10-03 反馈：灰色小字不对，用正常正文字号字色）。"""
    lab = QLabel(text)
    lab.setWordWrap(True)
    theme.style(lab, setting_style)
    return lab


def kbd_badge(text: str) -> QLabel:
    """kbd 徽标：底 surface-2、1px 边框、底边 2px、圆角 6、等宽 12px。"""
    lab = QLabel(text)
    theme.style(lab, kbd_style)
    return lab


def _divider() -> QFrame:
    line = QFrame()
    line.setFixedHeight(1)
    theme.style(line, divider_style)
    return line


def _sub_head(text: str) -> QLabel:
    lab = QLabel(text)
    theme.style(lab, subhead_style)
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
    def __init__(self, store: Store, llm: LlmSettings, parent=None):
        super().__init__(parent)
        self.setObjectName("settingsPage")  # FluentWindow.addSubInterface 要求非空
        self.store = store
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

        # ================= 卡一：外观（即时生效，不用保存） =================
        # 档位与移动端设置页同口径（system|light|dark），落 ui_settings.theme
        card, lay, _ = build_card(
            "外观", "浅色 = 孢子粉，深色 = Fungi 青；点一下立即换，所有页面同步")
        self.theme_seg = SegmentedWidget()
        self.theme_seg.setObjectName("themeSeg")
        for key, text in (("system", "跟随系统"), ("light", "浅色"),
                          ("dark", "深色")):
            self.theme_seg.addItem(key, text)
        self.theme_seg.setCurrentItem(theme.mode())
        self.theme_seg.setFixedWidth(330)      # 移动端是紧凑药丸，别拉满整卡
        self.theme_seg.currentItemChanged.connect(self._theme_picked)
        lay.addWidget(self.theme_seg, 0, Qt.AlignLeft)
        # 档位也可能被别处改（系统跟随时解析值变化）——分段控件别停在旧档
        theme.hook(self, self._sync_theme_seg)
        stack.addWidget(card)

        # ================= 卡二：模型 =================
        card, lay, title = build_card("模型")
        self.cards["model"] = title

        lay.addWidget(field_label("模型 endpoint（OpenAI 兼容）"))
        self.endpoint_edit = LineEdit()
        self.endpoint_edit.setObjectName("endpointEdit")
        theme.style(self.endpoint_edit, input_style)
        self.endpoint_edit.textChanged.connect(
            lambda t: self._model_changed("endpoint", t.strip()))
        lay.addWidget(self.endpoint_edit)

        lay.addWidget(field_label("API Key"))
        # 输入框永不回显旧值：只在敲入期间持有新值，回车即覆盖保存；
        # 状态句子直接做占位符（2026-10-03 反馈：别在框下面再挂一行字）
        self.key_edit = LineEdit()
        self.key_edit.setObjectName("keyEdit")
        self.key_edit.setEchoMode(QLineEdit.Password)
        theme.style(self.key_edit, input_style)
        self.key_edit.returnPressed.connect(self._save_key)
        lay.addWidget(self.key_edit)

        lay.addWidget(field_label("模型名"))
        self.model_edit = LineEdit()
        self.model_edit.setObjectName("modelEdit")
        theme.style(self.model_edit, input_style)
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
        theme.style(self.proxy_edit, input_style)
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
        theme.style(self.probe_msg, msg_style, None)
        row.addWidget(self.probe_btn)
        row.addWidget(self.probe_msg, 1)
        lay.addLayout(row)

        # 启动期错误提示（当前只有「API key 未设置」）：存引用——key 存进来后要能当场撤下，
        # 否则红字留到重启（2026-10-03 用户实测：设完底部依然显示）
        self._err_hint = None
        if self.llm.errors:
            err = hint_label("；".join(self.llm.errors))
            theme.style(err, danger_hint_style)
            lay.addWidget(err)
            self._err_hint = err
        stack.addWidget(card)
        stack.addStretch(1)

        # 操作状态（自动保存提示）—— 放滚动区外，始终可见
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
        self._flash_status("已自动保存")

    def _save_key(self):
        """粘贴新 key 回车 → 覆盖保存（永不回显；空输入只刷新状态行）。"""
        val = self.key_edit.text().strip()
        if val:
            self.llm.api_key = val        # 即改即生效（主窗/引擎持同一实例）
            self._clear_key_error()
            self.key_edit.clear()
            self._sync_key_ui()
            self._sync_probe_btn()
            self._touch()
        self._flash_status("已自动保存")

    def _clear_key_error(self):
        """key 到位 → 启动期灌进 errors 的「API key 未设置」当场撤（错误列表与页面
        红字一起清）。只撤 key 这条；别的启动错误该留留。"""
        if not self.llm.api_key:
            return
        self.llm.errors = [e for e in self.llm.errors if "API key" not in e]
        if self._err_hint is not None:
            self._err_hint.hide()
            self._err_hint = None

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
        self._flash_status("已自动保存")

    def _flash_status(self, text: str):
        """底部一行状态：2.2s 后自动清（期间被别的文案顶掉就不动它）。"""
        self.status.setText(text)
        QTimer.singleShot(2200, lambda: (self.status.text() == text
                                         and self.status.setText("")))

    # ---------- 外观（即时生效，不用保存按钮） ----------
    def _sync_theme_seg(self):
        key = theme.mode()
        if self.theme_seg.currentRouteKey() != key:
            self.theme_seg.blockSignals(True)   # 回填不许触发 currentItemChanged
            self.theme_seg.setCurrentItem(key)
            self.theme_seg.blockSignals(False)

    def _theme_picked(self, key: str):
        """设置页分段点一下：落盘 + 全应用换肤（同移动端 themeSet 桥）。"""
        resolved = theme.set_mode(key)
        self._flash_status("外观已切换：" + ("深色" if resolved == "dark"
                                            else "浅色"))

    # ---------- 测试连接 ----------
    def _sync_probe_btn(self):
        # endpoint / api_key / model 三者非空才可点（options.js:77 同款）
        self.probe_btn.setEnabled(
            bool(self.llm.endpoint and self.llm.api_key and self.llm.model))

    def _set_probe_msg(self, text: str, ok: bool | None = None):
        theme.style(self.probe_msg, msg_style, ok)
        self.probe_msg.setText(text)

    def _probe(self):
        if self._probe_task is not None and self._probe_task.isRunning():
            return                       # 上一发还在飞，忽略连点
        if not (self.llm.endpoint and self.llm.api_key and self.llm.model):
            self._set_probe_msg("endpoint / key / model 都要填", False)
            return
        self._set_probe_msg("探测中…")
        self._probe_task = _ProbeTask(self.llm.endpoint, self.llm.api_key,
                                 self.llm.model, self)
        self._probe_task.done.connect(self._set_probe_msg)
        self._probe_task.start()
