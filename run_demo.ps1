# Aegis SRE - 1-Click Interactive Demo Launcher (PowerShell)
# Meta Global AI Developer Hackathon Submission

Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "  AEGIS SRE: Autonomous Closed-Loop Site Reliability Engineering Agent" -ForegroundColor White
Write-Host "  Meta Global AI Developer Hackathon Submission" -ForegroundColor DarkCyan
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Locate mockStore
$MockStoreDir = Join-Path $RootDir "mockStore"
if (-not (Test-Path $MockStoreDir)) {
    $SiblingDir = Join-Path (Split-Path -Parent $RootDir) "mockStore"
    if (Test-Path $SiblingDir) {
        $MockStoreDir = $SiblingDir
    } else {
        Write-Host "Downloading demo microservice (mockStore)..." -ForegroundColor Yellow
        git clone https://github.com/ahmedharib/mockStore.git $MockStoreDir
    }
}

# 0. First-Time Setup & Credentials Check
$EnvFile = Join-Path $RootDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "[0/4] Checking environment credentials..." -ForegroundColor Yellow
    Write-Host "===============================================================================" -ForegroundColor Yellow
    Write-Host "  [NOTICE: CREDENTIAL SETUP REQUIRED BEFORE RUNNING THE DEMO]" -ForegroundColor White
    Write-Host "  A '.env' configuration file was not found." -ForegroundColor DarkYellow
    Write-Host "  Creating '.env' from '.env.example'..." -ForegroundColor DarkYellow
    Copy-Item (Join-Path $RootDir ".env.example") $EnvFile
    Write-Host "`n  Aegis SRE requires credentials in '.env' for live cloud execution:" -ForegroundColor White
    Write-Host "    * META_API_KEY       (Meta Muse Spark reasoning core)" -ForegroundColor Cyan
    Write-Host "    * MODAL_TOKEN_ID     (Modal Cloud ephemeral micro-VM sandboxes)" -ForegroundColor Cyan
    Write-Host "    * MODAL_TOKEN_SECRET (Modal Cloud authentication)" -ForegroundColor Cyan
    Write-Host "    * GITHUB_TOKEN       (Atomic GitHub Pull Request delivery)" -ForegroundColor Cyan
    Write-Host "`n  Please open '.env' in an editor and enter your credentials." -ForegroundColor White
    Write-Host "  (You can test your connection anytime with: python aegis_cli.py verify)" -ForegroundColor DarkGray
    Write-Host "===============================================================================" -ForegroundColor Yellow
    Read-Host "Press Enter once '.env' is configured to continue"
} else {
    Write-Host "[0/4] Environment configuration (.env) detected." -ForegroundColor Green
}

# 1. Database Check
Write-Host "`n[1/4] Checking PostgreSQL simulation container..." -ForegroundColor Yellow
try {
    $dockerRes = docker start pg-sim 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "      PostgreSQL container 'pg-sim' is active on localhost:5432." -ForegroundColor Green
    } else {
        Write-Host "      Notice: Docker container 'pg-sim' is standby or offline." -ForegroundColor DarkYellow
        Write-Host "      Watchdog will engage automatically when database connection is online." -ForegroundColor DarkGray
    }
} catch {
    Write-Host "      Notice: Docker not reachable. Telemetry will fallback to simulated/in-memory mode." -ForegroundColor DarkYellow
}

# 2. Launch MockStore on port 8000
Write-Host "`n[2/4] Launching Monitored Service (Cupertino Coffee Store) on http://localhost:8000..." -ForegroundColor Yellow
$MockPy = Join-Path $MockStoreDir ".venv\Scripts\python.exe"
if (-not (Test-Path $MockPy)) {
    $RootPy = Join-Path $RootDir ".venv\Scripts\python.exe"
    if (Test-Path $RootPy) {
        $MockPy = $RootPy
    } else {
        $MockPy = "python"
    }
}

Start-Process cmd.exe -ArgumentList "/c cd /d `"$MockStoreDir`" && `"$MockPy`" server.py" -WindowStyle Normal

# 3. Open Browser Tabs
Write-Host "`n[3/4] Opening Browser Windows..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
Start-Process "http://localhost:8000/"

# 4. Launch Aegis SRE UI on port 8080
Write-Host "`n[4/4] Starting Aegis SRE Web Dashboard on http://localhost:8080..." -ForegroundColor Yellow
$AegisPy = Join-Path $RootDir ".venv\Scripts\python.exe"
if (-not (Test-Path $AegisPy)) { $AegisPy = "python" }

& $AegisPy aegis_cli.py ui --config mockstore_aegis.yaml --port 8080
