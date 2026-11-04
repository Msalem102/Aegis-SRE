@echo off
echo ========================================================
echo   CloudStore - PostgreSQL Pool Exhaustion Simulation
echo ========================================================
echo.

echo [1/3] Starting PostgreSQL container (max_connections=25)...
docker compose up -d

echo [2/3] Waiting for PostgreSQL to be ready...
timeout /t 3 /nobreak >nul

echo [3/3] Launching FastAPI Backend on http://localhost:8000...
echo Opening browser...
start http://localhost:8000

.\.venv\Scripts\python.exe server.py
