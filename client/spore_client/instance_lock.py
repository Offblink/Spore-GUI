r"""Windows 命名互斥体：客户端单例的**权威判据**。

为什么不能拿 ``QLocalServer.listen`` 判单例：本机同会话两个进程对**同名** server
listen 都会成功（2026-10-03 实测：连开两个 Spore.exe，日志各自一条
``instance started: pipe owned``，进程 2 → 4）——同名 listen 不冲突，判据形同虚设。
内核互斥体同名必然互斥，所以：

- **单例判据** = ``CreateMutexW`` 的 ``ERROR_ALREADY_EXISTS``（跨进程、内核级）；
- ``QLocalServer`` 降级成**唤醒通道**：只有首实例 listen，第二实例连上去发个 wake 就退。

句柄语义：首实例必须**一直持有**句柄，锁才一直有效；进程退出（含崩溃）由内核释放，
不会留死锁 —— 这正是命名互斥体优于「手写标志文件/命名事件」的地方。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from .log import get_logger

LOG = get_logger()

ERROR_ALREADY_EXISTS = 183
# 带用户名：跨用户会话互不干扰（与 main.INSTANCE_NAME 同口径）。
# **不能加 `Spore\` 这种自造前缀**：合法命名空间只有 `Global\`/`Local\`/`Session\`，
# 其余反斜杠一律 ERROR_PATH_NOT_FOUND（errno=3，2026-10-03 实测）；不写前缀 = 会话内，
# 与 Local\ 等价、够用。
INSTANCE_LOCK_NAME = f"Spore.DesktopInstance.{os.environ.get('USERNAME', 'default')}"

# use_last_error=True：ctypes 会在**每次调用后**替我们抓 errno，否则
# get_last_error() 拿到的是别的 Win32 调用的残留值
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = wintypes.HANDLE
_k32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)


def acquire_instance_lock() -> int | None:
    """首实例 → 返回句柄（持有到进程结束，锁才有效）；已有实例 → ``None``。

    ``CreateMutexW`` 自身失败（几乎不可能）返回 ``0``：调用方按「首实例」放行并已记
    ERROR —— 宁可理论上可能双开，也不能让客户端起不来。
    """
    ctypes.set_last_error(0)
    handle = _k32.CreateMutexW(None, False, INSTANCE_LOCK_NAME)
    if not handle:
        LOG.error("CreateMutexW(%s) failed errno=%s → 按首实例继续",
                  INSTANCE_LOCK_NAME, ctypes.get_last_error())
        return 0
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _k32.CloseHandle(handle)      # 不关就等于自己也攥着锁
        return None
    return int(handle)


def release_instance_lock(handle: int | None) -> None:
    """显式放锁；正常退出其实用不上（进程退出内核自动释放），给测试/收尾用。"""
    if handle:
        _k32.CloseHandle(handle)
