@echo off
REM zeroAgent 本地一键重启入口（固定后端 :8000 / 前端 :3000）
REM @author 赵振明
REM @date 2026-07-28 11:17:13
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-dev.ps1" %*
exit /b %ERRORLEVEL%
