@echo off
rem One-click launcher for Spore: backend (skip if already up) + client (skip if running).
rem cmd shell + embedded PowerShell; see skill single-file-bat-embedding-powershell.
setlocal
set "wp_self=%~f0"
set "wp_tmp=%TEMP%\tool-%RANDOM%%RANDOM%.ps1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:wp_self); $i=$t.IndexOf('#:PS'+'1#'); if($i -lt 0){exit 9}; $t=$t.Substring($t.IndexOf([char]10,$i)+1); if(-not $t.Contains('function Start-SporeAll')){exit 9}; [IO.File]::WriteAllText($env:wp_tmp,$t,(New-Object Text.UTF8Encoding $true))"
if errorlevel 1 (
  echo [ERROR] failed to extract the embedded PowerShell part from "%~f0"
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%wp_tmp%" %*
set wp_rc=%errorlevel%
del "%wp_tmp%" >nul 2>&1

rem pause only on double-click: cmdcmdline contains this filename
echo %cmdcmdline% | find /i "%~nx0" >nul && pause
exit /b %wp_rc%

#:PS1#
<#
.SYNOPSIS
  Spore 一键启动：后端（已在跑则跳过）+ 客户端（已在跑则跳过），可重复双击不打架。
.DESCRIPTION
  后端 = mvn spring-boot:run（最小化 cmd 窗口；关那个窗口 = 停后端）。
  客户端 = client/.venv pythonw -m spore_client.main（GUI 关窗即退，热键随之注销）。
  JAVA_HOME 钉死 jdk-1.8（本机课设口径，别让系统默认 JDK 混进来）。
#>
[CmdletBinding()]
param()

function Test-Port([int]$Port) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $ok = $c.ConnectAsync('127.0.0.1', $Port).Wait(1500)
        $c.Close()
        return $ok
    } catch { return $false }
}

function Start-SporeAll {
    $root = Split-Path -Parent $env:wp_self
    $clientDir = Join-Path $root 'client'
    $pythonw = Join-Path $clientDir '.venv\Scripts\pythonw.exe'

    # ---- 1) 后端：8080 已监听就跳过（重复双击不报端口冲突） ----
    if (Test-Port 8080) {
        Write-Host '[1/2] 后端已在 8080 监听，跳过启动。'
    } else {
        Write-Host '[1/2] 启动后端 mvn spring-boot:run（最小化窗口；关它=停后端）...'
        $env:JAVA_HOME = 'C:\Program Files\Java\jdk-1.8'
        try {
            Start-Process -FilePath 'cmd.exe' -ArgumentList '/k', 'mvn spring-boot:run' `
                -WorkingDirectory $root -WindowStyle Minimized
        } catch {
            Write-Host "[ERR] 后端启动失败：$($_.Exception.Message)"
            exit 1
        }
        $deadline = (Get-Date).AddSeconds(120)
        while (-not (Test-Port 8080)) {
            if ((Get-Date) -gt $deadline) {
                Write-Host '[ERR] 后端 120 秒仍未监听 8080 —— 去任务栏找最小化的 cmd 窗口看报错。'
                exit 1
            }
            Start-Sleep -Seconds 2
        }
        Write-Host '       后端就绪。'
    }

    # ---- 2) 客户端：已在跑就跳过（双开会让 Alt+S/Alt+Z 热键重复响应） ----
    $running = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*spore_client*' }
    if ($running) {
        Write-Host '[2/2] 客户端已在运行，跳过。'
    } else {
        if (-not (Test-Path $pythonw)) {
            Write-Host "[ERR] 找不到 venv pythonw：$pythonw"
            exit 1
        }
        Write-Host '[2/2] 启动客户端...'
        try {
            Start-Process -FilePath $pythonw -ArgumentList '-m', 'spore_client.main' `
                -WorkingDirectory $clientDir
        } catch {
            Write-Host "[ERR] 客户端启动失败：$($_.Exception.Message)"
            exit 1
        }
    }

    Write-Host '完成。快捷键：Alt+S 截屏作答，Alt+Z 呼出回答面板。'
    exit 0
}

Start-SporeAll
