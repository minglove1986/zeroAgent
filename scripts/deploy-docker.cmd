@echo off
REM zeroAgent one-click Docker deploy (API fixed :8000)
REM @author 赵振明
REM @date 2026-07-28 15:29:36
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-docker.ps1" %*
exit /b %ERRORLEVEL%
