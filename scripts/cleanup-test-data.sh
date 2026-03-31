#!/usr/bin/env bash
set -euo pipefail

# Clean test data after backup
# Usage: ./scripts/cleanup-test-data.sh [--skip-backup]
# Recommended: Run backup-test-data.sh first, then cleanup

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

SKIP_BACKUP="${1:-}" == "--skip-backup"
FORCE="${FORCE:-0}"

if [[ "$SKIP_BACKUP" != "--skip-backup" && "$FORCE" != "1" ]]; then
    # Check if backup exists today
    TODAY="$(date +%Y%m%d)"
    BACKUP_DIR="$ROOT/test-backups"
    if [[ ! -d "$BACKUP_DIR" ]]; then
        echo "[cleanup] No backup directory found at $BACKUP_DIR"
        echo "[cleanup] Run ./scripts/backup-test-data.sh first, or use --skip-backup"
        exit 1
    fi
    if ! ls "$BACKUP_DIR/$TODAY"* 2>/dev/null; then
        echo "[cleanup] No backup found for today ($TODAY)"
        echo "[cleanup] Run ./scripts/backup-test-data.sh first, or use FORCE=1"
        exit 1
    fi
    echo "[cleanup] Backup found, proceeding with cleanup..."
fi

echo "[cleanup] Stopping services..."
systemctl --user stop yoitsu-submit.service yoitsu-trenni.service yoitsu-pasloe.service yoitsu-postgres.service yoitsu-pod.service 2>/dev/null || true

echo "[cleanup] Removing job containers..."
podman ps -a --format '{{.Names}}' | grep '^yoitsu-job-' | xargs -r podman rm -f 2>/dev/null || true
podman ps -a --format '{{.Names}}' | grep '^yoitsu-submit' | xargs -r podman rm -f 2>/dev/null || true

echo "[cleanup] Removing volumes..."
podman volume rm -f yoitsu-dev-state yoitsu-pasloe-data yoitsu-postgres-data 2>/dev/null || true

echo "[cleanup] Removing pod (if exists)..."
podman pod rm -f yoitsu-dev 2>/dev/null || true

echo "[cleanup] Cleanup complete"
echo "[cleanup] Restart with: ./scripts/deploy-quadlet.sh"