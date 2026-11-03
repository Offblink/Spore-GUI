"""组装 Windows 一体化发行包（onedir 客户端目录 + 后端 war + 自带 Tomcat 9 + 口令模板）。

用法：python tools/make_release_bundle.py     （在 client/ 下，或任意处跑）
产物：client/dist/Spore-<版本>-win64.zip（解压出来是同名文件夹，双击里面的 Spore.exe）

没有启动脚本：后端由客户端自己拉起（见 spore_client/backend.py，无命令行窗口、
随客户端退出而停），所以包里只有客户端目录 + war + Tomcat 9（bin/lib/conf）+ 口令模板。

后端是**严格 SSM 的 war**（Spring + SpringMVC + MyBatis，无 Spring Boot），
必须有 Servlet 容器才能跑——所以包里带一份 Tomcat 9：客户端首启把它配成独立的
CATALINA_BASE（端口钉 8080、war 部署成 ROOT），见 backend.prepare_base。

前置：先跑过 tools/build_exe.py（要 dist/Spore/ 这个 onedir 目录），
且在仓库根跑过 `mvn -DskipTests clean package`（要 target/spore-gui.war）。
"""

from __future__ import annotations

import hashlib
import os
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


def find_war(ver: str) -> Path:
    war = REPO / "target" / "spore-gui.war"
    if not war.is_file():
        sys.exit("缺后端 war：先在仓库根跑 mvn -DskipTests clean package")
    # 永久守卫：war 里绝不许带本机 DB 口令文件（v1.1.1 曾把口令打进 jar 放进 release）
    with zipfile.ZipFile(war) as z:
        for name in z.namelist():
            if name.endswith("WEB-INF/classes/db.properties") or \
                    name.endswith("WEB-INF/classes/application-local.yml"):
                sys.exit(f"拒绝组装：{war.name} 内嵌了 {name}（真实 DB 口令）。"
                         "口令文件只放仓库根、别放进 src/main/resources")
    target = DIST / f"spore-backend-{ver}.war"
    shutil.copy2(war, target)
    return target


def tomcat_home() -> Path:
    """打包用的 Tomcat 9 源：SPORE_TOMCAT 环境变量 → 仓库根 tomcat.home 一行文件。"""
    env = os.environ.get("SPORE_TOMCAT")
    if env:
        home = Path(env)
    else:
        marker = REPO / "tomcat.home"
        if not marker.is_file():
            sys.exit("缺 Tomcat 源：设环境变量 SPORE_TOMCAT，或在仓库根写一行 tomcat.home")
        home = Path(marker.read_text(encoding="utf-8").strip())
    if not (home / "bin" / "bootstrap.jar").is_file():
        sys.exit(f"{home} 不是 Tomcat 9 安装目录（缺 bin/bootstrap.jar）")
    return home


def main() -> int:
    ver = version()
    app = DIST / "Spore"
    if not (app / "Spore.exe").is_file():
        sys.exit(f"缺客户端产物：{app}（先跑 tools/build_exe.py 出 onedir 目录）")
    war = find_war(ver)
    tomcat = tomcat_home()
    schema = REPO / "docs" / "schema.sql"
    if not schema.is_file():
        sys.exit(f"缺建库脚本：{schema}")

    # 暂存 = 客户端 onedir 目录整体平铺进来（Spore.exe + _internal/），
    # war 必须与 Spore.exe 同目录——客户端按 exe 所在目录找后端（backend.war_dirs）
    staging = DIST / f"Spore-{ver}-win64"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(app, staging)
    shutil.copy2(war, staging / war.name)
    # 自带 Tomcat 9（只要跑起来必需的三件：bin/lib/conf；webapps/logs/temp/work
    # 由客户端首启在独立 CATALINA_BASE 里现建，端口那时才钉成 8080）。
    # ignore *.bat：出厂红线「zip 内无 .bat」——客户端直接 java … Bootstrap start
    # 拉起（spore_client/backend.py），Tomcat 自带的启动脚本用不上，打进包必撞红线。
    for sub in ("bin", "lib", "conf"):
        shutil.copytree(tomcat / sub, staging / "tomcat" / sub,
                        ignore=shutil.ignore_patterns("*.bat"))
    shutil.copy2(schema, staging / "schema.sql")
    for name in ("README.txt", "db.properties.example"):
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
