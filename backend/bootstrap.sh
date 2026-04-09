#!/bin/bash
###############################################################################
# bootstrap.sh - Instance initialization script
# Injected via cloud provider's initScript field at create time.
# Runs as root inside the newly provisioned VM/container.
###############################################################################
set -euo pipefail

# ---- Phase 0: Environment ---------------------------------------------------
INSTANCE_ID="${INSTANCE_ID:-unknown}"
CALLBACK_URL="${CALLBACK_URL:-http://localhost:9898/api/callback}"
LOG_FILE="/var/log/bootstrap.log"
BENCHMARK_RESULT="/var/log/benchmark.json"

log() {
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[$ts] $*" | tee -a "$LOG_FILE"
}

callback() {
    local status="$1"
    local benchmark_json="$2"  # empty string if not yet available
    if [[ -n "$benchmark_json" ]]; then
        payload="{\"instance_id\":\"${INSTANCE_ID}\",\"status\":\"${status}\",\"benchmark\":${benchmark_json}}"
    else
        payload="{\"instance_id\":\"${INSTANCE_ID}\",\"status\":\"${status}\"}"
    fi
    curl -sf -X POST "${CALLBACK_URL}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        --max-time 10 || true
}

log "=== Bootstrap started for instance ${INSTANCE_ID} ==="

# ---- Phase 1: Validate GPU driver -------------------------------------------
log "[Phase 1] Validating GPU driver..."
if ! command -v nvidia-smi &>/dev/null; then
    log "ERROR: nvidia-smi not found"
    callback "failed" ""
    exit 1
fi
nvidia-smi 2>&1 | tee -a "$LOG_FILE"
log "[Phase 1] GPU driver OK"

# ---- Phase 2: Install base tools --------------------------------------------
log "[Phase 2] Installing base tools..."
apt-get update -qq
apt-get install -y -qq nodejs npm curl jq fio iperf3 >/dev/null 2>&1 || true

# Install s5cmd for S3 operations
if ! command -v s5cmd &>/dev/null; then
    S5CMD_VER="2.3.0"
    S5CMD_OS="Linux"
    S5CMD_ARCH="arm64"
    if [[ "$(uname -m)" == "x86_64" ]]; then S5CMD_ARCH="64bit"; fi
    curl -sfL "https://github.com/peak/s5cmd/releases/download/v${S5CMD_VER}/s5cmd_${S5CMD_VER}_${S5CMD_OS}_${S5CMD_ARCH}.tar.gz" \
        -o /tmp/s5cmd.tar.gz 2>/dev/null || true
    if [[ -f /tmp/s5cmd.tar.gz ]]; then
        tar -xzf /tmp/s5cmd.tar.gz -C /usr/local/bin s5cmd 2>/dev/null || true
    fi
fi

log "[Phase 2] Base tools installed"

# ---- Phase 2b: Install proxy client (for GFW bypass) ----------------------
log "[Phase 2b] Setting up  proxy..."
HTTP_PROXY_URL="${HTTP_PROXY_URL:-}"  # e.g. http://127.0.0.1:7890
HTTP_CONFIG_JSON="${HTTP_CONFIG_JSON:-}"  # optional: full config JSON string
# todo: install proxy client...

# ---- Phase 3: Install Codex CLI + Claude Code CLI ---------------------------
log "[Phase 3] Installing Codex CLI and Claude Code CLI..."

# Codex CLI
if ! command -v codex &>/dev/null; then
    npm install -g @openai/codex 2>/dev/null || log "WARN: Codex CLI install failed"
fi

# Claude Code CLI
if ! command -v claude &>/dev/null; then
    npm install -g @anthropic-ai/claude-code 2>/dev/null || log "WARN: Claude Code install failed"
fi

log "[Phase 3] Codex CLI / Claude Code CLI done"

# ---- Phase 4: S3 mount + data pull (async, non-blocking) --------------------
log "[Phase 4] Starting S3 data pull (async)..."
(
    S3_BUCKET="${S3_BUCKET:-}"
    S3_ENDPOINT="${S3_ENDPOINT:-}"
    S3_ACCESS_KEY="${S3_ACCESS_KEY:-}"
    S3_SECRET_KEY="${S3_SECRET_KEY:-}"

    if [[ -z "$S3_BUCKET" ]] || ! command -v s5cmd &>/dev/null; then
        log "[Phase 4] S3 not configured or s5cmd not available, skipping"
        exit 0
    fi

    export AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY"
    export AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY"
    if [[ -n "$S3_ENDPOINT" ]]; then
        S5CMD_EP="--endpoint-url ${S3_ENDPOINT}"
    fi

    mkdir -p /data/fine-web-edu
    s5cmd $S5CMD_EP cp --concurrency 8 "s3://${S3_BUCKET}/CC-MAIN-2013-20/" "/data/fine-web-edu/" \
        2>> "$LOG_FILE" || log "[Phase 4] Data download failed"

    log "[Phase 4] S3 data pull complete"
) &
# Do not wait - continue to benchmark

# ---- Phase 5: Run benchmark -------------------------------------------------
log "[Phase 5] Running benchmark..."
BENCHMARK_JSON=""
if [[ -f /opt/gpu-scheduler/benchmark.py ]]; then
    cd /opt/gpu-scheduler
    BENCHMARK_JSON=$(python3 benchmark.py 2>> "$LOG_FILE") || true
    if [[ -n "$BENCHMARK_JSON" ]]; then
        echo "$BENCHMARK_JSON" > "$BENCHMARK_RESULT"
        log "[Phase 5] Benchmark complete"
    else
        log "[Phase 5] Benchmark returned empty result"
    fi
else
    log "[Phase 5] benchmark.py not found at /opt/gpu-scheduler/benchmark.py, skipping"
fi

# ---- Phase 6: Start Telemetry Agent -----------------------------------------
log "[Phase 6] Starting Telemetry Agent..."
if [[ -f /opt/gpu-scheduler/telemetry_agent.py ]]; then
    nohup python3 /opt/gpu-scheduler/telemetry_agent.py \
        --instance-id "${INSTANCE_ID}" \
        >> /var/log/telemetry.log 2>&1 &
    log "[Phase 6] Telemetry Agent started (PID $!)"
else
    log "[Phase 6] Telemetry Agent script not found, skipping"
fi

# ---- Phase 7: Callback ------------------------------------------------------
log "[Phase 7] Sending callback (status=ready)..."
callback "ready" "$BENCHMARK_JSON"

log "=== Bootstrap complete ==="
