#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

IMAGE="${YOITSU_PYTHON_BASE_IMAGE:-localhost/yoitsu-python-base:dev}"
CONTAINERFILE="${YOITSU_PYTHON_BASE_CONTAINERFILE:-$ROOT/deploy/podman/yoitsu-python-base.Containerfile}"

if ! command -v podman >/dev/null 2>&1; then
    echo "[build-python-base] podman is required" >&2
    exit 1
fi

if [[ ! -f "$CONTAINERFILE" ]]; then
    echo "[build-python-base] missing Containerfile: $CONTAINERFILE" >&2
    exit 1
fi

contracts_rev="$(git -C "$ROOT/yoitsu-contracts" rev-parse HEAD 2>/dev/null || true)"
pasloe_rev="$(git -C "$ROOT/pasloe" rev-parse HEAD 2>/dev/null || true)"
trenni_rev="$(git -C "$ROOT/trenni" rev-parse HEAD 2>/dev/null || true)"

echo "[build-python-base] Building $IMAGE"
podman build \
    --build-arg "YOITSU_CONTRACTS_REV=$contracts_rev" \
    --build-arg "PASLOE_REV=$pasloe_rev" \
    --build-arg "TRENNI_REV=$trenni_rev" \
    -t "$IMAGE" \
    -f "$CONTAINERFILE" \
    "$ROOT"
echo "[build-python-base] Done"
