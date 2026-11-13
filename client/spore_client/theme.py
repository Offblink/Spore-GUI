"""明暗主题：Fungi 双板（与 Spore-Mobile 同一套令牌）+ 跟随系统。

- 档位单一事实源：`%LOCALAPPDATA%\\Spore\\ui_settings.json` 的 `theme`
  （`system|light|dark`，与移动端 `SporeSettings.theme` 同名同值）。
- 浅色沿用桌面既定观感（白卡 + `#f7f8fc` 页底 + 孢子粉 `#EC4899`）；
  深色取 Fungi dark（底 `#12141C`、面 `#1B1E29`、主色青 `#2DD4BF`）。
  令牌名对齐移动端 `web/spore.css`，三端同源，别在这里自创色号。
- 控件样式不再「setStyleSheet 一次就完事」：`style(widget, builder, …)` 把
  builder 挂成控件的 Qt 子对象，换主题时统一重跑；控件销毁绑定自动消失。
- 样式表管不到的地方（富文本 HTML、QPainter 自绘、投影色）用
  `hook(widget, fn)` 挂回调，同样随控件销毁注销。
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from string import Template

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from shiboken6 import isValid

from . import settings_store

MODES = ("system", "light", "dark")
KEY = "theme"


def _mix(fg: str, alpha: float, bg: str) -> str:
    """不透明混色 → hex（Qt 样式表对 rgba() 支持有限，tint 一律预混）。"""
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(
        f"{round(bv + (fv - bv) * alpha):02X}"
        for fv, bv in zip(f, b, strict=True))


@dataclass(frozen=True)
class Palette:
    """一套主题的取色表；字段名 = 移动端令牌名（去掉 `--` 与连字符）。"""

    dark: bool
    bg: str              # 页面底
    surface: str         # 卡片 / 白面
    surface_2: str       # 次级面：气泡、行 hover
    surface_3: str       # 三级面：chip、软按钮底
    surface_4: str       # 软按钮 hover
    surface_press: str   # 软按钮按下
    surface_disabled: str
    input_bg: str
    ink: str             # 主文字
    ink_2: str           # 标题次级
    ink_3: str           # 正文淡
    ink_4: str           # 说明文字
    ink_5: str           # 最淡：占位、图标、小节标
    ink_6: str           # 未激活图标（未收藏星 / 禁用）
    line: str
    line_strong: str
    accent: str
    accent_strong: str
    accent_deep: str
    accent_soft: str     # 选中行底
    accent_soft_2: str   # 悬停更浓
    accent_tint: str     # 按钮 hover 底
    on_accent: str
    success: str
    success_bg: str
    danger: str
    danger_strong: str
    danger_bg: str
    danger_solid: str    # 危险实心按钮
    danger_solid_hover: str
    warn_bg: str
    info_bg: str         # 状态药丸（紫）
    info_fg: str
    overlay_border: str  # 浮窗描边（与桌面截图要能区分）
    marker: str          # 科目行的纸夹图标
    shadow: tuple[int, int, int, int]


LIGHT = Palette(
    dark=False,
    bg="#f7f8fc",
    surface="#ffffff",
    surface_2="#f2f4fb",
    surface_3="#f1f3fb",
    surface_4="#e8ebf7",
    surface_press="#dde1f2",
    surface_disabled="#f4f5fa",
    input_bg="#fafbfe",
    ink="#1a1d2e",
    ink_2="#2b2f4a",
    ink_3="#4a4f6b",
    ink_4="#7c819c",
    ink_5="#a3a8c2",
    ink_6="#b3b8cd",
    line="#e6e8f2",
    line_strong="#d9dcec",
    accent="#ec4899",
    accent_strong="#db2777",
    accent_deep="#c2185b",
    accent_soft="#ffeef7",
    accent_soft_2="#ffe4f1",
    accent_tint="#fff0f7",
    on_accent="#ffffff",
    success="#0f9d58",
    success_bg="#e7f8ef",
    danger="#d02747",
    danger_strong="#c81e45",
    danger_bg="#ffeef1",
    danger_solid="#ff3b5c",
    danger_solid_hover="#ef1f45",
    warn_bg="#fff9ea",
    info_bg="#f4ecff",
    info_fg="#7c4dbe",
    overlay_border="#b0b5cb",
    marker="#f9b6d5",
    shadow=(20, 24, 48, 13),
)

# 深色 tint 一律由面底预混（移动端是 rgba，Qt 样式表吃不了 → 补成实色）
_DARK_SURFACE = "#1B1E29"
DARK = Palette(
    dark=True,
    bg="#12141C",
    surface=_DARK_SURFACE,
    surface_2="#22252F",
    surface_3="#272B38",
    surface_4="#2F3444",
    surface_press="#363C4E",
    surface_disabled="#23262F",
    input_bg="#20242F",
    ink="#E6E8F2",
    ink_2="#D3D7E6",
    ink_3="#A6ACC4",
    ink_4="#8B92AE",
    ink_5="#7B82A0",
    ink_6="#5C6382",
    line="#2A2E3E",
    line_strong="#363B4E",
    accent="#2DD4BF",
    accent_strong="#4BE0CD",
    accent_deep="#99F6E4",
    accent_soft=_mix("#2DD4BF", 0.12, _DARK_SURFACE),
    accent_soft_2=_mix("#2DD4BF", 0.22, _DARK_SURFACE),
    accent_tint=_mix("#2DD4BF", 0.10, _DARK_SURFACE),
    on_accent="#08131A",
    success="#4ADE80",
    success_bg=_mix("#4ADE80", 0.10, _DARK_SURFACE),
    danger="#F87171",
    danger_strong="#FCA5A5",
    danger_bg=_mix("#F87171", 0.10, _DARK_SURFACE),
    danger_solid="#F87171",
    danger_solid_hover="#FCA5A5",
    warn_bg=_mix("#FBBF24", 0.10, _DARK_SURFACE),
    info_bg=_mix("#A78BFA", 0.16, _DARK_SURFACE),
    info_fg="#C4B5FD",
    overlay_border="#3A4056",
    marker=_mix("#2DD4BF", 0.55, _DARK_SURFACE),
    shadow=(0, 0, 0, 150),
)

_current: Palette = LIGHT     # 未 apply 前（import 阶段 / 部分测试）恒为浅色


class _Observer(QObject):
    """挂在控件上的观察者（Qt 子对象：控件删了它一起没，不用手工注销）。"""

    def __init__(self, widget: QObject, fn: Callable[[], None] | None = None,
                 builder: Callable[..., str] | None = None):
        super().__init__(widget)
        self.fn = fn
        self.builder = builder
        self.args: tuple = ()

    def apply(self) -> None:
        try:
            if self.builder is not None:
                widget = self.parent()
                if widget is not None:
                    widget.setStyleSheet(self.builder(_current, *self.args))
            if self.fn is not None:
                self.fn()
        except RuntimeError:      # 控件已进 deleteLater 队列
            pass


_OBSERVERS: set[weakref.ref] = set()   # 弱引用集合：控件删掉即自动移出


def style(widget, builder: Callable[..., str], *args) -> None:
    """给控件挂样式并立刻生效；换主题时按 ``builder(_current, *args)`` 重算。

    builder 必须是**模块级函数**（别闭包捕获控件或其它会过期的状态），
    动态状态（勾选、收藏、启用态）随参数传进来。
    """
    binding = getattr(widget, "_spore_style", None)
    if binding is None:
        binding = _Observer(widget, builder=builder)
        widget._spore_style = binding       # noqa: SLF001 — 绑定随控件活
        _OBSERVERS.add(weakref.ref(binding))
    binding.builder, binding.args = builder, args
    binding.apply()


def hook(widget, fn: Callable[[], None]) -> None:
    """样式表管不到的重绘（富文本 HTML、QPainter 色、投影色）挂在这里。"""
    obs = _Observer(widget, fn=fn)
    _OBSERVERS.add(weakref.ref(obs))


def mode() -> str:
    """当前档位：system / light / dark（文件缺失或值非法 → system）。"""
    value = settings_store.read().get(KEY)
    return value if value in MODES else "system"


def resolved() -> str:
    """档位解析成实际明暗：system 看系统色彩方案（Qt 6.5+ styleHints）。"""
    m = mode()
    if m != "system":
        return m
    hints = QGuiApplication.styleHints()
    scheme = hints.colorScheme() if hints is not None else None
    return "dark" if scheme == Qt.ColorScheme.Dark else "light"


def current() -> Palette:
    return _current


def qss(tpl: str, c: Palette, **extra: str) -> str:
    """QSS 模板填色：`$accent` → 调色板字段（花括号留给 QSS 自己，不用转义）。

    例：``qss("QLabel{color:$ink_4;}", c)``；动态色用 ``**extra`` 传。
    """
    return Template(tpl).substitute({**vars(c), **extra})


def apply() -> None:
    """按档位落地：qfluentwidgets 主题 + 自带调色板 + 全部绑定重跑。"""
    global _current
    dark = resolved() == "dark"
    pal = DARK if dark else LIGHT
    from qfluentwidgets import Theme, setTheme, setThemeColor
    setTheme(Theme.DARK if dark else Theme.LIGHT)
    setThemeColor(pal.accent)
    _current = pal
    for ref in list(_OBSERVERS):
        obs = ref()
        if obs is not None and isValid(obs):
            obs.apply()


def set_mode(m: str) -> str:
    """切档位（即时生效）：落盘 + 应用，返回解析后的 light|dark。"""
    m = m if m in MODES else "system"
    data = settings_store.read()
    data[KEY] = m
    settings_store.write(data)
    apply()
    return resolved()


def follow_system() -> None:
    """系统色彩方案变化 → 档位是 system 时重新落地（监听只装一次）。"""
    hints = QGuiApplication.styleHints()
    if hints is None or getattr(hints, "_spore_hooked", False):
        return
    hints._spore_hooked = True      # noqa: SLF001 — 防重复连接（每个进程一次）
    hints.colorSchemeChanged.connect(_on_system_scheme)


def _on_system_scheme(_scheme=None) -> None:
    if mode() == "system":
        apply()


def is_dark() -> bool:
    return _current.dark


__all__ = [
    "DARK", "LIGHT", "MODES", "Palette", "apply", "current", "follow_system",
    "hook", "is_dark", "mode", "qss", "resolved", "set_mode", "style",
]
