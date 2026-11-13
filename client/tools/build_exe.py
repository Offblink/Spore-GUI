"""Spore.exe 构建 + 自检（skill windows-packaging 配方）。

用法：python tools/build_exe.py
解释器**固定绑定** client/.venv-build（干净 venv，看不见全局 PyQt5/torch）；
缺了就打印创建命令并退出 2——不要用开发 venv 打包。

自检（不信退出码）：
- 日志里有 `Copying icon to EXE`（只有真给了 icon 才有这行，且走 stderr）
- dist/Spore/Spore.exe 与同目录 _internal/ 存在（onedir 结构）
- 启动后窗口必须出现：打印「到窗口」耗时（校准 WINDOW_TIMEOUT 的实测依据），
  进程中途死掉（缺依赖 import 崩）或到点没窗口（挂死）都算失败
- 打印产物目录的文件数 / 总体积 / 清单 sha256
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]              # client/
VENV_PY = ROOT / ".venv-build" / "Scripts" / "python.exe"
BASE_PY = Path.home() / "AppData/Local/Programs/Python/Python313/python.exe"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
# 到窗口的阈值（秒）：热态 ~2s，Defender 首扫新构建目录 6–12s（2026-11-13 实测
# 一次 8.3s 到主窗，叠加枚举轮询后被 15s 阈值误杀）。30s 给冷启留足余量；
# 进程先死会立刻失败，不会白等。
WINDOW_TIMEOUT = 30


def version() -> str:
    text = (ROOT / "spore_client" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("spore_client/__init__.py 里找不到 __version__")
    return m.group(1)


def ensure_env() -> None:
    if VENV_PY.is_file():
        return
    print("缺少干净构建 venv，先执行：")
    print(f'  "{BASE_PY}" -m venv --without-pip "{ROOT / ".venv-build"}"')
    print(f'  "{BASE_PY}" -m pip --python "{VENV_PY}" install '
          "-i https://mirrors.aliyun.com/pypi/simple/ "
          '"PySide6==6.10.2" "PySide6-Fluent-Widgets==1.11.3" '
          "pyinstaller httpx markdown Pillow keyboard")
    sys.exit(2)


def window_shows_up(pid: int) -> bool:
    """该 pid 是否已有可见顶层窗口（onedir 单进程，窗口就长在它自己身上）。"""
    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd: int, _lparam: int) -> bool:
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(_cb, 0)
    return bool(found)


def tree_digest(root: Path) -> tuple[str, int, int]:
    """产物目录指纹：按相对路径排序，累加 (路径, 内容 sha256)。

    返回 (清单 sha256, 文件数, 总字节数)。
    """
    h = hashlib.sha256()
    total = 0
    nfiles = 0
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode("utf-8"))
        h.update(b"\0")
        data = p.read_bytes()
        h.update(hashlib.sha256(data).digest())
        total += len(data)
        nfiles += 1
    return h.hexdigest(), nfiles, total


def main() -> int:
    ensure_env()
    ver = version()
    print(f"Spore {ver}，构建解释器 {VENV_PY}")

    subprocess.run([str(VENV_PY), str(ROOT / "tools" / "make_icon.py")],
                   check=True, cwd=ROOT)

    for d in (BUILD, DIST):                    # 旧 Analysis/产物会串
        shutil.rmtree(d, ignore_errors=True)
    log = subprocess.run(
        [str(VENV_PY), "-m", "PyInstaller", "Spore.spec",
         "--noconfirm", "--clean"],
        cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace")
    out = (log.stdout or "") + (log.stderr or "")   # PyInstaller INFO 走 stderr
    if log.returncode != 0:
        print(out[-6000:])
        return log.returncode

    assert "Copying icon to EXE" in out, "图标没进 exe（日志无 Copying icon）"
    exe = DIST / "Spore" / "Spore.exe"
    assert exe.is_file(), f"缺产物 {exe}"
    assert (exe.parent / "_internal").is_dir(), "缺 _internal/（onedir 结构不对）"

    # 窗口存活自检：onedir 是单进程（onefile 那种 bootloader 父子两枚没有了）。
    # 进程先死 = import 崩；到点没窗口 = 挂死；两种都算失败，且都打印耗时。
    # 另查启动日志——PyInstaller 的「Failed to execute script」错误框也是可见窗口，
    # 只看窗口会把「import 即崩」误判成成功（2026-11-13 缺 tzdata 实测栽过）。
    log_path = Path(os.environ.get(
        "SPORE_HOME", Path.home() / "AppData" / "Local" / "Spore")) / "logs" / "client.log"
    log_from = log_path.stat().st_size if log_path.is_file() else 0
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    t0 = time.monotonic()
    while proc.poll() is None and not window_shows_up(proc.pid):
        if time.monotonic() - t0 >= WINDOW_TIMEOUT:
            break
        time.sleep(0.3)
    elapsed = time.monotonic() - t0
    started = False
    if log_path.is_file():
        with log_path.open("rb") as fh:
            fh.seek(log_from)
            started = b"starting (frozen=True)" in fh.read()
    ok = proc.poll() is None and window_shows_up(proc.pid) and started
    print(f"自检：窗口 {'出现' if ok else '未出现'}，启动日志 "
          f"{'有' if started else '无'}，耗时 {elapsed:.1f}s"
          f"（阈值 {WINDOW_TIMEOUT}s，进程退出码 {proc.poll()}）")
    if ok:
        # 收尸：/T 连它拉起的子进程一起杀（当前是单进程；防御性带上）
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    assert ok, (f"窗口 exe {WINDOW_TIMEOUT}s 内没起窗（退出码 {proc.poll()}；"
                "缺 GUI 依赖？看 %LOCALAPPDATA%\\Spore\\logs）")

    digest, nfiles, nbytes = tree_digest(exe.parent)
    print(f"OK   {exe.parent}")
    print(f"files={nfiles}  size={nbytes / 1048576:.1f} MB")
    print(f"tree-sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
