#!/usr/bin/env bash
set -euo pipefail

# Full test round script: setup -> submit -> monitor -> backup -> cleanup
# Usage: ./scripts/test-round.sh [DURATION_MINUTES] [TASKS_DIR]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

DURATION_MINUTES="${1:-480}"  # 8 hours default
TASKS_DIR="${2:-$ROOT/test-tasks}"
DURATION_SECONDS=$((DURATION_MINUTES * 60))

ROUND_ID="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT/test-runs/$ROUND_ID"

echo "========================================"
echo "  Yoitsu Test Round: $ROUND_ID"
echo "========================================"
echo "Duration: $DURATION_MINUTES minutes ($DURATION_SECONDS seconds)"
echo "Tasks directory: $TASKS_DIR"
echo "Log directory: $LOG_DIR"
echo ""

mkdir -p "$LOG_DIR"

# Step 1: Fresh deployment
echo "[test-round] Step 1: Fresh deployment..."
"$SCRIPT_DIR/cleanup-test-data.sh" --skip-backup 2>&1 | tee "$LOG_DIR/cleanup.log" || true
"$SCRIPT_DIR/deploy-quadlet.sh" --skip-build 2>&1 | tee "$LOG_DIR/deploy.log"

# Wait for services to stabilize
echo "[test-round] Waiting for services to stabilize..."
sleep 30

# Verify services
"$SCRIPT_DIR/health-check.sh" 2>&1 | tee "$LOG_DIR/health.log" || true

# Step 2: Batch submit tasks
echo "[test-round] Step 2: Submitting tasks..."
MAX_TASKS="${MAX_TASKS:-100}"  # Limit tasks per round
"$SCRIPT_DIR/batch-submit.sh" "$TASKS_DIR" 2>&1 | tee "$LOG_DIR/submit.log"

# Step 3: Start monitoring
echo "[test-round] Step 3: Starting monitoring for $DURATION_MINUTES minutes..."
DURATION="$DURATION_SECONDS" \
LOG_FILE="$LOG_DIR/monitor.log" \
OUTPUT_FORMAT=text \
"$SCRIPT_DIR/monitor.sh" &
monitor_pid=$!

# Step 4: Wait for duration or queue empty
echo "[test-round] Monitoring running (PID: $monitor_pid)..."
echo "[test-round] Will run for $DURATION_MINUTES minutes or until queue is empty"

elapsed=0
check_interval=60

while [[ "$elapsed" -lt "$DURATION_SECONDS" ]]; do
    sleep "$check_interval"
    elapsed=$((elapsed + check_interval))
    
    # Check if queue is empty
    status="$(curl -sf http://127.0.0.1:8100/control/status 2>/dev/null || echo '{"running_jobs":0}')"
    running="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("running_jobs",0))' <<<"$status")"
    pending="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("pending_jobs",0))' <<<"$status")"
    
    remaining_minutes=$(( (DURATION_SECONDS - elapsed) / 60 ))
    
    echo "[test-round] Progress: ${elapsed}s elapsed, ${remaining_minutes}m remaining, queue: ${running}r/${pending}p"
    
    # If queue is empty for 3 consecutive checks, we can stop early
    if [[ "$running" -eq 0 && "$pending" -eq 0 ]]; then
        echo "[test-round] Queue is empty, checking if tasks completed..."
        
        # Check task states
        completed="$(python3 -c 'import json,sys; t=json.load(sys.stdin).get("tasks",{}); print(sum(1 for v in t.values() if v=="completed"))' <<<"$status")"
        failed="$(python3 -c 'import json,sys; t=json.load(sys.stdin).get("tasks",{}); print(sum(1 for v in t.values() if v=="failed"))' <<<"$status")"
        
        echo "[test-round] Completed: $completed, Failed: $failed"
        
        if [[ "$completed" -gt 0 || "$failed" -gt 0 ]]; then
            echo "[test-round] All tasks finished, stopping early"
            break
        fi
    fi
done

# Stop monitor
echo "[test-round] Stopping monitor..."
kill "$monitor_pid" 2>/dev/null || true
wait "$monitor_pid" 2>/dev/null || true

# Step 5: Backup data
echo "[test-round] Step 5: Backing up test data..."
"$SCRIPT_DIR/backup-test-data.sh" "$LOG_DIR/backup" 2>&1 | tee "$LOG_DIR/backup.log"

# Step 6: Generate summary report
echo "[test-round] Step 6: Generating summary report..."
"$SCRIPT_DIR/generate-report.sh" "$LOG_DIR" 2>&1 | tee "$LOG_DIR/report.md"

echo ""
echo "========================================"
echo "  Test Round Complete: $ROUND_ID"
echo "========================================"
echo "Logs saved to: $LOG_DIR"
echo "Report: $LOG_DIR/report.md"
echo ""
echo "Next steps:"
echo "  1. Review report: cat $LOG_DIR/report.md"
echo "  2. Cleanup data: ./scripts/cleanup-test-data.sh"
echo "  3. Start new round: ./scripts/test-round.sh"