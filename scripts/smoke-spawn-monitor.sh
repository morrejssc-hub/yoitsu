#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

PASLOE_URL="${YOITSU_PASLOE_URL:-http://127.0.0.1:8000}"
TRENNI_URL="${YOITSU_TRENNI_URL:-http://127.0.0.1:8100}"
TEAM="${TEAM:-default}"
BUDGET="${BUDGET:-0.80}"
TASK_TIMEOUT="${TASK_TIMEOUT:-180}"
TASK_INTERVAL="${TASK_INTERVAL:-3}"
TAIL_SOURCE="${TAIL_SOURCE:-trenni-supervisor}"
TAIL_ENABLED="${TAIL_ENABLED:-0}"

GOAL="${GOAL:-Spawn-mode smoke test.

Target outcome:
- create a new file smoke/SMOKE.txt in this repository
- the file must contain exactly one line with no trailing whitespace: smoke: ok
- do not modify any other file

The root task has no repo context. Use spawn to create child tasks that do the repository work. Each child task is an independent unit of work — the runtime automatically commits and pushes each child workspace on completion.

Each spawned child must include role, goal, budget, params.repo, params.init_branch, eval_spec.deliverables, and eval_spec.criteria.

After child tasks finish, review join_context. If the work is done, do not spawn more tasks.}"
REPO="${REPO:-https://github.com/guan-spicy-wolf/yoitsu.git}"
BRANCH="${BRANCH:-master}"
export TEAM BUDGET GOAL REPO BRANCH

if [[ -z "${PASLOE_API_KEY:-}" ]]; then
  ENV_FILE="${HOME}/.config/containers/systemd/yoitsu/trenni.env"
  if [[ -f "$ENV_FILE" ]]; then
    PASLOE_API_KEY="$(sed -n 's/^PASLOE_API_KEY=//p' "$ENV_FILE" | tail -n 1)"
    export PASLOE_API_KEY
  fi
fi

if [[ -z "${PASLOE_API_KEY:-}" ]]; then
  echo "PASLOE_API_KEY is not set and could not be loaded from trenni.env" >&2
  exit 1
fi

echo "[smoke] status snapshot"
(
  cd "$ROOT_DIR"
  uv run yoitsu status
)

status_json="$(
  curl -sf "${TRENNI_URL}/control/status"
)"

if ! python3 -c '
import json, sys
status = json.load(sys.stdin)
busy = status.get("running_jobs", 0) or status.get("pending_jobs", 0) or status.get("ready_queue_size", 0)
raise SystemExit(0 if busy == 0 else 1)
' <<<"$status_json"; then
  echo "[smoke] refusing to submit a new task: live queue is not empty" >&2
  echo "$status_json" >&2
  exit 2
fi

payload="$(python3 - <<'PY'
import json, os
payload = {
    "source_id": "smoke-spawn-monitor",
    "type": "trigger.external.received",
    "data": {
        "goal": os.environ["GOAL"],
        "team": os.environ["TEAM"],
        "budget": float(os.environ["BUDGET"]),
        "context": {
            "repo": os.environ["REPO"],
            "init_branch": os.environ["BRANCH"],
            "new_branch": True,
        },
    },
}
print(json.dumps(payload))
PY
)"

submit_resp="$(curl -sf \
  -H "X-API-Key: ${PASLOE_API_KEY}" \
  -H "Content-Type: application/json" \
  -X POST "${PASLOE_URL}/events" \
  -d "$payload")"

event_id="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"$submit_resp")"
task_id="$(python3 -c 'import hashlib,sys; s=sys.argv[1]; h="".join(ch for ch in s.lower() if ch in "0123456789abcdef"); print((h[:16] if len(h) >= 16 else hashlib.sha256(s.encode()).hexdigest()[:16]))' "$event_id")"

echo "[smoke] submitted event_id=${event_id}"
echo "[smoke] root task_id=${task_id}"

tail_pid=""
cleanup() {
  if [[ -n "$tail_pid" ]]; then
    kill "$tail_pid" 2>/dev/null || true
    wait "$tail_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$TAIL_ENABLED" == "1" ]]; then
  echo "[smoke] starting task-scoped events tail"
  (
    cd "$ROOT_DIR"
    uv run yoitsu events --task "$task_id" --source "$TAIL_SOURCE" tail
  ) &
  tail_pid="$!"
  sleep 1
fi

echo "[smoke] initial chain"
(
  cd "$ROOT_DIR"
  uv run yoitsu tasks chain "$task_id"
)

echo "[smoke] waiting for terminal state"
set +e
(
  cd "$ROOT_DIR"
  uv run yoitsu tasks --timeout "$TASK_TIMEOUT" --interval "$TASK_INTERVAL" wait "$task_id"
)
wait_rc=$?
set -e

echo "[smoke] final chain"
(
  cd "$ROOT_DIR"
  uv run yoitsu tasks chain "$task_id"
)

echo "[smoke] wait exit code=${wait_rc}"
exit "$wait_rc"
