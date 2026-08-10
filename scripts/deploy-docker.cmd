@echo off
REM zeroAgent local Docker deploy: API :8000, web :3000, admin :3001
REM Double-click keeps the window open on exit so errors are visible.
REM author: Zhao Zhenming
REM date: 2026-08-10
setlocal EnableExtensions
title zeroAgent Docker Deploy
set "ERR=0"

cd /d "%~dp0.."
if errorlevel 1 (
  echo [deploy-docker] ERROR: cannot cd to repo root "%~dp0.."
  set "ERR=1"
  goto :end
)

echo [deploy-docker] repo: %CD%
echo [deploy-docker] launching PowerShell...
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 (
  echo [deploy-docker] ERROR: powershell.exe not found.
  set "ERR=9009"
  goto :end
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-docker.ps1" %*
set "ERR=%ERRORLEVEL%"

echo.
if not "%ERR%"=="0" (
  echo [deploy-docker] FAILED exit=%ERR%
  echo [deploy-docker] Check: Docker Desktop running / ports free / build logs
  echo [deploy-docker] Or run in a terminal:
  echo   powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy-docker.ps1"
) else (
  echo [deploy-docker] OK
)

:end
echo %CMDCMDLINE% | find /I "/c" >nul
if not errorlevel 1 (
  echo.
  pause
)
endlocal & exit /b %ERR%