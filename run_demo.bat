@echo off
setlocal enabledelayedexpansion
title Aegis SRE - 1-Click Interactive Demo

echo ===============================================================================
echo   🛡️  AEGIS SRE: Autonomous Closed-Loop Site Reliability Engineering Agent
echo   Meta Global AI Developer Hackathon Submission
echo ===============================================================================
echo.

set "ROOT_DIR=%~dp0"
set "MOCKSTORE_DIR=%ROOT_DIR%..\mockStore"

:: 1. Database Check
echo [1/4] Checking PostgreSQL simulation container...
docker start pg-sim >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo       PostgreSQL container 'pg-sim' is active on localhost:5432.
) else (
    echo       Notice: Docker container 'pg-sim' standby or offline.
    echo       (Watchdog will auto-engage when database connection is online).
)

:: 2. Launch MockStore Backend on port 8000
echo.
echo [2/4] Launching Monitored Service (Cupertino Coffee Store) on http://localhost:8000...
if exist "%MOCKSTORE_DIR%\.venv\Scripts\python.exe" (
    set "MOCK_PY=%MOCKSTORE_DIR%\.venv\Scripts\python.exe"
) else (
    set "MOCK_PY=python"
)

start "Cupertino Coffee Store (:8000)" cmd /k "cd /d "%MOCKSTORE_DIR%" && "%MOCK_PY%" server.py"

:: 3. Open Browser Tabs
echo.
echo [3/4] Opening Browser Windows...
timeout /t 2 /nobreak >nul
start http://localhost:8000/

:: 4. Launch Aegis SRE Control Plane on port 8080
echo.
echo [4/4] Starting Aegis SRE Web Dashboard on http://localhost:8080...
if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    set "AEGIS_PY=%ROOT_DIR%.venv\Scripts\python.exe"
) else (
    set "AEGIS_PY=python"
)

"%AEGIS_PY%" aegis_cli.py ui --config mockstore_aegis.yaml --port 8080
