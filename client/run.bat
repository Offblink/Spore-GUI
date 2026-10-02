@echo off
chcp 65001 >nul
start "" /d "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -m spore_client.main
