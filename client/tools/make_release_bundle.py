"""组装 Windows 一体化发行包（onedir 客户端目录 + 后端 jar + 建库脚本 + 口令模板）。

用法：python tools/make_release_bundle.py     （在 client/ 下，或任意处跑）
产物：client/dist/Spore-<版本>-win64.zip（解压出来是同名文件夹，双击里面的 Spore.exe）

没有启动脚本：后端由客户端自己拉起（见 spore_client/backend.py，无命令行窗口、
随客户端退出而停），所以包里只有客户端目录 + jar + 建库/配置说明。

前置：先跑过 tools/build_exe.py（要 dist/Spore/ 这个 onedir 目录），
且在仓库根跑过 `mvn -DskipTests clean package -P dist`（要 target/spore-gui-*.jar）。
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
import zipfile
from pathlib import Path

CLIENT = Path(__file__).resolve().parents[1]        # client/
REPO = CLIENT.parent                                 # 仓库根
RELEASE_FILES = CLIENT / "tools" / "release"
DIST = CLIENT / "dist"


def version() -> str:
    text = (CLIENT / "spore_client" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("找不到 __version__")
    return m.group(1)


def find_jar(ver: str) -> Path:
    cands = sorted((REPO / "target").glob("spore-gui-*.jar"))
    jars = [p for p in cands if not p.name.endswith("-sources.jar")]
    if not jars:
        sys.exit("缺后端 jar：先在仓库根跑 mvn -DskipTests clean package -P dist")
    jar = jars[-1]
    # 永久守卫：jar 内绝不许带 application-local.yml（本机 DB 口令）——
    # 忘带 -P dist 打的包在这里当场拦下（v1.1.1 曾把口令打进 jar 放进 release）
    with zipfile.ZipFile(jar) as z:
        if "BOOT-INF/classes/application-local.yml" in z.namelist():
            sys.exit(f"拒绝组装：{jar.name} 内嵌了 application-local.yml（真实 DB 口令）。"
                     "请在仓库根用 mvn -DskipTests clean package -P dist 重建后再打包")
    target = DIST / f"spore-backend-{ver}.jar"
    shutil.copy2(jar, target)
    return target


def main() -> int:
    ver = version()
    app = DIST / "Spore"
    if not (app / "Spore.exe").is_file():
        sys.exit(f"缺客户端产物：{app}（先跑 tools/build_exe.py 出 onedir 目录）")
    jar = find_jar(ver)
    schema = REPO / "docs" / "schema.sql"
    if not schema.is_file():
        sys.exit(f"缺建库脚本：{schema}")

    # 暂存 = 客户端 onedir 目录整体平铺进来（Spore.exe + _internal/），
    # jar 必须与 Spore.exe 同目录——客户端按 exe 所在目录找后端（backend.jar_dirs）
    staging = DIST / f"Spore-{ver}-win64"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(app, staging)
    shutil.copy2(jar, staging / jar.name)
    shutil.copy2(schema, staging / "schema.sql")
    for name in ("README.txt", "application-local.yml.example"):
        text = (RELEASE_FILES / name).read_text(encoding="utf-8")
        (staging / name).write_text(text.replace("{VERSION}", ver), encoding="utf-8")

    zip_path = DIST / f"Spore-{ver}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_file():
                z.write(p, f"{staging.name}/{p.relative_to(staging).as_posix()}")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(f"OK   {zip_path}")
    print(f"size={zip_path.stat().st_size / 1048576:.1f} MB  sha256={digest}")
    for p in sorted(staging.iterdir()):
        if p.is_dir():
            files = [f for f in p.rglob("*") if f.is_file()]
            size = sum(f.stat().st_size for f in files)
            print(f"  {p.name}/  {size} B ({len(files)} files)")
        else:
            print(f"  {p.name}  {p.stat().st_size} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
