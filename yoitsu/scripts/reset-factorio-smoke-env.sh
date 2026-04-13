#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

FACTORIO_BIN="${FACTORIO_BIN:-/home/holo/factorio/bin/x64/factorio}"
FACTORIO_ROOT="${FACTORIO_ROOT:-/home/holo/factorio}"
FACTORIO_CONFIG_DIR="${FACTORIO_CONFIG_DIR:-/home/holo/factorio/config}"
FACTORIO_MAP_GEN_SETTINGS="${FACTORIO_MAP_GEN_SETTINGS:-/home/holo/factorio-agent/config/map-gen-settings.json}"
RCON_PORT="${RCON_PORT:-27015}"
RCON_PASSWORD="${RCON_PASSWORD:-changeme}"
SAVE_PATH="${SAVE_PATH:-$FACTORIO_ROOT/saves/yoitsu-clean-$(date +%Y%m%d-%H%M%S).zip}"
LOG_PATH="${LOG_PATH:-$FACTORIO_ROOT/factorio-current.log}"

if [[ ! -x "$FACTORIO_BIN" ]]; then
    echo "[factorio-smoke-reset] missing factorio binary: $FACTORIO_BIN" >&2
    exit 1
fi

if [[ ! -f "$FACTORIO_MAP_GEN_SETTINGS" ]]; then
    echo "[factorio-smoke-reset] missing map gen settings: $FACTORIO_MAP_GEN_SETTINGS" >&2
    exit 1
fi

echo "[factorio-smoke-reset] Stopping running Factorio process (if any)..."
pkill -f '/home/holo/factorio/bin/x64/factorio --start-server' 2>/dev/null || true
sleep 3

echo "[factorio-smoke-reset] Cleaning Yoitsu runtime state..."
# Equivalent to: cleanup-test-data.sh --skip-backup
bash "$ROOT/scripts/cleanup-test-data.sh" --skip-backup

echo "[factorio-smoke-reset] Rebuilding job image without cache..."
# Equivalent to: build-job-image.sh --no-cache
bash "$ROOT/scripts/build-job-image.sh" --no-cache

echo "[factorio-smoke-reset] Redeploying quadlet services..."
# Equivalent to: deploy-quadlet.sh --skip-build
bash "$ROOT/scripts/deploy-quadlet.sh" --skip-build

echo "[factorio-smoke-reset] Waiting for services to stabilize..."
sleep 20

echo "[factorio-smoke-reset] Creating fresh save: $SAVE_PATH"
mkdir -p "$(dirname "$SAVE_PATH")"
"$FACTORIO_BIN" --create "$SAVE_PATH" --map-gen-settings "$FACTORIO_MAP_GEN_SETTINGS"

echo "[factorio-smoke-reset] Starting Factorio with fresh save..."
nohup "$FACTORIO_BIN" \
  --start-server "$SAVE_PATH" \
  --server-settings "$FACTORIO_CONFIG_DIR/server-settings.json" \
  --rcon-port "$RCON_PORT" \
  --rcon-password "$RCON_PASSWORD" \
  >"$LOG_PATH" 2>&1 &

for i in $(seq 1 30); do
    if ss -ltnp | grep -q ":$RCON_PORT"; then
        break
    fi
    sleep 1
done

echo "[factorio-smoke-reset] Ready"
echo "[factorio-smoke-reset] save=$SAVE_PATH"
echo "[factorio-smoke-reset] log=$LOG_PATH"
