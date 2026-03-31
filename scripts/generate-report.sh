#!/usr/bin/env bash
set -euo pipefail

# Generate summary report from test run
# Usage: ./scripts/generate-report.sh [LOG_DIR]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

LOG_DIR="${1:-$ROOT/test-runs/latest}"

if [[ ! -d "$LOG_DIR" ]]; then
    echo "[report] Log directory not found: $LOG_DIR"
    exit 1
fi

ROUND_ID="$(basename "$LOG_DIR")"

# Fetch final status
status_json="$(curl -sf http://127.0.0.1:8100/control/status 2>/dev/null || echo '{}')"

# Parse task statistics
task_stats="$(python3 << PY
import json,sys
try:
    d=json.load(sys.stdin)
    tasks=d.get("tasks",{})
    completed=sum(1 for v in tasks.values() if v=="completed")
    failed=sum(1 for v in tasks.values() if v=="failed")
    partial=sum(1 for v in tasks.values() if v=="partial")
    eval_failed=sum(1 for v in tasks.values() if v=="eval_failed")
    pending=sum(1 for v in tasks.values() if v=="pending")
    running=sum(1 for v in tasks.values() if v=="running")
    evaluating=sum(1 for v in tasks.values() if v=="evaluating")
    total=len(tasks)
    success_rate=(completed/total*100) if total>0 else 0
    print(f"{completed}|{failed}|{partial}|{eval_failed}|{pending}|{running}|{evaluating}|{total}|{success_rate:.1f}")
except:
    print("0|0|0|0|0|0|0|0|0.0")
PY
 <<< "$status_json")"

completed="$(echo "$task_stats" | cut -d'|' -f1)"
failed="$(echo "$task_stats" | cut -d'|' -f2)"
partial="$(echo "$task_stats" | cut -d'|' -f3)"
eval_failed="$(echo "$task_stats" | cut -d'|' -f4)"
pending="$(echo "$task_stats" | cut -d'|' -f5)"
running="$(echo "$task_stats" | cut -d'|' -f6)"
evaluating="$(echo "$task_stats" | cut -d'|' -f7)"
total="$(echo "$task_stats" | cut -d'|' -f8)"
success_rate="$(echo "$task_stats" | cut -d'|' -f9)"

# Calculate duration from logs
start_time="$(head -1 "$LOG_DIR/monitor.log" 2>/dev/null | grep -oP '\[\K[0-9-]+ [0-9:]+' || echo 'unknown')"
end_time="$(tail -1 "$LOG_DIR/monitor.log" 2>/dev/null | grep -oP '\[\K[0-9-]+ [0-9:]+' || echo 'unknown')"

# Count job containers created
container_count="$(grep -c 'yoitsu-job-' "$LOG_DIR/monitor.log" 2>/dev/null || echo 0)"

# Get git commits
yoitsu_commit="$(cd "$ROOT" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
trenni_commit="$(cd "$ROOT/trenni" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
palimpsest_commit="$(cd "$ROOT/palimpsest" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
pasloe_commit="$(cd "$ROOT/pasloe" && git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"

# Generate markdown report
cat > "$LOG_DIR/report.md" << EOF
# Test Run Report: $ROUND_ID

## Summary

| Metric | Value |
|--------|-------|
| Round ID | $ROUND_ID |
| Start Time | $start_time |
| End Time | $end_time |
| Total Tasks | $total |
| Completed | $completed |
| Failed | $failed |
| Partial | $partial |
| Eval Failed | $eval_failed |
| Success Rate | $success_rate% |

## Task Distribution

\`\`\`
Completed:    $(printf '%5s' "$completed") $(python3 -c "print('█' * int($completed / max($total, 1) * 40))")
Failed:       $(printf '%5s' "$failed") $(python3 -c "print('█' * int($failed / max($total, 1) * 40))")
Partial:      $(printf '%5s' "$partial") $(python3 -c "print('█' * int($partial / max($total, 1) * 40))")
Eval Failed:  $(printf '%5s' "$eval_failed") $(python3 -c "print('█' * int($eval_failed / max($total, 1) * 40))")
Pending:      $(printf '%5s' "$pending") $(python3 -c "print('█' * int($pending / max($total, 1) * 40))")
\`\`\`

## Version Information

| Component | Commit |
|-----------|--------|
| Yoitsu | $yoitsu_commit |
| Trenni | $trenni_commit |
| Palimpsest | $palimpsest_commit |
| Pasloe | $pasloe_commit |

## Logs

- [Deploy Log](deploy.log)
- [Submit Log](submit.log)
- [Monitor Log](monitor.log)
- [Backup Log](backup.log)

## Files

\`\`\`
$(ls -la "$LOG_DIR" 2>/dev/null | tail -n +2 || echo "No files")
\`\`\`

---
Generated: $(date)
EOF

echo "[report] Report generated: $LOG_DIR/report.md"
cat "$LOG_DIR/report.md"