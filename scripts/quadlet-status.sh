#!/usr/bin/env bash
set -euo pipefail

IMAGE="${YOITSU_JOB_IMAGE:-localhost/yoitsu-palimpsest-job:dev}"

section() {
    echo
    echo "== $1 =="
}

section "systemd"
systemctl --user --no-pager --full status \
    podman.socket \
    yoitsu-pod.service \
    yoitsu-pasloe.service \
    yoitsu-trenni.service || true

section "podman pod"
podman pod ps || true

section "long-lived containers"
podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" || true

section "job containers"
podman ps -a \
    --filter label=io.yoitsu.managed-by=trenni \
    --format "table {{.Names}}\t{{.Status}}\t{{.Image}}" || true

section "job image"
if podman image exists "$IMAGE"; then
    echo "$IMAGE present"
else
    echo "$IMAGE missing"
fi
