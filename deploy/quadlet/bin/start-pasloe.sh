#!/bin/sh
set -eu

STATE_DIR="${PASLOE_STATE_DIR:-/var/lib/pasloe}"
PASLOE_SRC="${PASLOE_SRC_ROOT:-/workspace/pasloe}"
VENV="${STATE_DIR}/venv"
SRC_REV_FILE="${STATE_DIR}/pasloe.rev"
PIP_CACHE_DIR="${STATE_DIR}/pip-cache"

export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_CACHE_DIR

mkdir -p "${STATE_DIR}" "${PIP_CACHE_DIR}"

current_src_rev() {
  if command -v git >/dev/null 2>&1; then
    rev="$(git -C "$PASLOE_SRC" rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$rev" ]; then
      printf '%s\n' "$rev"
      return 0
    fi
  fi

  (
    cd "$PASLOE_SRC" || exit 1
    find . \
      \( -path './.git' -o -path './.venv' -o -path './__pycache__' -o -path './.pytest_cache' \) -prune \
      -o -type f -print \
      | LC_ALL=C sort \
      | while IFS= read -r rel; do
          sha="$(sha256sum "$rel" | awk '{print $1}')"
          printf '%s  %s\n' "$sha" "$rel"
        done \
      | sha256sum \
      | awk '{print $1}'
  )
}

if [ ! -x "${VENV}/bin/python" ]; then
  python -m venv "${VENV}"
  "${VENV}/bin/pip" install --upgrade pip setuptools wheel
fi

current_rev="$(current_src_rev)"
stored_rev="$(cat "${SRC_REV_FILE}" 2>/dev/null || true)"
needs_install=0

if [ ! -x "${VENV}/bin/uvicorn" ]; then
  needs_install=1
fi

if [ "${current_rev}" != "${stored_rev}" ]; then
  needs_install=1
fi

if [ "${needs_install}" -eq 1 ]; then
  "${VENV}/bin/pip" install --upgrade "${PASLOE_SRC}"
  printf '%s\n' "${current_rev}" > "${SRC_REV_FILE}"
fi

cd "${PASLOE_SRC}"
exec "${VENV}/bin/uvicorn" src.pasloe.app:app --host 0.0.0.0 --port 8000
