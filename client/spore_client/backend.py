r"""内嵌后端：随客户端起停（取代发行包里的「启动 Spore.bat」）。

规则与旧 bat 一致，只是命令行窗口不弹了：

- ``127.0.0.1:8080`` 已在监听**且真的是 Spore 应用** → 视为**外部后端**（开发态
  自己跑的 Tomcat 或用户自起），只用不接管：不重复起，客户端退出也不去碰它；
- 否则找 war + Tomcat 9，把 war 部署成 ROOT（接口前缀必须是 ``/api`` 而不是
  ``/spore-gui/api``），再 ``org.apache.catalina.startup.Bootstrap start`` 拉起，
  ``CREATE_NO_WINDOW`` 保证不弹控制台窗口（父进程是无控制台的 windowed exe，
  不加这个标记 java 会自开一个控制台）；
- 客户端退出（``aboutToQuit``）只收自己起的那个进程；另外把它挂进 Windows Job
  （``KILL_ON_JOB_CLOSE``），客户端崩溃 / ``taskkill /F`` 也一并带走——窗口已经藏了，
  进程绝不能变成没人关的孤儿。

**就绪信号为什么不能只看端口**：外部 Tomcat 是「先绑 Connector、再部署 webapp」，
端口通了应用可能还没部署（甚至根本起不来，比如数据库口令错），Spring Boot 那套
「refresh 收尾才绑端口 → 端口开 = 能打接口」的保证没有了。所以 :meth:`EmbeddedBackend.ready`
在端口通之后还要探一次 ``GET /api/storage``：只有应用真部署了才会被登录拦截器
回成 **401 JSON**（没部署时 Tomcat 回的是 404 HTML）。

工作目录见 :func:`launch_dir`——发行包等于 war 所在目录（= 旧 bat 的
``cd /d "%~dp0"``），所以 ``db.properties``（DB 口令）、``./logs``、``./data``
都落在 war 旁；开发态 war 在 ``target/`` 下则取仓库根。
java 的 stdout/stderr 落 ``<工作目录>/logs/backend-console.log``——窗口没了，
排障得有落点（每次启动截断，只留最近一次）。

本模块不碰 Qt：进程/端口逻辑可以裸测。
"""

from __future__ import annotations

import ctypes
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path

from .log import get_logger

LOG = get_logger()

HOST = "127.0.0.1"
PORT = 8080
# 0x08000000 = CREATE_NO_WINDOW（subprocess 常量只在 Windows 上存在，这里写字面量）
CREATE_NO_WINDOW = 0x08000000


def bootstrap_cp(home: Path) -> str:
    """Bootstrap 的 classpath：``bin/bootstrap.jar`` + ``bin/tomcat-juli.jar``（分号分隔）。"""
    return os.pathsep.join((str(home / "bin" / "bootstrap.jar"),
                            str(home / "bin" / "tomcat-juli.jar")))


class BackendError(Exception):
    """起不来（缺 war / 缺 Tomcat / 缺 java / 进程秒退 / 超时）——消息可直接给人看。"""


def is_listening(host: str = HOST, port: int = PORT, timeout: float = 0.4) -> bool:
    """端口通没通。**只**代表有进程占着端口，不代表应用能用——就绪判定用 :func:`probe`。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def probe(host: str = HOST, port: int = PORT, timeout: float = 1.0) -> bool:
    """应用真的能打接口吗：无 token ``GET /api/storage``。

    只有 Spore 应用部署成功才会被登录拦截器回成 **401 + R 包装 JSON**；
    webapp 没起来时 Tomcat 回 404 HTML，端口被别的进程（xerj 之类）占着时
    回的也不是这个——两者都算「没就绪」。
    """
    url = f"http://{host}:{port}/api/storage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method="GET"),
                                    timeout=timeout) as resp:
            ctype = resp.headers.get("Content-Type", "")
            resp.read()
            return resp.status == 401 and "json" in ctype
    except urllib.error.HTTPError as e:
        ctype = (e.headers or {}).get("Content-Type", "")
        return e.code == 401 and "json" in ctype
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def war_dirs() -> list[Path]:
    """找 war 的目录顺序（首个含 war 的目录胜出），去重保序。

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


def find_war(dirs: Sequence[Path] | None = None) -> Path | None:
    """找后端 war：发行名 ``spore-backend-*.war`` 优先，其次按名字取最大（开发态 = target/）。

    ``dirs=None`` 用 :func:`war_dirs`；``dirs=[]`` 表示「哪儿都不找」（测试用）。
    """
    for d in war_dirs() if dirs is None else dirs:
        if not d.is_dir():
            continue
        wars = [p for p in d.glob("spore-*.war")]
        if not wars:
            continue
        release = [p for p in wars if p.name.startswith("spore-backend-")]
        return max(release or wars, key=lambda p: p.name)
    return None


