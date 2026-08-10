@echo off
REM zeroAgent 一键重启前端入口（员工端 :3000 / 管理端 :3001）
REM @author 赵振明
REM @date 2026-08-03 09:32:59
cd /d "%~dp0\.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart-frontends.ps1" %*
exit /b %ERRORLEVEL%
