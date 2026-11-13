"""出厂检查：发行 zip 的红线（2026-11-13 起无后端、无账号、无同步）。

用法（必须用构建 venv——脚本要读 exe 的 PYZ）：
    MSYS_NO_PATHCONV=1 cmd.exe /c ".venv-build\\Scripts\\python.exe tools\\factory_check.py"
（在 client/ 下跑；先跑过 tools/make_release_bundle.py）

红线（任一不过 → 退出码 1）：
1. zip 内任何层级无 .bat（Tomcat 那套已下线，发行包也不该带脚本）；
2. 本机私有文件不进包：db.properties / application-local.yml / ui_settings.json /
   device.token（历史遗留物与真实口令都可能藏在里面）；嵌套 jar/war 再钻一层查；
3. 关键件抽查分两层（onedir 形态决定的，别混）：
   - 磁盘层 = zip 路径：_internal 里的资产/Qt 原生件；
   - PYZ 层 = exe 内字节码：markdown/keyboard/spore_client 这类纯 Python 包
     只活在 exe 的 PYZ 里，zip 路径上根本没有。

不打印任何口令/key 内容。
"""

from __future__ import annotations

import io
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]        # client/
DIST = CLIENT / "dist"

FORBIDDEN_NAMES = {
    "db.properties",
    "application-local.yml",
    "ui_settings.json",
    "device.token",
}

# 磁盘层标记：子串必须至少命中一条 zip entry 路径
DISK_MARKERS = (
    "_internal/",                  # onedir 结构本体
    "spore_client/assets/",         # 包内资产（图标等）真在磁盘上
    "icon-16.png",
    "icon-128.png",
    "PySide6",                      # Qt 原生件
    "matplotlib",                   # 懒加载依赖：漏了公式静默变源码（2026-11-13）
)
# PYZ 层标记：纯 Python 包，只查 exe 内字节码（zip 路径上没有）
PYZ_MARKERS = ("markdown", "keyboard", "spore_client")


def version() -> str:
    text = (CLIENT / "spore_client" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("找不到 __version__")
    return m.group(1)


def scan_bytes(data: bytes, where: str, depth: int, problems: list[str]) -> None:
    """查私有文件名；jar/war 内再钻一层（历史遗留包里可能还有）。"""
    base = where.rsplit("/", 1)[-1].lower()
    if base in FORBIDDEN_NAMES:
        problems.append(f"发现私有文件：{where}")
    if depth < 4 and base.endswith((".jar", ".war")):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z2:
                for info2 in z2.infolist():
                    if info2.is_dir():
                        continue
                    scan_bytes(z2.read(info2), f"{where}!/{info2.filename}",
                               depth + 1, problems)
        except zipfile.BadZipFile:
            pass                            # 非 zip 的 .jar 直接跳过


def pyz_module_names(exe_bytes: bytes) -> set[str]:
    """读 zip 里那份 Spore.exe 的 PYZ 目录（验的是要发出去的字节）。"""
    try:
        from PyInstaller.archive.readers import CArchiveReader
    except ImportError:
        sys.exit("FAIL  缺 PyInstaller：请用 .venv-build\\Scripts\\python.exe 跑本脚本")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".exe", dir=DIST) as tmp:
        tmp.write(exe_bytes)
    try:
        pyz = CArchiveReader(tmp.name).open_embedded_archive("PYZ.pyz")
        toc = pyz.toc
        if isinstance(toc, dict):
            return set(toc.keys())
        return {t[0] for t in toc}
    finally:
        os.unlink(tmp.name)


def main() -> int:
    ver = version()
    zip_path = DIST / f"Spore-{ver}-win64.zip"
    if not zip_path.is_file():
        sys.exit(f"FAIL  缺发行 zip：{zip_path}（先跑 tools/make_release_bundle.py）")

    problems: list[str] = []
    paths: list[str] = []
    exe_bytes: bytes | None = None
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            paths.append(name)
            if name.rsplit("/", 1)[-1].lower().endswith(".bat"):
                problems.append(f"zip 内有 .bat：{name}")
            data = z.read(info)
            if name.rsplit("/", 1)[-1].lower() == "spore.exe":
                exe_bytes = data
            scan_bytes(data, name, 1, problems)

    # 红线 3a：磁盘层（zip 路径）
    missing = [m for m in DISK_MARKERS if not any(m in p for p in paths)]

    # 红线 3b：PYZ 层（exe 内字节码）
    pyz_note = "PYZ 层未查（zip 里没找到 Spore.exe？）"
    if exe_bytes is not None:
        names = pyz_module_names(exe_bytes)
        lack = [m for m in PYZ_MARKERS
                if not any(k == m or k.startswith(m + ".") for k in names)]
        missing.extend(f"PYZ 缺 {m}" for m in lack)
        state = "OK" if not lack else f"LACK {lack}"
        pyz_note = f"PYZ {len(names)} modules: {'/'.join(PYZ_MARKERS)} {state}"
    else:
        missing.append("zip 里没有 Spore.exe")

    for msg in problems:
        print(f"FAIL  {msg}")
    if missing:
        print(f"FAIL  关键件缺失：{', '.join(missing)}")
    if problems or missing:
        return 1
    size = zip_path.stat().st_size
    print(f"PASS  {zip_path.name}  entries={len(paths)}  size={size / 1048576:.1f} MB  {pyz_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
