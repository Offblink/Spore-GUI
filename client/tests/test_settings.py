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


def _pane(api) -> SettingsPane:
    return SettingsPane(api, LlmSettings(api_key="sk-test"))


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
