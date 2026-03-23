#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
QUADLET_SRC="$ROOT/deploy/quadlet"
QUADLET_DEST="${YOITSU_QUADLET_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd/yoitsu}"

BUILD_IMAGE=1
START_SERVICES=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-build)
            BUILD_IMAGE=0
            shift
            ;;
        --no-start)
            START_SERVICES=0
            shift
            ;;
        --dest)
            QUADLET_DEST="$2"
            shift 2
            ;;
        -h|--help)
            cat <<EOF
Usage: $0 [--skip-build] [--no-start] [--dest PATH]

Installs the Quadlet unit files into the user systemd tree, ensures env files
exist from the example templates, optionally builds the Palimpsest job image,
reloads systemd, and starts the Yoitsu Quadlet services.
EOF
            exit 0
            ;;
        *)
            echo "[deploy-quadlet] unknown option: $1" >&2
            exit 1
            ;;
    esac
done

if ! command -v systemctl >/dev/null 2>&1; then
    echo "[deploy-quadlet] systemctl is required" >&2
    exit 1
fi

mkdir -p "$QUADLET_DEST" "$QUADLET_DEST/bin"

copy_file() {
    local rel="$1"
    install -m 0644 "$QUADLET_SRC/$rel" "$QUADLET_DEST/$rel"
}

copy_exec() {
    local rel="$1"
    install -m 0755 "$QUADLET_SRC/$rel" "$QUADLET_DEST/$rel"
}

copy_file "yoitsu.pod"
copy_file "yoitsu-pasloe.container"
copy_file "yoitsu-trenni.container"
copy_file "yoitsu-pasloe-data.volume"
copy_file "yoitsu-dev-state.volume"
copy_file "trenni.dev.yaml"
copy_exec "bin/start-pasloe.sh"
copy_exec "bin/start-trenni.sh"
copy_exec "bin/health-pasloe.sh"
copy_exec "bin/health-trenni.sh"

for name in pasloe trenni; do
    install -m 0644 "$QUADLET_SRC/$name.env.example" "$QUADLET_DEST/$name.env.example"
    if [[ ! -f "$QUADLET_DEST/$name.env" ]]; then
        install -m 0600 "$QUADLET_SRC/$name.env.example" "$QUADLET_DEST/$name.env"
        echo "[deploy-quadlet] created $QUADLET_DEST/$name.env from example"
    fi
done

if [[ "$BUILD_IMAGE" -eq 1 ]]; then
    "$SCRIPT_DIR/build-job-image.sh"
fi

echo "[deploy-quadlet] Reloading user systemd"
systemctl --user daemon-reload

if [[ "$START_SERVICES" -eq 1 ]]; then
    echo "[deploy-quadlet] Starting podman.socket and Yoitsu services"
    systemctl --user start podman.socket yoitsu-pod.service
    systemctl --user restart yoitsu-pasloe.service yoitsu-trenni.service
fi

echo "[deploy-quadlet] Done"
echo "[deploy-quadlet] Quadlet dir: $QUADLET_DEST"
echo "[deploy-quadlet] Next: edit $QUADLET_DEST/pasloe.env and $QUADLET_DEST/trenni.env if needed"
echo "[deploy-quadlet] Status: $SCRIPT_DIR/quadlet-status.sh"
