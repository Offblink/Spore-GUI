"""Spore 桌面客户端（PySide6 + Fluent）。

架构：单进程、无后端；数据在本机 SQLite，可选连远端 Spore-Cloud 做双向同步。
全部数据在本机 SQLite（``%LOCALAPPDATA%\\Spore\\spore.db``），
``spore_client.store.Store`` 直接读写；本包只做 UI + 作答链路。
"""

# 全仓唯一版本号（构建/发版脚本从这里读，见 tools/build_exe.py）
__version__ = "1.6.0"
