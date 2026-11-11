# ====================================================================
# CloudStore - PostgreSQL Pool Exhaustion Simulation Launcher
# ====================================================================

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  CloudStore: PostgreSQL Pool Starvation Simulation" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Docker status
Write-Host "[1/3] Checking Docker..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version
    Write-Host "  ✓ $dockerVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Docker is not running or not found in PATH." -ForegroundColor Red
    Write-Host "    Please start Docker Desktop and rerun this script." -ForegroundColor Yellow
}

# 2. Start PostgreSQL container
Write-Host "[2/3] Starting PostgreSQL container with connection limits..." -ForegroundColor Yellow
Write-Host "  (max_connections=25, idle_in_transaction_session_timeout=0)" -ForegroundColor Gray
docker compose up -d

Write-Host "  Waiting for database ready state..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# 3. Launch FastAPI backend
Write-Host "[3/3] Launching FastAPI Backend on http://localhost:8000..." -ForegroundColor Yellow
Write-Host "  Opening browser to Apple-designed UI..." -ForegroundColor Green
Start-Process "http://localhost:8000"

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}

& $pythonExe server.py
