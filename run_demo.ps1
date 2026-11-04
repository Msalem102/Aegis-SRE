# Aegis SRE - 1-Click Interactive Demo Launcher (PowerShell)
# Meta Global AI Developer Hackathon Submission

Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  🛡️  AEGIS SRE: Autonomous Closed-Loop Site Reliability Engineering Agent" -ForegroundColor White
Write-Host "  Meta Global AI Developer Hackathon Submission" -ForegroundColor DarkCyan
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MockStoreDir = Join-Path (Split-Path -Parent $RootDir) "mockStore"

# 1. Database Check
Write-Host "[1/4] Checking PostgreSQL simulation container..." -ForegroundColor Yellow
try {
    $dockerRes = docker start pg-sim 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "      PostgreSQL container 'pg-sim' is active on localhost:5432." -ForegroundColor Green
    } else {
        Write-Host "      Notice: Docker container 'pg-sim' standby or offline." -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "      Notice: Docker not reachable. Telemetry will fallback to simulated/in-memory mode." -ForegroundColor DarkYellow
}

# 2. Launch MockStore on port 8000
Write-Host "`n[2/4] Launching Monitored Service (Cupertino Coffee Store) on http://localhost:8000..." -ForegroundColor Yellow
$MockPy = Join-Path $MockStoreDir ".venv\Scripts\python.exe"
if (-not (Test-Path $MockPy)) { $MockPy = "python" }

Start-Process cmd.exe -ArgumentList "/k cd /d `"$MockStoreDir`" && `"$MockPy`" server.py" -WindowStyle Normal

# 3. Open Browser Tabs
Write-Host "`n[3/4] Opening Browser Windows..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
Start-Process "http://localhost:8000/"

# 4. Launch Aegis SRE UI on port 8080
Write-Host "`n[4/4] Starting Aegis SRE Web Dashboard on http://localhost:8080..." -ForegroundColor Yellow
$AegisPy = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $AegisPy)) { $AegisPy = "python" }

& $AegisPy aegis_cli.py ui --config mockstore_aegis.yaml --port 8080
