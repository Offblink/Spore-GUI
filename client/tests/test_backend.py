"""backend 契约：不接管外部后端 / 缺件要说人话 / 无窗口拉起 / 退出只收自己的进程。

测试一律注入端口（free_port / listener），绝不碰真 8080——本机可能正跑着别的服务。
"""

import ctypes
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from spore_client.backend import (
    CREATE_NO_WINDOW,
    BackendError,
    EmbeddedBackend,
    config_args,
    find_jar,
    is_listening,
    kill_on_parent_exit,
    launch_dir,
    runtime_base,
    spawn_hidden,
)

# 子进程自报「我有没有控制台」：有控制台 = 有命令行窗口可弹。
# 父测试进程自己是有控制台的，所以这条断言不空转——去掉 CREATE_NO_WINDOW
# 它就会继承到控制台，console= 非 0，测试立刻红。
_CONSOLE_PROBE = (
    "import ctypes, time; "
    "print('console=%d' % ctypes.windll.kernel32.GetConsoleWindow(), flush=True); "
    "time.sleep(60)"
)


@pytest.fixture()
def free_port():
    """当前没人监听的端口（绑定即释放，未建立过连接，无 TIME_WAIT 残留）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def listener():
    """真在监听的端口——扮演「外部后端已经在跑」。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    yield s.getsockname()[1]
    s.close()


# ---------- 端口探测（就绪信号） ----------

def test_is_listening_true_when_port_bound(listener):
    assert is_listening(port=listener)


def test_is_listening_false_on_free_port(free_port):
    assert not is_listening(port=free_port)


# ---------- 找 jar ----------

def test_find_jar_prefers_release_name(tmp_path):
    (tmp_path / "spore-gui-0.1.0-SNAPSHOT.jar").write_bytes(b"")
    (tmp_path / "spore-backend-1.0.0.jar").write_bytes(b"")
    assert find_jar([tmp_path]).name == "spore-backend-1.0.0.jar"


def test_find_jar_skips_sources_and_javadoc(tmp_path):
    (tmp_path / "spore-gui-0.1.0-SNAPSHOT-sources.jar").write_bytes(b"")
    (tmp_path / "spore-gui-0.1.0-SNAPSHOT-javadoc.jar").write_bytes(b"")
    assert find_jar([tmp_path]) is None


def test_find_jar_first_dir_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "spore-backend-1.0.0.jar").write_bytes(b"")
    (b / "spore-backend-2.0.0.jar").write_bytes(b"")
    assert find_jar([a, b]).name == "spore-backend-1.0.0.jar"


def test_find_jar_empty_search_list_finds_nothing():
    assert find_jar([]) is None          # dirs=[] 表示「哪儿都不找」，不回落默认


def test_find_jar_ignores_missing_dir(tmp_path):
    assert find_jar([tmp_path / "nope"]) is None


# ---------- 工作目录 / 开发态配置 ----------

def test_launch_dir_release_is_jar_dir(tmp_path):
    assert launch_dir(tmp_path / "spore-backend-1.0.0.jar") == tmp_path


def test_launch_dir_target_goes_to_repo_root(tmp_path):
    """开发态 jar 在 target/ 下 → 工作目录取仓库根（否则 ./data 掉进 target/ 会被 clean 清掉）。"""
    target = tmp_path / "target"
    target.mkdir()
    assert launch_dir(target / "spore-gui-0.1.0-SNAPSHOT.jar") == tmp_path


def test_config_args_empty_without_dev_local_yml(tmp_path):
    assert config_args(tmp_path) == []                    # 发行包：全靠 jar 同目录的 yml


def test_config_args_points_at_src_resources_only_when_yml_there(tmp_path):
    dev = tmp_path / "src" / "main" / "resources"
    dev.mkdir(parents=True)
    assert config_args(tmp_path) == []                    # 目录在但没口令文件 → 不硬加
    (dev / "application-local.yml").write_text("spring: {}", encoding="utf-8")
    assert config_args(tmp_path) == [
        "--spring.config.additional-location=optional:file:./src/main/resources/"]


# ---------- 起 ----------

def test_external_backend_is_reused_not_taken_over(listener):
    be = EmbeddedBackend(search_dirs=[], port=listener)
    assert be.start_if_needed() is False      # 已在监听 → 不接管
    assert not be.owned                       # 也没另起进程（退出时更不该去收它）


def test_missing_jar_raises_readable_error(free_port):
    be = EmbeddedBackend(search_dirs=[], port=free_port)
    with pytest.raises(BackendError, match="jar"):
        be.start_if_needed()


def test_missing_java_raises_readable_error(tmp_path, free_port):
    jar = tmp_path / "spore-backend-1.0.0.jar"
    jar.write_bytes(b"")
    be = EmbeddedBackend(jar=jar, java=tmp_path / "no-such-java.exe", port=free_port)
    with pytest.raises(BackendError, match="Java"):
        be.start_if_needed()


