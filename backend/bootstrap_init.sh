#!/bin/bash
###############################################################################
# bootstrap_init.sh - One-time project setup script
# Run this once to initialize the development environment.
###############################################################################
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== GPU Scheduler - Project Initialization ==="

# 1. Create Python virtual environment
if [[ -d .venv ]]; then
    echo "[skip] .venv already exists"
else
    echo "[1/3] Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q --upgrade pip

# 2. Install dependencies
echo "[2/3] Installing Python dependencies..."
pip install -q -r requirements.txt

# 3. Create environment file if it doesn't exist
if [[ -f .env ]]; then
    echo "[skip] .env already exists"
else
    echo "[3/3] Creating .env template..."
    cat > .env << 'ENVEOF'
# Luchen Cloud credentials
LUCHEN_USERNAME=
LUCHEN_PASSWORD=
LUCHEN_IMAGE_ID=
LUCHEN_REGION_ID=
# Example Luchen instance type IDs (UUIDs from dashboard)
# LUCHEN_INSTANCE_TYPES={"A100": "uuid-a100", "H800": "uuid-h800", "RTX6090": "uuid-6090"}

# PPIO credentials
PPIO_API_KEY=
PPIO_BASE_URL=https://api.ppinfra.com/v3

# Callback URL (use ngrok URL during development)
CALLBACK_BASE_URL=http://localhost:9898
ENVEOF
    echo "Please edit .env with your credentials before starting."
fi

echo ""
echo "=== Done. Start the server with: ==="
echo "  source .venv/bin/activate"
echo "  cd backend && uvicorn main:app --reload --host 0.0.0.0 --port 9898"
