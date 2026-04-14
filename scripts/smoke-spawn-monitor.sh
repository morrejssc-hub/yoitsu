#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLI_PROJECT="${YOITSU_CLI_PROJECT:-$ROOT_DIR}"

PASLOE_URL="${YOITSU_PASLOE_URL:-http://127.0.0.1:8000}"
TRENNI_URL="${YOITSU_TRENNI_URL:-http://127.0.0.1:8100}"
BUNDLE="${BUNDLE:-${TEAM:-}}"
ROLE="${ROLE:-}"
BUDGET="${BUDGET:-0.80}"
TASK_TIMEOUT="${TASK_TIMEOUT:-180}"
TASK_INTERVAL="${TASK_INTERVAL:-3}"
TAIL_SOURCE="${TAIL_SOURCE:-trenni-supervisor}"
TAIL_ENABLED="${TAIL_ENABLED:-0}"
ROOT_REPO_CONTEXT="${ROOT_REPO_CONTEXT:-0}"
FRESH_RESET="${FRESH_RESET:-0}"
REBUILD_IMAGE="${REBUILD_IMAGE:-0}"

GOAL="${GOAL:-Spawn-mode smoke test.

Target outcome:
- create a new file smoke/SMOKE.txt in this repository
- the file must contain exactly one line with no trailing whitespace: smoke: ok
- do not modify any other file

The root task has no repo context. Use spawn to create child tasks that do the repository work. Each child task is an independent unit of work — the runtime automatically commits and pushes each child workspace on completion.

Each spawned child must include role, goal, budget, repo, init_branch, eval_spec.deliverables, and eval_spec.criteria.

After child tasks finish, review join_context. If the work is done, do not spawn more tasks.}"
REPO="${REPO-https://github.com/guan-spicy-wolf/yoitsu.git}"
BRANCH="${BRANCH-master}"

usage() {
  cat <<EOF
Usage: $0 [--fresh] [--rebuild-image]

Submit one spawn-mode smoke task and wait for terminal state.

Options:
  --fresh          destroy existing Yoitsu runtime data, redeploy services,
                   and wait for a clean empty queue before submitting
  --rebuild-image  rebuild the Palimpsest job image during --fresh reset
  -h, --help       show this help text

Required env:
  ROLE             root role to execute

Optional env:
  BUNDLE           bundle name
  GOAL             root task goal
  REPO             target repository mentioned in the prompt
  BRANCH           target branch mentioned in the prompt
  ROOT_REPO_CONTEXT=1  also pass repo/init_branch as root trigger fields
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --fresh)
      FRESH_RESET=1
      shift
      ;;
    --rebuild-image)
      REBUILD_IMAGE=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[smoke] unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "$ROLE" ]]; then
  echo "[smoke] ROLE is required (for example ROLE=planner)" >&2
  exit 1
fi

if [[ -z "$BUNDLE" ]]; then
  echo "[smoke] BUNDLE is required" >&2
  exit 1
fi

if [[ ! -f "$CLI_PROJECT/pyproject.toml" ]]; then
  echo "[smoke] yoitsu CLI project not found: $CLI_PROJECT" >&2
  exit 1
fi

if [[ "$BUNDLE" == "factorio" && "$GOAL" == *"create a new file smoke/SMOKE.txt"* ]]; then
  echo "[smoke] default smoke goal targets repository-authoring work, but bundle 'factorio' only supports live Factorio bundle tasks" >&2
  echo "[smoke] provide a factorio-specific GOAL or run the smoke against a repository-authoring bundle" >&2
  exit 1
fi

export BUNDLE ROLE BUDGET GOAL REPO BRANCH ROOT_REPO_CONTEXT

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

wait_for_services() {
  local deadline="$((SECONDS + 180))"
  while (( SECONDS < deadline )); do
    if curl -sf "${PASLOE_URL}/health" >/dev/null 2>&1 && \
       curl -sf "${TRENNI_URL}/control/status" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "[smoke] services did not become ready within 180s" >&2
  return 1
}

if [[ "$FRESH_RESET" == "1" ]]; then
  echo "[smoke] resetting runtime state"
  bash "$ROOT_DIR/scripts/cleanup-test-data.sh" --skip-backup
  if [[ "$REBUILD_IMAGE" == "1" ]]; then
    echo "[smoke] rebuilding job image"
    bash "$ROOT_DIR/scripts/build-job-image.sh"
  fi
  echo "[smoke] redeploying quadlet services"
  bash "$ROOT_DIR/scripts/deploy-quadlet.sh" --skip-build
  echo "[smoke] waiting for services"
  wait_for_services
fi

echo "[smoke] status snapshot"
(
  uv run --project "$CLI_PROJECT" yoitsu status
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
goal = os.environ["GOAL"]
repo = os.environ.get("REPO", "").strip()
branch = os.environ.get("BRANCH", "").strip() or "main"
if repo:
    goal = (
        f"{goal}\n\n"
        f"Target repository:\n"
        f"- repo: {repo}\n"
        f"- branch: {branch}"
    )
payload = {
    "source_id": "smoke-spawn-monitor",
    "type": "trigger.external.received",
    "data": {
        "goal": goal,
        "bundle": os.environ["BUNDLE"],
        "role": os.environ["ROLE"],
        "budget": float(os.environ["BUDGET"]),
    },
}
if os.environ.get("ROOT_REPO_CONTEXT", "0") == "1" and repo:
    payload["data"]["repo"] = repo
    payload["data"]["init_branch"] = branch
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
    uv run --project "$CLI_PROJECT" yoitsu events --task "$task_id" --source "$TAIL_SOURCE" tail
  ) &
  tail_pid="$!"
  sleep 1
fi

echo "[smoke] initial chain"
(
  uv run --project "$CLI_PROJECT" yoitsu tasks chain "$task_id"
)

echo "[smoke] waiting for terminal state"
set +e
(
  uv run --project "$CLI_PROJECT" yoitsu tasks --timeout "$TASK_TIMEOUT" --interval "$TASK_INTERVAL" wait "$task_id"
)
wait_rc=$?
set -e

echo "[smoke] final chain"
(
  uv run --project "$CLI_PROJECT" yoitsu tasks chain "$task_id"
)

echo "[smoke] wait exit code=${wait_rc}"
exit "$wait_rc"