def find_tomcat_home(launch: Path) -> Path | None:
    """Tomcat 9 安装目录（= CATALINA_HOME，只读也行），三处按序找：

    1. 环境变量 ``SPORE_TOMCAT``（开发机/CI 指向任意 Tomcat 9）；
    2. ``<launch>/tomcat/``（发行包自带，最常见）；
    3. ``<launch>/tomcat.home`` 一行文本（开发态仓库根放这个，gitignore）。
    """
    env = os.environ.get("SPORE_TOMCAT")
    if env and (Path(env) / "bin" / "bootstrap.jar").is_file():
        return Path(env)
    bundled = launch / "tomcat"
    if (bundled / "bin" / "bootstrap.jar").is_file():
        return bundled
    marker = launch / "tomcat.home"
    if marker.is_file():
        try:
            home = Path(marker.read_text(encoding="utf-8").strip())
        except OSError:
            return None
        if (home / "bin" / "bootstrap.jar").is_file():
            return home
    return None


def prepare_base(home: Path, war: Path, base: Path) -> None:
    """备齐 CATALINA_BASE：``conf/``（缺则从 home 拷、端口钉 8080）+ ``webapps/ROOT.war``。

    必须是独立 base 而不是直接用 home：开发态的 home 往往是课程用的 Tomcat，
    往它 webapps 里塞 ROOT.war 会把课程那套覆盖掉。
    端口必须钉成 :data:`PORT`——客户端/手机/二维码都认 8080，home 的 conf 可能是别的端口。
    """
    conf = base / "conf"
    if not (conf / "server.xml").is_file():
        if not (home / "conf" / "server.xml").is_file():
            raise BackendError(f"Tomcat 目录不完整：{home} 里没有 conf\\server.xml")
        shutil.copytree(home / "conf", conf)
    # 端口**每次启动都钉**：base 里的 server.xml 可能是旧配置/被人改过（实测踩过
    # 残留 base 还是 18090、客户端探 8080 永远不就绪），端口不一致就等于后端没起来
    _pin_http_port(conf / "server.xml", PORT)
    for name in ("webapps", "logs", "temp", "work"):
        (base / name).mkdir(parents=True, exist_ok=True)

    target = base / "webapps" / "ROOT.war"
    if not (target.is_file()
            and target.stat().st_size == war.stat().st_size
            and abs(target.stat().st_mtime - war.stat().st_mtime) < 2):
        shutil.copy2(war, target)   # 覆盖后 Tomcat 下次启动按新 war 重新展开


def _pin_http_port(server_xml: Path, port: int) -> None:
    """把 server.xml 里第一个**没被注释掉**的 Connector 端口改成 ``port``（注释原样保留）。"""
    text = server_xml.read_text(encoding="utf-8")
    # 按注释切段：偶数段是正文、奇数段是 <!-- ... -->，只在正文里动刀——
    # Tomcat 默认模板里 8443/8009 那些 Connector 都在注释里，碰了会把它们一起改掉
    parts = re.split(r"(<!--.*?-->)", text, flags=re.S)
    for i in range(0, len(parts), 2):
        new, n = re.subn(r'(<Connector\s+port=")\d+(")', rf"\g<1>{port}\g<2>",
                         parts[i], count=1)
        if n:
            parts[i] = new
            server_xml.write_text("".join(parts), encoding="utf-8")
            return
    raise BackendError(f"{server_xml} 里找不到 HTTP Connector，无法固定端口 {port}")


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


def launch_dir(war: Path) -> Path:
    """java 的工作目录（db.properties / ./logs / ./data 落哪）。

    发行包：war 所在目录——旧 bat 的 ``cd /d "%~dp0"``。
    开发态：war 在 ``<仓库>/target/`` 下 → 取仓库根
    （否则 ``./data`` ``./logs`` 会掉进 target/，一次 ``mvn clean`` 就没）。
    """
    return war.parent.parent if war.parent.name == "target" else war.parent


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