def test_spawn_is_windowless_and_console_lands_in_log(tmp_path, free_port):
    """拉起的子进程带 CREATE_NO_WINDOW，输出落 backend-console.log，秒退能被认出来。"""
    jar = tmp_path / "spore-backend-1.0.0.jar"
    jar.write_bytes(b"")
    # 假 java = python：`python -jar …` 立刻报错退出，正好用来验「秒退」这条分支
    be = EmbeddedBackend(jar=jar, java=Path(sys.executable), port=free_port)
    assert be.start_if_needed() is True
    assert be.owned
    assert be.console_log == tmp_path / "logs" / "backend-console.log"
    assert be.wait_ready(timeout=15, poll=0.05) is False   # 没起来就是没起来，不等满超时
    assert be.tail_console()                               # 秒退时能给人看的东西就在日志里
    be.stop()
    assert not be.owned


def test_spawn_hidden_gives_child_no_console(tmp_path):
    """「服务器命令行界面不弹出」的实证：子进程连控制台都没有（所以无窗可弹）。"""
    log = tmp_path / "logs" / "console.log"
    proc = spawn_hidden([sys.executable, "-c", _CONSOLE_PROBE], tmp_path, log)
    try:
        # 只认 `console=<数字>`：日志头里回显的探针源码含 `console=%d`，
        # 用裸 `console=` 当条件会匹配到自己的头，抢在子进程落笔之前就退出（实测假红）
        deadline = time.time() + 15
        text = ""
        while time.time() < deadline and not re.search(r"console=\d", text):
            if proc.poll() is not None:
                break
            time.sleep(0.1)
            text = log.read_text(encoding="utf-8", errors="replace")
        text = log.read_text(encoding="utf-8", errors="replace")  # 收尾再读全量
        assert proc.poll() is None, f"探针子进程提前退出 rc={proc.poll()} log={text!r}"
        hit = re.search(r"console=(\d+)", text)
        assert hit is not None, f"子进程没自报控制台：log={text!r}"
        assert hit.group(1) == "0", f"子进程有控制台窗口：console={hit.group(1)}"
    finally:
        proc.kill()
        proc.wait(timeout=5)


# ---------- 停 ----------

def test_stop_without_spawn_is_noop(free_port):
    be = EmbeddedBackend(port=free_port)
    be.stop()
    assert not be.owned


def test_wait_ready_without_process_is_false(free_port):
    assert EmbeddedBackend(port=free_port).wait_ready(timeout=5) is False


def test_job_kills_child_when_client_goes_away():
    """窗口已经藏了：客户端进程一没（崩溃 / taskkill /F 也算），后端必须跟着没。"""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            creationflags=CREATE_NO_WINDOW)
    job = kill_on_parent_exit(proc)
    assert job is not None, "job object 挂不上（Win8+ 才允许嵌套 job）"
    try:
        ctypes.windll.kernel32.CloseHandle(job)  # 模拟客户端消失：句柄被内核关掉
        proc.wait(timeout=15)
        assert proc.poll() is not None           # 内核把 job 里的进程收了
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_stop_kills_own_process_and_is_idempotent():
    be = EmbeddedBackend(search_dirs=[])
    be.proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=CREATE_NO_WINDOW,
    )
    proc = be.proc
    be.stop()
    assert proc.poll() is not None       # 真收掉了
    assert not be.owned
    be.stop()                            # 重复调用不炸


# ---------- 可写根（1.1.0 装进 Program Files 启动即崩的回归钉） ----------

def test_writable_probes_without_leaving_residue(tmp_path):
    from spore_client.backend import _writable

    assert _writable(tmp_path) is True
    assert _writable(tmp_path / "no" / "such") is False   # 建不出来 → OSError → False
    assert not (tmp_path / ".spore-write-probe").exists()  # 探针即用即删


def test_runtime_base_keeps_jar_dir_when_writable(tmp_path):
    # 开发态/便携目录：行为与旧版逐字节一致（./data ./logs 仍落 jar 旁）
    assert runtime_base(tmp_path) == tmp_path


def test_runtime_base_falls_back_to_spore_home_when_unwritable(tmp_path, monkeypatch):
    # Program Files 场景：jar 目录不可写 → SPORE_HOME（缺则现建）
    monkeypatch.setattr("spore_client.backend._writable", lambda d: False)
    monkeypatch.setenv("SPORE_HOME", str(tmp_path / "home"))
    out = runtime_base(Path(r"C:\Program Files (x86)\Spore-1.1.0-win64"))
    assert out == tmp_path / "home"
    assert out.is_dir()
