# -*- mode: python ; coding: utf-8 -*-
"""Spore 客户端打包配方（onefile + windowed）。

构建（必须用干净构建 venv `.venv-build`——开发 venv 是 --system-site-packages，
会把全局 PyQt5 版 qfluentwidgets / torch 拖进包里，见 skill windows-packaging）：

    .venv-build/Scripts/python.exe -m PyInstaller Spore.spec --noconfirm --clean

或直接 `python tools/build_exe.py`（含图标生成、自检与 sha256）。
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)                      # = client/
ICON = str(ROOT / "assets" / "app.ico")
ASSETS = str(ROOT / "spore_client" / "assets")

# AI 建议框（2026-10-08）：RapidOCR 离线识别要整包进——
# 模型 *.onnx 是包内数据、onnxruntime/cv2 原生件是动态库，漏一个开开关就崩
ml_datas, ml_binaries, ml_hidden = collect_all("rapidocr")
onnx_datas, onnx_binaries, onnx_hidden = collect_all("onnxruntime")
cv_datas, cv_binaries, cv_hidden = collect_all("cv2")

a = Analysis(
    [str(ROOT / "tools" / "frozen" / "Spore.py")],
    pathex=[str(ROOT)],
    binaries=ml_binaries + onnx_binaries + cv_binaries,
    # 包内图标（app_icon.py 用 __file__ 找 assets/，冻结后要同相对深度）
    datas=[(ASSETS, "spore_client/assets")] + ml_datas + onnx_datas + cv_datas,
    # 懒加载/间接引用，静态分析可能漏（qrcode、PIL 子模块、全局热键库）
    hiddenimports=["qrcode", "PIL.ImageDraw", "PIL.ImageGrab", "keyboard"]
    + ml_hidden + onnx_hidden + cv_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # pkg_resources 冻结后要 jaraco.text，import 即崩（打包纪律第一条）
        "pkg_resources", "setuptools", "jaraco", "pip", "_distutils_hack",
        "tkinter", "unittest", "pydoc", "test",
        # 另一套 Qt 绑定绝不进包
        "PyQt5", "PyQt6", "PySide2",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Spore",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI 应用：没有 stdout，靠日志排查
    disable_windowed_traceback=False,
    icon=ICON,
)
