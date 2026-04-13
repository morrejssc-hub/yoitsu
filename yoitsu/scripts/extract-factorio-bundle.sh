#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$ROOT_DIR/evo/factorio}"
TARGET_DIR="${TARGET_DIR:-$(dirname "$ROOT_DIR")/factorio-bundle}"
REMOTE_URL="${REMOTE_URL:-https://github.com/guan-spicy-wolf/factorio-bundle.git}"
BRANCH="${BRANCH:-evolve}"
COMMIT_MESSAGE="${COMMIT_MESSAGE:-chore: import factorio bundle from yoitsu evo snapshot}"
GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-holo}"
GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-holo@localhost.localdomain}"

usage() {
  cat <<EOF
Usage: $0 [--source PATH] [--target PATH] [--remote URL] [--branch NAME]

Extract evo/factorio into an independent git repository snapshot.

Options:
  --source PATH   source bundle directory (default: $SOURCE_DIR)
  --target PATH   destination repo directory (default: $TARGET_DIR)
  --remote URL    origin remote URL (default: $REMOTE_URL)
  --branch NAME   initial branch name (default: $BRANCH)
  -h, --help      show this help text
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --target)
      TARGET_DIR="$2"
      shift 2
      ;;
    --remote)
      REMOTE_URL="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[extract-factorio-bundle] unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "[extract-factorio-bundle] source directory not found: $SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"

if [[ ! -d "$TARGET_DIR/.git" ]]; then
  git init -b "$BRANCH" "$TARGET_DIR" >/dev/null
fi

git -C "$TARGET_DIR" config user.name "$GIT_AUTHOR_NAME"
git -C "$TARGET_DIR" config user.email "$GIT_AUTHOR_EMAIL"

if git -C "$TARGET_DIR" rev-parse --verify HEAD >/dev/null 2>&1; then
  git -C "$TARGET_DIR" checkout -B "$BRANCH" >/dev/null
else
  git -C "$TARGET_DIR" symbolic-ref HEAD "refs/heads/$BRANCH"
fi

if git -C "$TARGET_DIR" remote get-url origin >/dev/null 2>&1; then
  git -C "$TARGET_DIR" remote set-url origin "$REMOTE_URL"
else
  git -C "$TARGET_DIR" remote add origin "$REMOTE_URL"
fi

find "$TARGET_DIR" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

while IFS= read -r rel; do
  dest="$TARGET_DIR/${rel#./}"
  mkdir -p "$(dirname "$dest")"
  cp "$SOURCE_DIR/${rel#./}" "$dest"
done < <(
  cd "$SOURCE_DIR"
  find . \( -name '__pycache__' -o -name '*.pyc' \) -prune -o -type f -print | LC_ALL=C sort
)

cat >"$TARGET_DIR/.gitignore" <<'EOF'
__pycache__/
*.pyc
EOF

git -C "$TARGET_DIR" add .

if ! git -C "$TARGET_DIR" diff --cached --quiet --exit-code; then
  git -C "$TARGET_DIR" commit -m "$COMMIT_MESSAGE" >/dev/null
fi

echo "[extract-factorio-bundle] source: $SOURCE_DIR"
echo "[extract-factorio-bundle] target: $TARGET_DIR"
echo "[extract-factorio-bundle] remote: $REMOTE_URL"
echo "[extract-factorio-bundle] head: $(git -C "$TARGET_DIR" rev-parse --short HEAD)"
