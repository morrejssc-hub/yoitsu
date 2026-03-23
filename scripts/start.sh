#!/usr/bin/env bash
# DEPRECATED: Use `uv run yoitsu up` for local service startup or
# `./scripts/deploy-quadlet.sh` for Quadlet deployment.
# This script is kept for reference only.
# start.sh — Start Pasloe + Trenni for a Yoitsu test run
# Usage: OPENAI_API_KEY=sk-xxx ./start.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

export PASLOE_API_KEY="yoitsu-test-key-2026"

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: OPENAI_API_KEY is not set" >&2
    exit 1
fi

# ── Start Pasloe ──────────────────────────────────────────────────────
echo "[start] Starting Pasloe on :8000..."
cd "$ROOT/pasloe"
uv run uvicorn src.pasloe.app:app --host 127.0.0.1 --port 8000 \
    > "$ROOT/pasloe.log" 2>&1 &
PASLOE_PID=$!
echo "[start] Pasloe PID=$PASLOE_PID"

# Wait for Pasloe to be ready
echo -n "[start] Waiting for Pasloe..."
for i in $(seq 1 20); do
    if curl -sf -H "X-API-Key: yoitsu-test-key-2026" \
            "http://localhost:8000/events?limit=1" > /dev/null 2>&1; then
        echo " OK"
        break
    fi
    echo -n "."
    sleep 0.5
done

# ── Start Trenni ──────────────────────────────────────────────────────
echo "[start] Starting Trenni on :8100..."
cd "$ROOT/trenni"
uv run trenni start -c "$ROOT/config/trenni.yaml" \
    > "$ROOT/trenni.log" 2>&1 &
TRENNI_PID=$!
echo "[start] Trenni PID=$TRENNI_PID"

echo ""
echo "Services started. PIDs: pasloe=$PASLOE_PID trenni=$TRENNI_PID"
echo ""
echo "Next steps:"
echo "  Submit tasks:  python3 $SCRIPT_DIR/submit-tasks.py"
echo "  Monitor:       python3 $SCRIPT_DIR/monitor.py --hours 5"
echo "  Quadlet:       $SCRIPT_DIR/deploy-quadlet.sh"
echo "  Pasloe UI:     http://localhost:8000/ui"
echo "  Trenni status: http://localhost:8100/status"
echo "  Logs:          tail -f $ROOT/pasloe.log $ROOT/trenni.log"
