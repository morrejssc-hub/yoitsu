#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI_PROJECT="${YOITSU_CLI_PROJECT:-$ROOT_DIR}"
cd "$ROOT_DIR"

INTERVAL="${INTERVAL:-10}"
PASLOE_API_KEY="${PASLOE_API_KEY:-$(grep PASLOE_API_KEY ~/.config/containers/systemd/yoitsu/trenni.env 2>/dev/null | cut -d= -f2)}"

if [[ -z "$PASLOE_API_KEY" ]]; then
    echo "[monitor] PASLOE_API_KEY not set" >&2
    exit 1
fi

export PASLOE_API_KEY

echo "[monitor] Starting (interval=${INTERVAL}s)"
echo "[monitor] Press Ctrl-C to stop"
echo ""

while true; do
    echo "=== $(date '+%H:%M:%S') ==="

    # Status summary
    status_json="$(uv run --project "$CLI_PROJECT" yoitsu status 2>/dev/null || echo '{}')"
    paused="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("trenni",{}).get("paused",False))' <<<"$status_json")"
    running="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("trenni",{}).get("running_jobs",0))' <<<"$status_json")"
    pending="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("trenni",{}).get("pending_jobs",0))' <<<"$status_json")"
    tasks_in_mem="$(python3 -c 'import json,sys; d=json.load(sys.stdin); t=d.get("trenni",{}).get("tasks",{}); print(len(t))' <<<"$status_json")"

    paused_icon="▶"  # running
    if [[ "$paused" == "True" ]]; then
        paused_icon="⏸"  # paused
    fi

    echo "  [$paused_icon] jobs: running=$running pending=$pending  tasks_in_mem=$tasks_in_mem"

    # Smoke test status
    smoke_content="$(cat smoke/SMOKE.txt 2>/dev/null || echo '(empty)')"
    smoke_status="❌ empty"
    if [[ "$smoke_content" == "smoke: ok" ]]; then
        smoke_status="✅ PASS"
    elif [[ -n "$smoke_content" ]]; then
        smoke_status="⚠️  has content: '$smoke_content'"
    fi
    echo "  [smoke] $smoke_status"

    # Task chain for smoke test root
    echo ""
    uv run --project "$CLI_PROJECT" yoitsu tasks chain 069dcd2647ad762a 2>/dev/null | head -20 || echo "  (chain unavailable)"

    # Running containers
    echo ""
    containers="$(podman ps --format "{{.Names}}" --filter "name=yoitsu-job" 2>/dev/null | head -5)"
    if [[ -n "$containers" ]]; then
        echo "  [containers]"
        for c in $containers; do
            echo "    - $c"
        done
    else
        echo "  [containers] none running"
    fi

    echo ""
    echo "----------------------------------------"
    sleep "$INTERVAL"
done
