#!/usr/bin/env bash
set -euo pipefail

# Backup and clean test data between test rounds
# Usage: ./scripts/backup-test-data.sh [backup_dir]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

BACKUP_DIR="${1:-$ROOT/test-backups}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"

echo "[backup] Creating backup at: $BACKUP_PATH"
mkdir -p "$BACKUP_PATH"

# 1. Backup Pasloe database (PostgreSQL dump)
echo "[backup] Dumping Pasloe PostgreSQL database..."
source ~/.config/containers/systemd/yoitsu/postgres.env 2>/dev/null || true
PG_HOST="${PG_HOST:-127.0.0.1}"
PG_PORT="${PG_PORT:-5432}"
PG_USER="${PG_USER:-yoitsu}"
PG_PASSWORD="${PG_PASSWORD:-yoitsu}"
PG_DB="${PG_DB:-pasloe}"

docker_exec="podman exec yoitsu-postgres"
if $docker_exec pg_isready -q 2>/dev/null; then
    $docker_exec pg_dump -U "$PG_USER" "$PG_DB" > "$BACKUP_PATH/pasloe-db.sql" 2>&1 || echo "[backup] pg_dump failed, continuing..."
    echo "[backup] Pasloe DB backed up: $(wc -l < "$BACKUP_PATH/pasloe-db.sql") lines"
else
    echo "[backup] PostgreSQL not reachable, skipping DB backup"
fi

# 2. Backup Trenni state volume
echo "[backup] Copying Trenni state volume..."
if podman volume exists yoitsu-dev-state 2>/dev/null; then
    podman volume export yoitsu-dev-state --output "$BACKUP_PATH/yoitsu-dev-state.tar" 2>&1 || echo "[backup] Volume export failed, continuing..."
    echo "[backup] Trenni state backed up: $(stat -c%s "$BACKUP_PATH/yoitsu-dev-state.tar" 2>/dev/null || echo 0) bytes"
fi

# 3. Backup Pasloe data volume
echo "[backup] Copying Pasloe data volume..."
if podman volume exists yoitsu-pasloe-data 2>/dev/null; then
    podman volume export yoitsu-pasloe-data --output "$BACKUP_PATH/yoitsu-pasloe-data.tar" 2>&1 || echo "[backup] Volume export failed, continuing..."
fi

# 4. Backup container logs (last N lines)
echo "[backup] Collecting service logs..."
mkdir -p "$BACKUP_PATH/logs"
journalctl --user -u yoitsu-postgres.service --no-pager -n 500 > "$BACKUP_PATH/logs/postgres.log" 2>/dev/null || true
journalctl --user -u yoitsu-pasloe.service --no-pager -n 500 > "$BACKUP_PATH/logs/pasloe.log" 2>/dev/null || true
journalctl --user -u yoitsu-trenni.service --no-pager -n 500 > "$BACKUP_PATH/logs/trenni.log" 2>/dev/null || true

# 5. Backup task execution summary
echo "[backup] Collecting task summary..."
source ~/.config/containers/systemd/yoitsu/trenni.env 2>/dev/null || true
curl -sf http://127.0.0.1:8100/control/status > "$BACKUP_PATH/status.json" 2>/dev/null || echo '{"error": "trenni not reachable"}' > "$BACKUP_PATH/status.json"
curl -sf "http://127.0.0.1:8000/events?limit=1000" -H "X-API-Key: ${PASLOE_API_KEY:-}" > "$BACKUP_PATH/events.json" 2>/dev/null || echo '{"events": []}' > "$BACKUP_PATH/events.json"

# 6. Create backup manifest
echo "[backup] Writing manifest..."
cat > "$BACKUP_PATH/manifest.json" <<EOF
{
    "timestamp": "$TIMESTAMP",
    "backup_path": "$BACKUP_PATH",
    "files": $(ls -1 "$BACKUP_PATH" | python3 -c 'import json,sys; print(json.dumps(list(sys.stdin.read().strip().split("\n"))))'),
    "yoitsu_commit": "$(cd "$ROOT" && git rev-parse HEAD 2>/dev/null || echo 'unknown')",
    "trenni_commit": "$(cd "$ROOT/trenni" && git rev-parse HEAD 2>/dev/null || echo 'unknown')",
    "palimpsest_commit": "$(cd "$ROOT/palimpsest" && git rev-parse HEAD 2>/dev/null || echo 'unknown')",
    "pasloe_commit": "$(cd "$ROOT/pasloe" && git rev-parse HEAD 2>/dev/null || echo 'unknown')"
}
EOF

echo "[backup] Backup complete: $BACKUP_PATH"
echo "[backup] Size: $(du -sh "$BACKUP_PATH" | cut -f1)"