"""出厂检查：发行 zip 的红线（口径见 skill spore-gui-release 步骤 6）。

用法（必须用构建 venv——脚本要读 exe 的 PYZ）：
    MSYS_NO_PATHCONV=1 cmd.exe /c ".venv-build\\Scripts\\python.exe tools\\factory_check.py"
（在 client/ 下跑；先跑过 tools/make_release_bundle.py）

红线（任一不过 → 退出码 1）：
1. zip 外层没有任何 .bat；
2. application-local.yml（真实 DB 口令文件）在任何层级都不许出现——
   含嵌套 jar 再钻一层（v1.1.1 就是 jar 内嵌它进了公开 release）；.example 模板除外；
3. 本机 application-local.yml 里的真实口令不出现在任何 entry 字节里；
   必须打印「待检口令 N 个」且 N>=1——N=0 = 基线没提取到 = 检查空转，按 FAIL 算；
4. 关键件抽查分两层（onedir 形态决定的，别混）：
   - 磁盘层 = zip 路径：_internal 里的资产/Qt/OCR 模型与原生件；
   - PYZ 层 = exe 内字节码：qrcode/markdown/keyboard/spore_client 这类纯 Python 包
     只活在 exe 的 PYZ 里，zip 路径上根本没有。拿 zip 子串凑数会撞
     dist-info、qtvirtualkeyboardplugin.dll 这类假阳性（2026-10-11 实测踩过）。

口令只在内存比对，绝不 print。路径一律用 Path / 分段拼（别写字面反斜杠）。
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
REPO = CLIENT.parent                                 # 仓库根
DIST = CLIENT / "dist"
LOCAL_YML = REPO / "src" / "main" / "resources" / "application-local.yml"

# 磁盘层标记：子串必须至少命中一条 zip entry 路径
DISK_MARKERS = (
    "_internal/",                  # onedir 结构本体
    "spore_client/assets/",         # 包内资产（图标等）真在磁盘上
    "icon-16.png",
    "icon-128.png",
    "PySide6",                      # Qt 原生件
)
# PYZ 层标记：纯 Python 包，只查 exe 内字节码（zip 路径上没有）
PYZ_MARKERS = ("qrcode", "markdown", "keyboard", "spore_client")


def version() -> str:
    text = (CLIENT / "spore_client" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not m:
        sys.exit("找不到 __version__")
    return m.group(1)


def extract_secrets() -> list[str]:
    """从本机口令文件提取所有 password 值（不回显）。"""
    if not LOCAL_YML.is_file():
        sys.exit(f"FAIL  读不到基线口令文件：{LOCAL_YML}（没基线 = 检查空转）")
    text = LOCAL_YML.read_text(encoding="utf-8")
    found = re.findall(r"(?im)^\s*[\w.-]*password\s*:\s*(.+?)\s*$", text)
    out: set[str] = set()
    for v in found:
        v = v.split(" #", 1)[0].strip().strip("'\"")   # 去行尾注释与引号
        if v and v != "CHANGE_ME":                     # 模板占位不算真口令
            out.add(v)
    return sorted(out)


def scan_bytes(data: bytes, secrets: list[bytes], where: str,
               depth: int, problems: list[str]) -> None:
    """扫一段字节：查口令、查 application-local.yml；jar 内再钻一层。"""
    base = where.rsplit("/", 1)[-1]
    if base.lower() == "application-local.yml":
        problems.append(f"发现 application-local.yml：{where}")
    for i, s in enumerate(secrets, 1):
        if s in data:
            problems.append(f"口令 #{i} 出现在 {where}")
    if depth < 4 and base.lower().endswith(".jar"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z2:
                for info2 in z2.infolist():
                    if info2.is_dir():
                        continue
                    scan_bytes(z2.read(info2), secrets,
                               f"{where}!/{info2.filename}", depth + 1, problems)
        except zipfile.BadZipFile:
            pass                            # 非 zip 的 .jar 直接跳过（没见过，不炸）


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

    secrets = [s.encode("utf-8") for s in extract_secrets()]
    print(f"待检口令 {len(secrets)} 个（来源 {LOCAL_YML.name}，只比对不回显）")
    if len(secrets) < 1:
        print("FAIL  待检口令 0 个：基线口令没提取到，检查会空转")
        return 1

    problems: list[str] = []
    paths: list[str] = []
    exe_bytes: bytes | None = None
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            name = info.filename
            paths.append(name)
            # 红线 1：外层不许有启动脚本
            if name.rsplit("/", 1)[-1].lower().endswith(".bat"):
                problems.append(f"zip 内有 .bat：{name}")
            data = z.read(info)
            if name.rsplit("/", 1)[-1].lower() == "spore.exe":
                exe_bytes = data
            # 红线 2 + 3：yml 与口令，逐 entry（jar 会钻进去）
            scan_bytes(data, secrets, name, 1, problems)

    # 红线 4a：磁盘层（zip 路径）
    missing = [m for m in DISK_MARKERS if not any(m in p for p in paths)]
    if not any("rapidocr" in p and p.lower().endswith(".onnx") for p in paths):
        missing.append("rapidocr/**/*.onnx（OCR 模型）")
    if not any("onnxruntime" in p and p.lower().endswith(".dll") for p in paths):
        missing.append("onnxruntime/**/*.dll（原生件）")

    # 红线 4b：PYZ 层（exe 内字节码）
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
