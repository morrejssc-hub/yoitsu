#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

IMAGE="${YOITSU_JOB_IMAGE:-localhost/yoitsu-palimpsest-job:dev}"
CONTAINERFILE="${YOITSU_JOB_CONTAINERFILE:-$ROOT/deploy/podman/palimpsest-job.Containerfile}"
NO_CACHE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-cache)
            NO_CACHE=1
            shift
            ;;
        -h|--help)
            cat <<'EOF'
Usage: scripts/build-job-image.sh [--no-cache]

Build the local Palimpsest job image used by Trenni.

Options:
  --no-cache   Force a clean rebuild without Podman layer cache
EOF
            exit 0
            ;;
        *)
            echo "[build-job-image] unknown argument: $1" >&2
            exit 1
            ;;
    esac
done

if ! command -v podman >/dev/null 2>&1; then
    echo "[build-job-image] podman is required" >&2
    exit 1
fi

if [[ ! -f "$CONTAINERFILE" ]]; then
    echo "[build-job-image] missing Containerfile: $CONTAINERFILE" >&2
    exit 1
fi

contracts_rev="$(git -C "$ROOT/yoitsu-contracts" rev-parse HEAD 2>/dev/null || true)"
palimpsest_rev="$(git -C "$ROOT/palimpsest" rev-parse HEAD 2>/dev/null || true)"
evo_rev="$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || true)"

build_args=(
    --build-arg "YOITSU_CONTRACTS_REV=$contracts_rev"
    --build-arg "PALIMPSEST_REV=$palimpsest_rev"
    --build-arg "EVO_REV=$evo_rev"
)

if [[ "$NO_CACHE" -eq 1 ]]; then
    build_args=(--no-cache "${build_args[@]}")
fi

echo "[build-job-image] Building $IMAGE"
echo "[build-job-image] yoitsu-contracts rev: ${contracts_rev:-unknown}"
echo "[build-job-image] palimpsest rev: ${palimpsest_rev:-unknown}"
echo "[build-job-image] evo/main repo rev: ${evo_rev:-unknown}"
podman build "${build_args[@]}" -t "$IMAGE" -f "$CONTAINERFILE" "$ROOT"
echo "[build-job-image] Done"
