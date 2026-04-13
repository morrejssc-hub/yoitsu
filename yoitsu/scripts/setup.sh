#!/usr/bin/env bash
# setup.sh — Clone or update all Yoitsu component repos
# Usage: ./scripts/setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

REPOS=(
    "yoitsu-contracts:git@github.com:guan-spicy-wolf/yoitsu-contracts.git"
    "palimpsest:git@github.com:guan-spicy-wolf/palimpsest.git"
    "pasloe:git@github.com:guan-spicy-wolf/pasloe.git"
    "trenni:git@github.com:guan-spicy-wolf/trenni.git"
)

for entry in "${REPOS[@]}"; do
    name="${entry%%:*}"
    url="${entry#*:}"
    dest="$ROOT/$name"

    if [[ -d "$dest/.git" ]]; then
        echo "[setup] Updating $name..."
        git -C "$dest" pull --ff-only
    else
        echo "[setup] Cloning $name..."
        git clone "$url" "$dest"
    fi
done

# palimpsest has an evo submodule
if [[ -f "$ROOT/palimpsest/.gitmodules" ]]; then
    echo "[setup] Initializing palimpsest submodules..."
    git -C "$ROOT/palimpsest" submodule update --init --recursive
fi

echo "[setup] Done."
