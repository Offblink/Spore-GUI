"""组装 Windows 发行 zip（只含客户端 onedir 目录）。

用法：python tools/make_release_bundle.py     （在 client/ 下，或任意处跑）
前置：先跑过 tools/build_exe.py（要 dist/Spore/ 这个 onedir 目录）
产物：client/dist/Spore-<版本>-win64.zip（解压出来是同名文件夹，双击 Spore.exe）

2026-11-13 起没有后端：无 war、无 Tomcat、无 MySQL、无 db.properties。
包里只有 Spore.exe + _internal/ + 一份说明。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]        # client/
RELEASE_FILES = CLIENT / "tools" / "release"
DIST = CLIENT / "dist"


def version() -> str:
    text = (CLIENT / "spore_client" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("找不到 __version__")
    return m.group(1)


def main() -> int:
    ver = version()
    app = DIST / "Spore"
    if not (app / "Spore.exe").is_file():
        sys.exit(f"缺客户端产物：{app}（先跑 tools/build_exe.py 出 onedir 目录）")

    staging = DIST / f"Spore-{ver}-win64"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(app, staging)
    text = (RELEASE_FILES / "README.txt").read_text(encoding="utf-8")
    (staging / "README.txt").write_text(text.replace("{VERSION}", ver),
                                        encoding="utf-8")

    zip_path = DIST / f"Spore-{ver}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                z.write(p, f"{staging.name}/{p.relative_to(staging).as_posix()}")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    size = zip_path.stat().st_size / 1048576
    print(f"OK   {zip_path}")
    print(f"size={size:.1f} MB  sha256={digest}")
    files = [f for f in staging.rglob("*") if f.is_file()]
    total = sum(f.stat().st_size for f in files)
    print(f"  staging: {len(files)} files, {total / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
