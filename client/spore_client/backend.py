r"""内嵌后端：随客户端起停（取代发行包里的「启动 Spore.bat」）。

规则与旧 bat 一致，只是命令行窗口不弹了：

- ``127.0.0.1:8080`` 已在监听 → 视为**外部后端**（开发态 ``mvn spring-boot:run``
  或用户自起），只用不接管：不重复起，客户端退出也不去碰它；
- 否则把 jar 找出来 ``java -jar`` 拉起，``CREATE_NO_WINDOW`` 保证不弹控制台窗口
  （父进程是无控制台的 windowed exe，不加这个标记 java 会自开一个控制台）；
- 客户端退出（``aboutToQuit``）只收自己起的那个进程；另外把它挂进 Windows Job
  （``KILL_ON_JOB_CLOSE``），客户端崩溃 / ``taskkill /F`` 也一并带走——窗口已经藏了，
  进程绝不能变成没人关的孤儿。

工作目录（Spring 的 ``file:./``）见 :func:`launch_dir`——发行包等于 jar 所在目录
（= 旧 bat 的 ``cd /d "%~dp0"``），所以 ``application-local.yml``（DB 口令）、
``./logs``、``./data`` 都落在 jar 旁；开发态在 ``target/`` 下则取仓库根。
java 的 stdout/stderr 落 ``<工作目录>/logs/backend-console.log``——窗口没了，
排障得有落点（每次启动截断，只留最近一次）。

本模块不碰 Qt：进程/端口逻辑可以裸测。
"""

from __future__ import annotations

import ctypes
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path

from .log import get_logger

LOG = get_logger()

HOST = "127.0.0.1"
PORT = 8080
# 0x08000000 = CREATE_NO_WINDOW（subprocess 常量只在 Windows 上存在，这里写字面量）
CREATE_NO_WINDOW = 0x08000000
# 开发态 target/ 里可能是 sources/javadoc 包，不能当运行 jar
JAR_EXCLUDE = ("-sources.jar", "-javadoc.jar", "-tests.jar")


class BackendError(Exception):
    """起不来（缺 jar / 缺 java / 进程秒退 / 超时）——消息可直接给人看。"""


