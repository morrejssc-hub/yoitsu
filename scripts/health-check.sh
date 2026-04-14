#!/usr/bin/env bash
set -euo pipefail

# Health check script for all Yoitsu services
# Usage: ./scripts/health-check.sh [--verbose]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
CLI_PROJECT="${YOITSU_CLI_PROJECT:-$ROOT}"

VERBOSE="${1:-}"
[[ "$VERBOSE" == "--verbose" ]] || VERBOSE=""

PASLOE_URL="${YOITSU_PASLOE_URL:-http://127.0.0.1:8000}"
TRENNI_URL="${YOITSU_TRENNI_URL:-http://127.0.0.1:8100}"

errors=0
warnings=0

echo "[health] Checking Yoitsu services..."
echo ""

# 1. Check Podman
echo -n "[health] Podman: "
if podman info &>/dev/null; then
    echo "✓ OK"
else
    echo "✗ FAIL"
    errors=$((errors + 1))
fi

# 2. Check Yoitsu pod
echo -n "[health] Yoitsu pod: "
if podman pod exists yoitsu-dev 2>/dev/null; then
    pod_status="$(podman pod inspect yoitsu-dev --format '{{.Status}}' 2>/dev/null || echo 'unknown')"
    if [[ "$pod_status" == "Running" ]]; then
        echo "✓ Running"
    else
        echo "⚠ Status: $pod_status"
        warnings=$((warnings + 1))
    fi
else
    echo "✗ Not found"
    errors=$((errors + 1))
fi

# 3. Check PostgreSQL
echo -n "[health] PostgreSQL: "
if podman ps --format '{{.Names}}' | grep -q '^yoitsu-postgres$'; then
    pg_health="$(podman exec yoitsu-postgres pg_isready -q 2>/dev/null && echo 'ok' || echo 'fail')"
    if [[ "$pg_health" == "ok" ]]; then
        echo "✓ OK"
    else
        echo "✗ Not ready"
        errors=$((errors + 1))
    fi
else
    echo "✗ Not running"
    errors=$((errors + 1))
fi

# 4. Check Pasloe HTTP
echo -n "[health] Pasloe HTTP: "
pasloe_response="$(curl -sf --connect-timeout 5 "${PASLOE_URL}/health" 2>/dev/null || echo 'unreachable')"
if [[ "$pasloe_response" != "unreachable" ]]; then
    pasloe_status="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","unknown"))' <<<"$pasloe_response" 2>/dev/null || echo 'parse-error')"
    if [[ "$pasloe_status" == "ok" ]]; then
        echo "✓ OK"
    else
        echo "⚠ Status: $pasloe_status"
        warnings=$((warnings + 1))
    fi
else
    echo "✗ Unreachable"
    errors=$((errors + 1))
fi

# 5. Check Trenni HTTP
echo -n "[health] Trenni HTTP: "
trenni_response="$(curl -sf --connect-timeout 5 "${TRENNI_URL}/control/status" 2>/dev/null || echo 'unreachable')"
if [[ "$trenni_response" != "unreachable" ]]; then
    trenni_running="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("running",False))' <<<"$trenni_response" 2>/dev/null || echo 'false')"
    if [[ "$trenni_running" == "True" ]]; then
        echo "✓ Running"
    else
        echo "⚠ Not running (paused?)"
        warnings=$((warnings + 1))
    fi
else
    echo "✗ Unreachable"
    errors=$((errors + 1))
fi

# 6. Check job image
echo -n "[health] Job image: "
if podman image exists localhost/yoitsu-palimpsest-job:dev 2>/dev/null; then
    echo "✓ Present"
else
    echo "⚠ Not found (run ./scripts/build-job-image.sh)"
    warnings=$((warnings + 1))
fi

# 7. Check disk space
echo -n "[health] Disk space: "
disk_usage="$(df -h /home 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')"
if [[ "${disk_usage:-0}" -lt 80 ]]; then
    echo "✓ ${disk_usage}% used"
elif [[ "${disk_usage:-0}" -lt 90 ]]; then
    echo "⚠ ${disk_usage}% used"
    warnings=$((warnings + 1))
else
    echo "✗ ${disk_usage}% used (critical)"
    errors=$((errors + 1))
fi

# 8. Check systemd services
echo "[health] Systemd services:"
for svc in yoitsu-postgres yoitsu-pasloe yoitsu-trenni; do
    status="$(systemctl --user is-active ${svc}.service 2>/dev/null || echo 'inactive')"
    if [[ "$status" == "active" ]]; then
        echo "  ${svc}: ✓ active"
    else
        echo "  ${svc}: ✗ $status"
        errors=$((errors + 1))
    fi
done

# Summary
echo ""
echo "[health] Summary: $errors errors, $warnings warnings"

if [[ "$VERBOSE" == "--verbose" ]]; then
    echo ""
    echo "[health] Detailed status:"
    uv run --project "$CLI_PROJECT" yoitsu status 2>/dev/null | python3 -m json.tool || true
fi

if [[ "$errors" -gt 0 ]]; then
    exit 1
fi
exit 0