def config_args(launch: Path) -> list[str]:
    """告诉后端去哪读 ``db.properties``；没有就返回空（回落工作目录 ``./db.properties``）。

    **为什么必须显式指路**：``runtime_base`` 在 Program Files 下把 cwd 迁到可写根
    （``%LOCALAPPDATA%\\Spore``），而属性装载默认按工作目录的 ``./db.properties`` 搜 →
    放在 war 旁的口令文件读不到，回落 classpath 里的 ``db.password=CHANGE_ME``，后端报
    ``Access denied for user 'root'@'localhost'`` 起不来。1.3.1 真机踩过同款
    （当时是 application-local.yml）：配置改对了也连不上库，差别只有 cwd。

    绝对路径 ⇒ 与 cwd 无关，迁不迁都成立。
    口令只从文件读，**绝不进命令行**——argv 在任务管理器/wmic 里是公开的
    （这里传的是文件**路径**，不是口令本身）。
    """
    cfg = launch / "db.properties"
    if cfg.is_file():
        return [f"-Dspore.config={cfg.resolve()}"]
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
    """一个受管的 Tomcat 子进程（也可能没有：外部后端 / 缺件）。"""

    def __init__(self, war: Path | None = None, java: Path | None = None,
                 host: str = HOST, port: int = PORT,
                 search_dirs: Sequence[Path] | None = None):
        self.war = war
        self.java = java
        self.host, self.port = host, port
        self._search_dirs = None if search_dirs is None else list(search_dirs)
        self.proc: subprocess.Popen | None = None
        self.console_log: Path | None = None
        self._job: int | None = None   # 持有 = 后端随客户端一起没（崩溃也算）
        self._probe_at = 0.0           # ready() 节流：主流程每 200ms 轮询
        self._last_probe = False

    # ---------- 状态 ----------
    def ready(self) -> bool:
        """端口通**且应用真部署了**（0.5s 节流，别把轮询打成压测）。"""
        if not is_listening(self.host, self.port):
            self._probe_at = 0.0
            return False
        now = time.monotonic()
        if now - self._probe_at < 0.5:
            return self._last_probe
        self._last_probe = probe(self.host, self.port)
        self._probe_at = now
        return self._last_probe

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
        """已在跑且真能打接口 → False（外部后端，不接管）；拉起了 → True（要 :meth:`wait_ready`）。

        缺 war / 缺 Tomcat / 缺 java 抛 :class:`BackendError`。
        """
        if self.ready():
            LOG.info("backend already serving on %s:%s → 外部后端，不接管",
                     self.host, self.port)
            return False
        war = self.war or find_war(self._search_dirs)
        if war is None or not war.is_file():
            raise BackendError(
                "没找到后端 war（spore-backend-*.war / target/spore-gui.war）："
                "发行包请把它与 Spore.exe 放同一目录，源码开发则先在仓库根跑 mvn clean package。")
        launch = launch_dir(war)
        home = find_tomcat_home(launch)
        if home is None:
            raise BackendError(
                "没找到 Tomcat 9：发行包要有 tomcat\\ 目录（与 Spore.exe 同目录）；"
                "开发机可设环境变量 SPORE_TOMCAT，或在仓库根放一行 tomcat.home。")
        java = self.java or find_java()
        if java is None or not Path(java).is_file():
            raise BackendError("没找到 Java：请安装 JDK 8（课设口径），或把 java 加进 PATH。")
        self.war, self.java = war, Path(java)
        self._spawn(war, home, Path(java))
        return True

    def _spawn(self, war: Path, home: Path, java: Path) -> None:
        # config 探测按 war 位置（launch_dir 语义不变）；cwd/日志根走可写根——
        # Program Files 下 exe 旁建 logs 会 WinError 5 崩启动（见 runtime_base）
        launch = launch_dir(war)
        workdir = runtime_base(launch)
        base = workdir / "tomcat-base"
        # 先备 base（拷 conf + 钉 8080 + 放 ROOT.war），再拉 Bootstrap
        prepare_base(home, war, base)
        log = workdir / "logs" / "backend-console.log"
        self.console_log = log
        cmd = [java,
               f"-Dcatalina.home={home}",
               f"-Dcatalina.base={base}",
               f"-Djava.io.tmpdir={base / 'temp'}",
               *config_args(launch),
               "-cp", bootstrap_cp(home),
               "org.apache.catalina.startup.Bootstrap", "start"]
        self.proc = spawn_hidden(cmd, workdir, log)
        self._job = kill_on_parent_exit(self.proc)   # 失败原因已在函数里记 errno
        LOG.info("backend spawned: pid=%s job=%s home=%s base=%s cwd=%s",
                 self.proc.pid, self._job, home, base, workdir)

    # ---------- 等 ----------
    def wait_ready(self, timeout: float = 90.0, poll: float = 0.2) -> bool:
        """等**应用**就绪（端口 + 探活）；**进程先死**立刻 False（比等满超时快，报错也更准）。

        上限 90s：外部 Tomcat 冷启动要展开 war + 起父容器 + 起 DispatcherServlet，
        实测首次约 40s、之后约 30s（Boot 时代只要 6 秒，这是换外部容器的代价）。
        """
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
        return "\n".join(self._read_console().splitlines()[-lines:])

    def console_text(self) -> str:
        """后端控制台**全文**——做程序化判定（如「是不是数据库连不上」）用。

        别用 tail_console 判定：Spring 秒退时堆栈有几十帧，最后 12 行全是
        ``at com.zaxxer...`` 纯堆栈帧，真正的 ``Access denied`` / ``pool
        initialization`` 特征串在更上面会被切掉（2026-10-29 真机冒烟栽过）。
        日志每次 spawn 都被 ``spawn_hidden`` 用 ``"w"`` 截断，整个文件就是这一次
        启动，读全文是安全且有界的。
        """
        return self._read_console()

    def _read_console(self) -> str:
        if self.console_log is None or not self.console_log.is_file():
            return ""
        try:
            return self.console_log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

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
