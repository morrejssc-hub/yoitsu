#!/usr/bin/env bash
set -euo pipefail

# Batch submit tasks for long-running tests
# Usage: ./scripts/batch-submit.sh [TASKS_DIR] [--interval SECONDS] [--parallel N]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

TASKS_DIR="${1:-$ROOT/test-tasks}"
INTERVAL="${INTERVAL:-300}"  # 5 minutes between submissions
PARALLEL="${PARALLEL:-1}"    # submit N tasks at once
MAX_TASKS="${MAX_TASKS:-0}"  # 0 = unlimited

PASLOE_URL="${YOITSU_PASLOE_URL:-http://127.0.0.1:8000}"

# Load API key
if [[ -z "${PASLOE_API_KEY:-}" ]]; then
    ENV_FILE="${HOME}/.config/containers/systemd/yoitsu/trenni.env"
    if [[ -f "$ENV_FILE" ]]; then
        PASLOE_API_KEY="$(sed -n 's/^PASLOE_API_KEY=//p' "$ENV_FILE" | tail -n 1)"
        export PASLOE_API_KEY
    fi
fi

if [[ -z "${PASLOE_API_KEY:-}" ]]; then
    echo "[batch-submit] PASLOE_API_KEY not set" >&2
    exit 1
fi

# Check tasks directory
if [[ ! -d "$TASKS_DIR" ]]; then
    echo "[batch-submit] Creating tasks directory: $TASKS_DIR"
    mkdir -p "$TASKS_DIR"
    echo "[batch-submit] Place task YAML files in $TASKS_DIR"
    exit 0
fi

# Find task files
task_files="$(find "$TASKS_DIR" -name '*.yaml' -o -name '*.yml' | sort)"
task_count="$(echo "$task_files" | grep -c . || echo 0)"

if [[ "$task_count" -eq 0 ]]; then
    echo "[batch-submit] No task files found in $TASKS_DIR"
    exit 0
fi

echo "[batch-submit] Found $task_count task files in $TASKS_DIR"
echo "[batch-submit] Interval: $INTERVAL seconds"
echo "[batch-submit] Parallel: $PARALLEL tasks at once"

submitted=0
failed=0
skipped=0

for task_file in $task_files; do
    if [[ "$MAX_TASKS" -gt 0 && "$submitted" -ge "$MAX_TASKS" ]]; then
        echo "[batch-submit] Max tasks limit reached ($MAX_TASKS)"
        break
    fi
    
    # Check if already submitted (has a stamp file)
    stamp_file="$TASKS_DIR/.submitted/$(basename "$task_file").stamp"
    if [[ -f "$stamp_file" ]]; then
        echo "[batch-submit] Skipping already submitted: $task_file"
        skipped=$((skipped + 1))
        continue
    fi
    
    echo "[batch-submit] Submitting: $task_file"
    
    # Submit task
    result="$(uv run yoitsu submit "$task_file" 2>&1)"
    
    # Check result
    submitted_count="$(python3 -c 'import json,sys; d=json.loads(sys.stdin.read().strip().split("\n")[-1]); print(d.get("submitted",0))' <<<"$result" 2>/dev/null || echo 0)"
    
    if [[ "$submitted_count" -gt 0 ]]; then
        submitted=$((submitted + submitted_count))
        echo "[batch-submit] ✓ Submitted $submitted_count tasks from $task_file"
        
        # Create stamp file
        mkdir -p "$TASKS_DIR/.submitted"
        echo "$(date +%Y%m%d-%H%M%S)" > "$stamp_file"
        echo "$result" >> "$stamp_file"
    else
        failed=$((failed + 1))
        echo "[batch-submit] ✗ Failed to submit $task_file"
        echo "$result" | tail -3
    fi
    
    # Wait between submissions (unless parallel batch)
    if [[ $((submitted % PARALLEL)) -eq 0 && "$submitted" -lt "$task_count" ]]; then
        echo "[batch-submit] Waiting $INTERVAL seconds..."
        sleep "$INTERVAL"
    fi
done

echo "[batch-submit] Summary:"
echo "  Submitted: $submitted"
echo "  Failed: $failed"
echo "  Skipped: $skipped"

# Show current queue status
echo "[batch-submit] Current queue status:"
curl -sf http://127.0.0.1:8100/control/status | python3 -m json.tool | head -20