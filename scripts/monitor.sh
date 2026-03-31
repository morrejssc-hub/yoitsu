#!/usr/bin/env bash
set -euo pipefail

# Continuous monitoring dashboard for long-running tests
# Usage: ./scripts/monitor.sh [--interval SECONDS] [--log-file PATH]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

INTERVAL="${INTERVAL:-60}"
LOG_FILE="${LOG_FILE:-$ROOT/monitor.log}"
DURATION="${DURATION:-}"  # Optional: stop after N seconds
OUTPUT_FORMAT="${OUTPUT_FORMAT:-text}"  # text or json

PASLOE_URL="${YOITSU_PASLOE_URL:-http://127.0.0.1:8000}"
TRENNI_URL="${YOITSU_TRENNI_URL:-http://127.0.0.1:8100}"

# Load API key
if [[ -z "${PASLOE_API_KEY:-}" ]]; then
    ENV_FILE="${HOME}/.config/containers/systemd/yoitsu/trenni.env"
    if [[ -f "$ENV_FILE" ]]; then
        PASLOE_API_KEY="$(sed -n 's/^PASLOE_API_KEY=//p' "$ENV_FILE" | tail -n 1)"
        export PASLOE_API_KEY
    fi
fi

start_time="$(date +%s)"
iteration=0

# Accumulated statistics
declare -A stats
stats[total_tasks]=0
stats[completed]=0
stats[failed]=0
stats[partial]=0
stats[pending]=0
stats[running]=0
stats[evaluating]=0
stats[total_jobs]=0
stats[total_containers_created]=0

echo "[monitor] Starting continuous monitoring (interval=${INTERVAL}s)"
echo "[monitor] Log file: $LOG_FILE"
echo "[monitor] Press Ctrl-C to stop"

# Initialize log file
echo "# Yoitsu Monitor Log - Started $(date)" > "$LOG_FILE"
echo "# timestamp,running_jobs,pending_jobs,ready_queue,completed,failed,partial" >> "$LOG_FILE"

cleanup() {
    echo ""
    echo "[monitor] Stopped at $(date)"
    duration_sec=$(( $(date +%s) - start_time ))
    echo "[monitor] Total duration: ${duration_sec}s"
    echo "[monitor] Final statistics:"
    for key in "${!stats[@]}"; do
        echo "  $key: ${stats[$key]}"
    done
    exit 0
}
trap cleanup INT TERM

while true; do
    iteration=$((iteration + 1))
    now="$(date +%s)"
    elapsed=$(( now - start_time ))
    
    # Check duration limit
    if [[ -n "$DURATION" && "$elapsed" -ge "$DURATION" ]]; then
        echo "[monitor] Duration limit reached ($DURATION seconds)"
        cleanup
    fi
    
    # Fetch status from Trenni
    status_json="$(curl -sf "${TRENNI_URL}/control/status" 2>/dev/null || echo '{"error": "trenni unreachable"}')"
    
    # Parse status
    running_jobs="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("running_jobs",0))' <<<"$status_json")"
    pending_jobs="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("pending_jobs",0))' <<<"$status_json")"
    ready_queue="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("ready_queue_size",0))' <<<"$status_json")"
    paused="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("paused",False))' <<<"$status_json")"
    
    # Parse task states
    tasks_json="$(python3 -c '
import json,sys
d=json.load(sys.stdin)
tasks=d.get("tasks",{})
completed=failed=partial=pending=running=evaluating=0
for k,v in tasks.items():
    if v=="completed": completed+=1
    elif v=="failed": failed+=1
    elif v=="partial": partial+=1
    elif v=="pending": pending+=1
    elif v=="running": running+=1
    elif v=="evaluating": evaluating+=1
print(f"{completed},{failed},{partial},{pending},{running},{evaluating}")
' <<<"$status_json")"
    
    completed="$(echo "$tasks_json" | cut -d, -f1)"
    failed="$(echo "$tasks_json" | cut -d, -f2)"
    partial="$(echo "$tasks_json" | cut -d, -f3)"
    pending="$(echo "$tasks_json" | cut -d, -f4)"
    running="$(echo "$tasks_json" | cut -d, -f5)"
    evaluating="$(echo "$tasks_json" | cut -d, -f6)"
    
    # Update accumulated stats (max values)
    total_tasks=$((completed + failed + partial + pending + running + evaluating))
    stats[total_tasks]="$total_tasks"
    stats[completed]="$completed"
    stats[failed]="$failed"
    stats[partial]="$partial"
    stats[pending]="$pending"
    stats[running]="$running"
    stats[evaluating]="$evaluating"
    stats[total_jobs]="$((stats[total_jobs] + running_jobs))"
    
    # Check container count
    container_count="$(podman ps --format '{{.Names}}' | grep -c '^yoitsu-job-' 2>/dev/null || echo 0)"
    stats[total_containers_created]="$((stats[total_containers_created] + container_count))"
    
    # Health check
    pasloe_health="$(curl -sf "${PASLOE_URL}/health" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","unknown"))' || echo 'unreachable')"
    
    # Format output
    timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    
    if [[ "$OUTPUT_FORMAT" == "json" ]]; then
        python3 -c '
import json,sys
data={
    "timestamp": sys.argv[1],
    "elapsed_sec": int(sys.argv[2]),
    "iteration": int(sys.argv[3]),
    "running_jobs": int(sys.argv[4]),
    "pending_jobs": int(sys.argv[5]),
    "ready_queue": int(sys.argv[6]),
    "tasks": {
        "completed": int(sys.argv[7]),
        "failed": int(sys.argv[8]),
        "partial": int(sys.argv[9]),
        "pending": int(sys.argv[10]),
        "running": int(sys.argv[11]),
        "evaluating": int(sys.argv[12]),
    },
    "container_count": int(sys.argv[13]),
    "pasloe_health": sys.argv[14],
    "paused": sys.argv[15] == "True",
}
print(json.dumps(data))
' "$timestamp" "$elapsed" "$iteration" "$running_jobs" "$pending_jobs" "$ready_queue" \
  "$completed" "$failed" "$partial" "$pending" "$running" "$evaluating" \
  "$container_count" "$pasloe_health" "$paused"
    else
        # Text format - compact status line
        echo "[$timestamp] elapsed=${elapsed}s iter=${iteration} | jobs: ${running_jobs}r/${pending_jobs}p/${ready_queue}q | tasks: ${completed}✓ ${failed}✗ ${partial}~ ${pending}… ${running}▶ ${evaluating}⏳ | containers: ${container_count} | pasloe: ${pasloe_health}"
    fi | tee -a "$LOG_FILE"
    
    # Log detailed data to file
    echo "${timestamp},${running_jobs},${pending_jobs},${ready_queue},${completed},${failed},${partial}" >> "$LOG_FILE.data"
    
    sleep "$INTERVAL"
done