@echo off
REM zeroAgent Windows hot update: rebuild + rolling restart API/web/admin
REM Double-click keeps the window open on exit so errors are visible.
REM author: Zhao Zhenming
REM date: 2026-09-07 11:57:38
setlocal EnableExtensions
title zeroAgent Docker Update
set "ERR=0"

cd /d "%~dp0.."
if errorlevel 1 (
  echo [deploy-update] ERROR: cannot cd to repo root "%~dp0.."
  set "ERR=1"
  goto :end
)

echo [deploy-update] repo: %CD%
echo [deploy-update] launching PowerShell...
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [deploy-update] ERROR: powershell.exe not found.
  set "ERR=9009"
  goto :end
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-update.ps1" %*
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [deploy-update] FAILED exit=%ERR%
  echo [deploy-update] Check: Docker Desktop running / base services up / build logs
  echo [deploy-update] Or run in a terminal:
  echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-update.ps1"
) else (
  echo [deploy-update] OK
)

:end
echo %CMDCMDLINE% | find /I "/c" >nul
if not errorlevel 1 (
  echo.
  pause
)
endlocal & exit /b %ERR%
