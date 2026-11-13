"""主题契约：档位落盘/解析、调色板双板、样式绑定与 hook 在换肤时重跑。

真窗口观感靠人眼验收（截图在提交说明里），这里钉住「换肤真的传播出去」这条
最容易静默退回的风险：per-widget setStyleSheet 之后忘记重刷 = 深色下白底白字。
"""

import pytest
from PySide6.QtWidgets import QLabel

from spore_client import settings_store, theme


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "PATH", tmp_path / "ui_settings.json")
    return settings_store


@pytest.fixture(autouse=True)
def reset_palette():
    """每个用例结束回到浅色调色板（同进程后续用例不该继承深色）。"""
    yield
    theme._current = theme.LIGHT     # noqa: SLF001 — 测试隔离


# ---------- 档位 ----------

def test_default_mode_is_system(store):
    assert theme.mode() == "system"
    assert theme.resolved() in ("light", "dark")


def test_set_mode_persists_and_resolves(store):
    assert theme.set_mode("dark") == "dark"
    assert store.read()["theme"] == "dark"
    assert theme.mode() == "dark"
    assert theme.current().dark is True
    assert theme.current().accent == "#2DD4BF"       # Fungi 深色主色（青）
    assert theme.set_mode("light") == "light"
    assert theme.current().accent == "#ec4899"       # 浅色仍是孢子粉


def test_bad_mode_falls_back_to_system(store):
    theme.set_mode("purple")
    assert store.read()["theme"] == "system"


def test_light_palette_keeps_white_surface(store):
    """记录页分段的选中态断言依赖浅色卡面仍是 #ffffff（别改色号）。"""
    theme.set_mode("light")
    assert theme.current().surface == "#ffffff"


# ---------- 换肤传播 ----------

def test_style_binding_reapplies_on_switch(qapp, store):
    lab = QLabel("x")
    theme.style(lab, lambda c: f"color:{c.ink};")
    theme.set_mode("light")
    assert theme.LIGHT.ink in lab.styleSheet()
    theme.set_mode("dark")
    assert theme.DARK.ink in lab.styleSheet()


def test_hook_runs_on_switch(qapp, store):
    hits: list[str] = []
    lab = QLabel("x")
    theme.hook(lab, lambda: hits.append(theme.resolved()))
    theme.set_mode("dark")
    assert hits[-1] == "dark"


def test_qss_template_substitutes_tokens():
    assert theme.qss("QLabel{color:$ink;}", theme.DARK) == (
        f"QLabel{{color:{theme.DARK.ink};}}")
