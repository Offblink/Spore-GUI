@echo off
chcp 65001 >nul
rem Spore 开发版一键启动：只起客户端。后端由客户端自己用 target\spore-gui.war
rem 加仓库根 tomcat.home 指向的 Tomcat 9 拉起（无命令行窗口；退出客户端即停后端）。
rem 8080 上已经跑着**真的 Spore 应用**时，客户端探活通过就直接复用，不会重复起；
rem 端口被别的进程占着（例如 xerj）则不算复用，会在状态栏报端口冲突。
rem 前置：仓库根跑过 mvn clean package（否则客户端拿不到 war，会明确报错）。
setlocal
cd /d "%~dp0client"

if not exist ".venv\Scripts\pythonw.exe" (
  echo [ERR] 缺 client\.venv：先建开发 venv 再双击本脚本。
  exit /b 1
)

rem 客户端有单例管道：重复双击只会唤醒已在跑的那个，不会双开抢热键
start "" ".venv\Scripts\pythonw.exe" -m spore_client.main
exit /b 0
