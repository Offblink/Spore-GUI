"""设置页行为（2026-10-03 反馈回归）。

- 题库目录：refresh/切换后按后端真实键 path/fileCount/bytes 回填
  （旧代码读 dir/files 两个不存在的键 → 输入框恒空、统计恒 ?）；
- 滚轮不改数值：焦点还在输入框时滚动页面不许顺手改数字。
"""

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from spore_client.answer.settings import LlmSettings
from spore_client.settings import SettingsPane, _NoWheelSpinBox


class _StorageApi:
    """只给设置页目录区用的假后端（键形状 = StorageServiceImpl.info/switchTo）。"""

    def __init__(self):
        self.returned = {"path": "D:/题库", "fileCount": 7, "bytes": 12345}

    def storage_info(self):
        return dict(self.returned)

    def switch_storage(self, path):
        self.returned = {"path": path, "fileCount": 2, "bytes": 9}
        return dict(self.returned)


def _pane(api, llm: LlmSettings | None = None) -> SettingsPane:
    return SettingsPane(api, llm or LlmSettings(api_key="sk-test"))


def test_storage_refresh_fills_dir_and_stats(qapp):
    pane = _pane(_StorageApi())
    pane.refresh()
    assert pane.dir_edit.text() == "D:/题库"
    assert pane.dir_info.text() == "7 个文件 · 12345 字节"


def test_storage_switch_updates_stats_immediately(qapp):
    api = _StorageApi()
    pane = _pane(api)
    pane._switch_to("E:/新库")
    assert pane.dir_edit.text() == "E:/新库"          # 输入框跟着切
    assert pane.dir_info.text() == "2 个文件 · 9 字节"  # 底部统计当场刷新


def _wheel_event() -> QWheelEvent:
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                       Qt.NoButton, Qt.NoModifier, Qt.ScrollBegin, False)


def test_wheel_does_not_change_spin_value(qapp):
    spin = _NoWheelSpinBox()
    spin.setRange(0, 10)
    spin.setValue(5)
    spin.wheelEvent(_wheel_event())   # 焦点在框上滚轮也忽略（反馈现场）
    assert spin.value() == 5


def test_plain_spinbox_still_reacts_to_wheel(qapp):
    """判别对照：没有防护的 SpinBox 滚轮会改值——证明上一条钉住的是修复本身。"""
    from qfluentwidgets import SpinBox

    spin = SpinBox()
    spin.setRange(0, 10)
    spin.setValue(5)
    spin.wheelEvent(_wheel_event())
    assert spin.value() != 5


# ---------- API key 输入框（2026-10-03 拍板：只依赖 config，不回显） ----------

def test_key_input_saves_without_echoing(qapp):
    pane = _pane(_StorageApi(), LlmSettings())      # 起点：没设过 key
    assert pane.key_edit.text() == ""                 # 永不回显旧值
    assert pane.key_edit.placeholderText() == "未设置 ✗（粘贴 API key 后回车保存）"
    pane.key_edit.setText("  sk-new  ")
    pane._save_key()
    assert pane.llm.api_key == "sk-new"               # 即改即生效
    assert pane.key_edit.text() == ""                 # 保存即清空，不回显
    # 状态句子直接做占位符（2026-10-03 反馈：并入输入框，不再单挂一行字）
    assert pane.key_edit.placeholderText() == "已设置 ✓（不回显；粘贴新值回车即覆盖）"
    assert pane._collect()["apiKey"] == "sk-new"      # 进落盘白名单


def test_save_key_clears_startup_key_error_and_hint(qapp):
    # 2026-10-03 用户实测：设完 API key，底部红字「API key 未设置」留到重启不消
    llm = LlmSettings(api_key="")
    llm.errors.append("API key 未设置——到设置页粘贴后回车保存即生效")
    pane = _pane(_StorageApi(), llm)
    assert pane.llm.errors, "预设：启动错误先在场"
    assert pane._err_hint is not None, "预设：红字标签已建并被引用"

    pane.key_edit.setText("sk-new-key")
    pane._save_key()

    assert llm.api_key == "sk-new-key"
    assert not any("API key" in e for e in llm.errors)
    assert pane._err_hint is None, "撤下的标签引用一并清空"
