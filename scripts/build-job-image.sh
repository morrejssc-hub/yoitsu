#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

IMAGE="${YOITSU_JOB_IMAGE:-localhost/yoitsu-palimpsest-job:dev}"
CONTAINERFILE="${YOITSU_JOB_CONTAINERFILE:-$ROOT/deploy/podman/palimpsest-job.Containerfile}"

if ! command -v podman >/dev/null 2>&1; then
    echo "[build-job-image] podman is required" >&2
    exit 1
fi

if [[ ! -f "$CONTAINERFILE" ]]; then
    echo "[build-job-image] missing Containerfile: $CONTAINERFILE" >&2
    exit 1
fi

echo "[build-job-image] Building $IMAGE"
podman build -t "$IMAGE" -f "$CONTAINERFILE" "$ROOT"
echo "[build-job-image] Done"
