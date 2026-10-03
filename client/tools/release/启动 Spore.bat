@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ---- 1) 找 Java：优先课设口径的 JDK8，找不到就用 PATH 上的 java ----
set "JAVA=%ProgramFiles%\Java\jdk-1.8\bin\java.exe"
if not exist "%JAVA%" set "JAVA=java"

rem ---- 2) 数据库口令文件必须先准备好 ----
if not exist "application-local.yml" (
  echo [提示] 缺 application-local.yml：请复制 application-local.yml.example
  echo         为 application-local.yml，填上你的 MySQL 账号口令后重试。
  pause
  exit /b 1
)

rem ---- 3) 后端：8080 已在监听就跳过 ----
netstat -an | findstr ":8080" | findstr LISTENING >nul
if not errorlevel 1 goto client
start "Spore 后端" /min "%JAVA%" -jar spore-backend-1.0.0.jar

rem ---- 等 8080 就绪（最多 60 秒）----
set /a n=0
:wait
timeout /t 1 /nobreak >nul
netstat -an | findstr ":8080" | findstr LISTENING >nul
if not errorlevel 1 goto client
set /a n+=1
if %n% lss 60 goto wait
echo [警告] 后端 60 秒内未就绪，仍尝试启动客户端（先看后端窗口的报错）。

:client
start "" "Spore.exe"
exit /b 0