def is_listening(host: str = HOST, port: int = PORT, timeout: float = 0.4) -> bool:
    """端口通没通。

    够当就绪信号：Spring Boot 的 Tomcat 在 refresh 收尾才绑定端口，
    而数据源等单例 bean 初始化在此之前——端口开了基本就能打接口。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def jar_dirs() -> list[Path]:
    """找 jar 的目录顺序（首个含 jar 的目录胜出），去重保序。

    frozen：``sys.executable`` 是**原 exe 路径**（PyInstaller 6.17.0 实测，
    ``sys._MEIPASS`` 才是临时解压目录）；``argv[0]``/cwd 兜底（相对路径启动时
    cwd 也常是 exe 目录）。
    """
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).resolve().parent)
        if sys.argv and sys.argv[0]:
            dirs.append(Path(sys.argv[0]).expanduser().absolute().parent)
    dirs.append(Path.cwd())
    if not getattr(sys, "frozen", False):
        # 开发态：mvn 产物在仓库根 target/
        dirs.append(Path(__file__).resolve().parents[2] / "target")
    out, seen = [], set()
    for d in dirs:
        key = str(d).lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_jar(dirs: Sequence[Path] | None = None) -> Path | None:
    """找后端 jar：发行名 ``spore-backend-*.jar`` 优先，其次按名字取最大。

    ``dirs=None`` 用 :func:`jar_dirs`；``dirs=[]`` 表示「哪儿都不找」（测试用）。
    """
    for d in jar_dirs() if dirs is None else dirs:
        if not d.is_dir():
            continue
        jars = [p for p in d.glob("spore-*.jar") if not p.name.endswith(JAR_EXCLUDE)]
        if not jars:
            continue
        release = [p for p in jars if p.name.startswith("spore-backend-")]
        return max(release or jars, key=lambda p: p.name)
    return None


def find_java() -> Path | None:
    """找 java：课设口径 JDK8 优先 → ``JAVA_HOME`` → ``ProgramFiles\\Java`` → PATH。"""
    pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    cands = [pf / "Java" / "jdk-1.8" / "bin" / "java.exe"]
    if os.environ.get("JAVA_HOME"):
        cands.append(Path(os.environ["JAVA_HOME"]) / "bin" / "java.exe")
    cands += sorted((pf / "Java").glob("*/bin/java.exe"))
    for c in cands:
        if c.is_file():
            return c
    which = shutil.which("java")
    return Path(which) if which else None


# Windows Job Object：把 java 挂进「句柄一关就全杀」的 job，
# 客户端崩溃 / taskkill /F 也照样把后端带走——窗口已经藏了，
# 要是进程还留着，用户就连「关掉那个窗口」这最后一招都没了。
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_EXTENDED_LIMIT_INFORMATION = 9   # JobObjectExtendedLimitInformation
_JOB_EXT_LIMIT_SIZE = 144             # sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
_LIMIT_FLAGS_OFFSET = 16              # BasicLimitInformation.LimitFlags 的字节偏移

# use_last_error=True：调用后用 ctypes.get_last_error() 拿真 errno（windll 拿不到）
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateJobObjectW.restype = wintypes.HANDLE
_k32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
_k32.SetInformationJobObject.restype = wintypes.BOOL
_k32.SetInformationJobObject.argtypes = (
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD)
_k32.AssignProcessToJobObject.restype = wintypes.BOOL
_k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = (wintypes.HANDLE,)


def kill_on_parent_exit(proc: subprocess.Popen) -> int | None:
    """把子进程挂进 job（KILL_ON_JOB_CLOSE），返回 job 句柄；挂不上返回 None（不致命）。

    句柄必须由调用方**一直持有**：客户端进程一没，内核关掉句柄就杀掉 job 里的进程。
    挂不上必须记 errno —— 否则「崩溃也收尸」这条就只剩一张嘴。
    """
    ctypes.set_last_error(0)
    job = _k32.CreateJobObjectW(None, None)   # 匿名 job：不命名，跨用户/会话零冲突
    if not job:
        LOG.warning("CreateJobObjectW failed errno=%s → 崩溃时后端可能残留",
                    ctypes.get_last_error())
        return None
    info = bytearray(_JOB_EXT_LIMIT_SIZE)
    struct.pack_into("I", info, _LIMIT_FLAGS_OFFSET, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
    if not _k32.SetInformationJobObject(job, _JOB_EXTENDED_LIMIT_INFORMATION,
                                        bytes(info), _JOB_EXT_LIMIT_SIZE):
        LOG.warning("SetInformationJobObject failed errno=%s → 崩溃时后端可能残留",
                    ctypes.get_last_error())
        _k32.CloseHandle(job)
        return None
    ctypes.set_last_error(0)
    # proc._handle 是 CPython Windows 专有的进程句柄（唯一的免开句柄来源）
    if not _k32.AssignProcessToJobObject(job, proc._handle):
        LOG.warning("AssignProcessToJobObject(pid=%s) failed errno=%s → 崩溃时后端可能残留",
                    proc.pid, ctypes.get_last_error())
        _k32.CloseHandle(job)
        return None
    return int(job)


def close_job(job: int | None) -> None:
    """关掉 job 句柄（= 请求内核按 KILL_ON_JOB_CLOSE 收掉里面还活着的进程）。"""
    if job:
        _k32.CloseHandle(job)


def launch_dir(jar: Path) -> Path:
    """java 的工作目录（= Spring 的 ``file:./``：application-local.yml / ./logs / ./data 落哪）。

    发行包：jar 所在目录——旧 bat 的 ``cd /d "%~dp0"``。
    开发态：jar 在 ``<仓库>/target/`` 下 → 取仓库根，跟 ``mvn spring-boot:run`` 一致
    （否则 ``./data`` ``./logs`` 会掉进 target/，一次 ``mvn clean`` 就没）。
    """
    return jar.parent.parent if jar.parent.name == "target" else jar.parent


def app_home() -> Path:
    """应用可写根：``SPORE_HOME`` 可整体重定向，缺省 ``%LOCALAPPDATA%\\Spore``
    （与 log.py / settings_store / capture / login 同一根，同一套约定）。"""
    return Path(os.environ.get(
        "SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore"))


def _writable(d: Path) -> bool:
    """就地建删探针。Windows 上比 ``os.access`` 靠谱：装进 Program Files 的
    非管理员进程必吃 WinError 5，探针一次就现形；成功路径无残留。"""
    probe = d / ".spore-write-probe"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def runtime_base(jar_dir: Path) -> Path:
    """后端的 cwd 与控制台日志根：jar 目录**可写就沿用**（开发态/便携目录语义不变）；
    不可写 → :meth:`app_home`。

    1.1.0 实测回归：装进 ``C:\\Program Files (x86)\\...`` 后 ``spawn_hidden`` 要在 exe 旁
    建 ``logs\\`` → ``PermissionError [WinError 5]`` 直接把客户端崩在启动 1 秒处（打不开）。
    迁到可写根后，后端自己按 ``file:./`` 写的 ``./logs`` ``./data`` 也一并落进
    ``%LOCALAPPDATA%\\Spore``（Spring 日志、题库目录），jar 仍按绝对路径从安装目录读。
    """
    if _writable(jar_dir):
        return jar_dir
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    return home


def config_args(workdir: Path) -> list[str]:
    """开发态补一条 Spring 附加配置位置；发行态返回空。

    jar 里没有 ``application-local.yml``（它在 ``src/main/resources``，gitignore 敏感件，
    打发行包时必须不在场），所以从仓库根起 jar 要把那个目录挂上。目录里没有该文件时
    ``optional:`` 前缀也一声不吭，缺口令照样由 Spring 自己报。

    口令只从文件读，**绝不进命令行**——argv 在任务管理器/wmic 里是公开的。
    """
    dev_cfg = workdir / "src" / "main" / "resources"
    if (dev_cfg / "application-local.yml").is_file():
        return ["--spring.config.additional-location=optional:file:./src/main/resources/"]
    return []


def spawn_hidden(cmd: Sequence[str], cwd: Path, log: Path) -> subprocess.Popen:
    """无窗口拉起子进程，stdout/stderr 全落 ``log``（每次截断，只留最近一次）。

    ``CREATE_NO_WINDOW`` 是「服务器命令行界面不弹出」的全部实现：客户端 exe 是无控制台
    的 windowed 程序，控制台子进程不加这个标记就会自开一个控制台窗口。
    """
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", errors="replace") as fh:
        fh.write(f"=== {' '.join(str(c) for c in cmd)} @ {time.strftime('%F %T')} ===\n")
        fh.flush()
        # 退出 with 时父进程关掉句柄；子进程持有自己那份 dup，继续写没问题
        return subprocess.Popen(
            [str(c) for c in cmd],
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,  # 后端不读 stdin，别让它挂住
            stdout=fh,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )


class EmbeddedBackend:
    """一个受管的 ``java -jar`` 子进程（也可能没有：外部后端 / 缺件）。"""

    def __init__(self, jar: Path | None = None, java: Path | None = None,
                 host: str = HOST, port: int = PORT,
                 search_dirs: Sequence[Path] | None = None):
        self.jar = jar
        self.java = java
        self.host, self.port = host, port
        self._search_dirs = None if search_dirs is None else list(search_dirs)
        self.proc: subprocess.Popen | None = None
        self.console_log: Path | None = None
        self._job: int | None = None   # 持有 = 后端随客户端一起没（崩溃也算）

    # ---------- 状态 ----------
    def ready(self) -> bool:
        return is_listening(self.host, self.port)

    @property
    def alive(self) -> bool:
        """我们起的进程还活着（外部后端 / 没起 = False）。"""
        return self.proc is not None and self.proc.poll() is None

    @property
    def owned(self) -> bool:
        """这个后端是我们起的（退出时才知道该不该收）。"""
        return self.proc is not None

    # ---------- 起 ----------
    def start_if_needed(self) -> bool:
        """已在监听 → False（外部后端，不接管）；拉起了 → True（要 :meth:`wait_ready`）。

        缺 jar / 缺 java 抛 :class:`BackendError`。
        """
        if self.ready():
            LOG.info("backend already listening on %s:%s → 外部后端，不接管",
                     self.host, self.port)
            return False
        jar = self.jar or find_jar(self._search_dirs)
        if jar is None or not jar.is_file():
            raise BackendError(
                "没找到后端 jar（spore-backend-*.jar）：请把它与 Spore.exe 放同一目录"
                "（源码开发则先在仓库根跑 mvn clean package）。")
        java = self.java or find_java()
        if java is None or not Path(java).is_file():
            raise BackendError("没找到 Java：请安装 JDK 8（课设口径），或把 java 加进 PATH。")
        self.jar, self.java = jar, Path(java)
        self._spawn(jar, Path(java))
        return True

    def _spawn(self, jar: Path, java: Path) -> None:
        # config 探测按 jar 位置（launch_dir 语义不变）；cwd/日志根走可写根——
        # Program Files 下 exe 旁建 logs 会 WinError 5 崩启动（见 runtime_base）
        launch = launch_dir(jar)
        workdir = runtime_base(launch)
        log = workdir / "logs" / "backend-console.log"
        self.console_log = log
        self.proc = spawn_hidden(
            [java, "-jar", jar.absolute(), *config_args(launch)], workdir, log)
        self._job = kill_on_parent_exit(self.proc)   # 失败原因已在函数里记 errno
        LOG.info("backend spawned: pid=%s job=%s cmd='%s -jar %s' cwd=%s",
                 self.proc.pid, self._job, java, jar.name, workdir)

    # ---------- 等 ----------
    def wait_ready(self, timeout: float = 60.0, poll: float = 0.2) -> bool:
        """等端口就绪；**进程先死**立刻 False（比等满超时快，报错也更准）。"""
        deadline = time.monotonic() + timeout
        while True:
            if self.ready():
                return True
            if self.proc is None:
                return False  # 没起（外部后端）——调用方本不该等
            if self.proc.poll() is not None:
                LOG.error("backend exited early rc=%s (console: %s)",
                          self.proc.returncode, self.console_log)
                return False
            if time.monotonic() >= deadline:
                LOG.error("backend not ready after %.0fs (console: %s)",
                          timeout, self.console_log)
                return False
            time.sleep(poll)

    def tail_console(self, lines: int = 12) -> str:
        """后端控制台最后几行——窗口没了，这是秒退/超时唯一能给人看的东西。"""
        if self.console_log is None or not self.console_log.is_file():
            return ""
        try:
            text = self.console_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])

    # ---------- 停 ----------
    def stop(self) -> None:
        """客户端退出 → 收掉自己起的后端（外部后端不动）。可重复调用。"""
        proc, self.proc = self.proc, None
        job, self._job = self._job, None
        try:
            if proc is None:
                return
            if proc.poll() is not None:
                LOG.info("backend already exited rc=%s", proc.returncode)
                return
            LOG.info("stopping backend pid=%s", proc.pid)
            # Windows terminate = TerminateProcess：Spring 侧没有必须跑完的停机钩子
            # （actuator shutdown 要开明文关机端口，得不偿失）；端口随进程立刻释放。
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            LOG.info("backend stopped rc=%s", proc.returncode)
        finally:
            close_job(job)   # 万一上面没杀干净，关 job 句柄会连人带进程收走
