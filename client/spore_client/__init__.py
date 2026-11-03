"""Spore 桌面客户端（PySide6 + Fluent）。

架构（2026-10-02 用户拍板换栈）：本包只做 UI + REST 调用，
后端是同仓库的严格 SSM war（客户端用自带 Tomcat 9 起在 :8080），评分主体在后端。
"""

# 全仓唯一版本号（构建/发版脚本从这里读，见 tools/build_exe.py）
__version__ = "1.4.0"
