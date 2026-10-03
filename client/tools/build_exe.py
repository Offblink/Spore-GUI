"""Spore.exe 构建 + 自检（skill windows-packaging 配方）。

用法：python tools/build_exe.py
解释器**固定绑定** client/.venv-build（干净 venv，看不见全局 PyQt5/torch）；
缺了就打印创建命令并退出 2——不要用开发 venv 打包。

自检（不信退出码）：
- 日志里有 `Copying icon to EXE`（只有真给了 icon 才有这行，且走 stderr）
- dist/Spore.exe 存在、打印体积与 sha256
- 窗口 exe 启动 15 秒后仍活着（导入失败时它没有 stdout，进程直接死）
- 另存一份带版本名的发布资产 dist/Spore-<ver>-win64.exe
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]              # client/
VENV_PY = ROOT / ".venv-build" / "Scripts" / "python.exe"
BASE_PY = Path.home() / "AppData/Local/Programs/Python/Python313/python.exe"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


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
          "pyinstaller httpx markdown qrcode Pillow keyboard")
    sys.exit(2)


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
    exe = DIST / "Spore.exe"
    assert exe.is_file(), f"缺产物 {exe}"

    # 窗口 exe 存活自检：onefile 解包 + 起 Qt 慢，给 15s
    proc = subprocess.Popen([str(exe)], cwd=str(DIST))
    time.sleep(15)
    alive = proc.poll() is None
    if alive:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    assert alive, "窗口 exe 15s 内退出（缺 GUI 依赖？看 %LOCALAPPDATA%\\Spore\\logs）"

    asset = DIST / f"Spore-{ver}-win64.exe"
    shutil.copy2(exe, asset)
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    print(f"OK   {asset}")
    print(f"size={asset.stat().st_size / 1048576:.1f} MB")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
