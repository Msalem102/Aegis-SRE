#!/usr/bin/env bash
# Aegis SRE - 1-Click Interactive Demo Launcher (macOS / Linux)
# Meta Global AI Developer Hackathon Submission

set -e

echo "==============================================================================="
echo "  AEGIS SRE: Autonomous Closed-Loop Site Reliability Engineering Agent"
echo "  Meta Global AI Developer Hackathon Submission"
echo "==============================================================================="
echo ""

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCKSTORE_DIR="$ROOT_DIR/mockStore"

# Locate mockStore
if [ ! -d "$MOCKSTORE_DIR" ]; then
    if [ -d "$ROOT_DIR/../mockStore" ]; then
        MOCKSTORE_DIR="$ROOT_DIR/../mockStore"
    else
        echo "Downloading demo microservice (mockStore)..."
        git clone https://github.com/ahmedharib/mockStore.git "$MOCKSTORE_DIR"
    fi
fi

# 0. First-Time Setup & Credentials Check
if [ ! -f "$ROOT_DIR/.env" ]; then
    echo "[0/4] Checking environment credentials..."
    echo "==============================================================================="
    echo "  [NOTICE: CREDENTIAL SETUP REQUIRED BEFORE RUNNING THE DEMO]"
    echo "  A '.env' configuration file was not found."
    echo "  Creating '.env' from '.env.example'..."
    cp "$ROOT_DIR/.env.example" "$ROOT_DIR/.env"
    echo ""
    echo "  Aegis SRE requires credentials in '.env' for live cloud execution:"
    echo "    * META_API_KEY       (Meta Muse Spark reasoning core)"
    echo "    * MODAL_TOKEN_ID     (Modal Cloud ephemeral micro-VM sandboxes)"
    echo "    * MODAL_TOKEN_SECRET (Modal Cloud authentication)"
    echo "    * GITHUB_TOKEN       (Atomic GitHub Pull Request delivery)"
    echo ""
    echo "  Please open '.env' in an editor and enter your credentials."
    echo "  (You can test your connection anytime with: python aegis_cli.py verify)"
    echo "==============================================================================="
    read -p "Press Enter once '.env' is configured to continue..."
else
    echo "[0/4] Environment configuration (.env) detected."
fi

# 1. Database Check
echo ""
echo "[1/4] Checking PostgreSQL simulation container..."
if docker start pg-sim >/dev/null 2>&1; then
    echo "      PostgreSQL container 'pg-sim' is active on localhost:5432."
else
    echo "      Notice: Docker container 'pg-sim' is standby or offline."
    echo "      Watchdog will engage automatically when database connection is online."
fi

# 2. Launch MockStore Backend on port 8000
echo ""
echo "[2/4] Launching Monitored Service (Cupertino Coffee Store) on http://localhost:8000..."
if [ -f "$MOCKSTORE_DIR/.venv/bin/python" ]; then
    MOCK_PY="$MOCKSTORE_DIR/.venv/bin/python"
elif [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    MOCK_PY="$ROOT_DIR/.venv/bin/python"
else
    MOCK_PY="python3"
fi

(cd "$MOCKSTORE_DIR" && "$MOCK_PY" server.py) &
MOCK_PID=$!

trap "kill $MOCK_PID 2>/dev/null || true" EXIT

# 3. Open Browser Tabs
echo ""
echo "[3/4] Opening Browser Windows..."
sleep 2
if command -v open >/dev/null 2>&1; then
    open "http://localhost:8000/" || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "http://localhost:8000/" || true
fi

# 4. Launch Aegis SRE on port 8080
echo ""
echo "[4/4] Starting Aegis SRE Web Dashboard on http://localhost:8080..."
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    AEGIS_PY="$ROOT_DIR/.venv/bin/python"
else
    AEGIS_PY="python3"
fi

"$AEGIS_PY" aegis_cli.py ui --config mockstore_aegis.yaml --port 8080
