"""共享 fixture：widget 级测试（点行、信号冒泡）要一个 QApplication。

offscreen 在 pytest 里最稳——不弹真窗口、不要求交互桌面；
必须在 QApplication 构造**之前**设（conftest 先于测试模块加载）。
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 单例互斥体名带 USERNAME（instance_lock）——不改掉的话，**开着 Spore.exe
# 跑门禁必红**（真进程占着同一把锁，2026-10-05 实测）。测试进程换用户名 =
# 换一把锁，隔离出真应用状态；USERNAME 只被 instance_lock/main 读（已 grep）。
os.environ["USERNAME"] = "spore-pytest"


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
