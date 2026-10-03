"""单例锁契约：同名互斥体跨进程互斥，释放后可重拿（= 客户端不会双开）。"""

from spore_client.instance_lock import (
    acquire_instance_lock,
    release_instance_lock,
)


def test_first_acquire_returns_handle():
    h = acquire_instance_lock()
    assert h, "首实例必须拿到句柄（0/None 都说明没拿到锁）"
    release_instance_lock(h)


def test_second_acquire_is_rejected_while_held():
    h = acquire_instance_lock()
    assert h, "首实例必须拿到句柄"
    try:
        assert acquire_instance_lock() is None, "锁被持有时必须判成「已有实例」"
    finally:
        release_instance_lock(h)


def test_lock_can_be_reacquired_after_release():
    h1 = acquire_instance_lock()
    assert h1
    release_instance_lock(h1)
    h2 = acquire_instance_lock()
    assert h2, "释放后要能重新拿到（进程退出后重启不应被残留锁挡住）"
    release_instance_lock(h2)


def test_release_of_empty_handle_is_noop():
    release_instance_lock(None)
    release_instance_lock(0)
