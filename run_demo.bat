@echo off
setlocal
title Aegis SRE - 1-Click Interactive Demo

echo ===============================================================================
echo   AEGIS SRE: Autonomous Closed-Loop Site Reliability Engineering Agent
echo   Meta Global AI Developer Hackathon Submission
echo ===============================================================================
echo.

set "ROOT_DIR=%~dp0"

:: Locate mockStore
if exist "%ROOT_DIR%mockStore" (
    set "MOCKSTORE_DIR=%ROOT_DIR%mockStore"
) else if exist "%ROOT_DIR%..\mockStore" (
    set "MOCKSTORE_DIR=%ROOT_DIR%..\mockStore"
) else (
    echo Downloading demo microservice (mockStore)...
    git clone https://github.com/ahmedharib/mockStore.git "%ROOT_DIR%mockStore"
    set "MOCKSTORE_DIR=%ROOT_DIR%mockStore"
)

:: 0. First-Time Setup & Credentials Check
if not exist "%ROOT_DIR%.env" (
    echo [0/4] Checking environment credentials...
    echo ===============================================================================
    echo   [NOTICE: CREDENTIAL SETUP REQUIRED BEFORE RUNNING THE DEMO]
    echo   A '.env' configuration file was not found.
    echo   Creating '.env' from '.env.example'...
    copy "%ROOT_DIR%.env.example" "%ROOT_DIR%.env" >nul
    echo.
    echo   Aegis SRE requires credentials in '.env' for live cloud execution:
    echo     * META_API_KEY       (Meta Muse Spark reasoning core)
    echo     * MODAL_TOKEN_ID     (Modal Cloud ephemeral micro-VM sandboxes)
    echo     * MODAL_TOKEN_SECRET (Modal Cloud authentication)
    echo     * GITHUB_TOKEN       (Atomic GitHub Pull Request delivery)
    echo.
    echo   Please open '.env' in an editor and enter your credentials.
    echo   (You can test your connection anytime with: python aegis_cli.py verify)
    echo ===============================================================================
    echo Press any key to continue once '.env' is configured...
    pause >nul
) else (
    echo [0/4] Environment configuration (.env) detected.
)

:: 1. Database Check
echo [1/4] Checking PostgreSQL simulation container...
docker start pg-sim >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo       PostgreSQL container 'pg-sim' is active on localhost:5432.
) else (
    echo       Notice: Docker container 'pg-sim' is standby or offline.
    echo       Watchdog will engage automatically when database connection is online.
)

:: 2. Launch MockStore Backend on port 8000
echo.
echo [2/4] Launching Monitored Service (Cupertino Coffee Store) on http://localhost:8000...
if exist "%MOCKSTORE_DIR%\.venv\Scripts\python.exe" (
    set "MOCK_PY=%MOCKSTORE_DIR%\.venv\Scripts\python.exe"
) else if exist "%ROOT_DIR%.venv\Scripts\python.exe" (
    set "MOCK_PY=%ROOT_DIR%.venv\Scripts\python.exe"
) else (
    set "MOCK_PY=python"
)

start "Cupertino Coffee Store (:8000)" cmd /c "cd /d %MOCKSTORE_DIR% && %MOCK_PY% server.py"

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
