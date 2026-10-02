"""共享 fixture：widget 级测试（点行、信号冒泡）要一个 QApplication。

offscreen 在 pytest 里最稳——不弹真窗口、不要求交互桌面；
必须在 QApplication 构造**之前**设（conftest 先于测试模块加载）。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
