#!/bin/sh
set -eu

STATE_DIR="${YOITSU_STATE_DIR:-/var/lib/yoitsu}"
TRENNI_SRC="${TRENNI_SRC_ROOT:-/workspace/trenni}"
CONTRACTS_SRC="${YOITSU_CONTRACTS_SRC_ROOT:-/workspace/yoitsu-contracts}"
TRENNI_BUILD_SRC="${STATE_DIR}/src/trenni"
CONTRACTS_BUILD_SRC="${STATE_DIR}/src/yoitsu-contracts"
TRENNI_REV_FILE="${STATE_DIR}/src/trenni.rev"
CONTRACTS_REV_FILE="${STATE_DIR}/src/yoitsu-contracts.rev"
TRENNI_VENV="${STATE_DIR}/venvs/trenni"
BASE_VENV="${YOITSU_BASE_VENV:-/opt/yoitsu-base/venv}"
BASE_REV_DIR="${YOITSU_BASE_REV_DIR:-/opt/yoitsu-base/revs}"
PIP_CACHE_DIR="${STATE_DIR}/pip-cache"

export HOME="${HOME:-${STATE_DIR}/home}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_CACHE_DIR

mkdir -p "${STATE_DIR}/venvs" "${STATE_DIR}/src" "${HOME}" "${PIP_CACHE_DIR}"

ensure_venv() {
  venv_path="$1"
  package_path="$2"
  rev_file="$3"
  base_rev_file="$4"

  if [ ! -x "${venv_path}/bin/python" ]; then
    if [ -x "${BASE_VENV}/bin/python" ]; then
      cp -a "${BASE_VENV}" "${venv_path}"
      if [ -f "${base_rev_file}" ]; then
        cp "${base_rev_file}" "${rev_file}"
      fi
    else
      python -m venv "${venv_path}"
      "${venv_path}/bin/pip" install --upgrade pip setuptools wheel
    fi
  fi

  "${venv_path}/bin/pip" install --upgrade "${package_path}"
}

current_src_rev() {
  src_path="$1"

  if command -v git >/dev/null 2>&1; then
    rev="$(git -C "$src_path" rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$rev" ]; then
      printf '%s\n' "$rev"
      return 0
    fi
  fi

  (
    cd "$src_path" || exit 1
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

sync_src() {
  src_path="$1"
  dest_path="$2"

  rm -rf "${dest_path}"
  mkdir -p "${dest_path}"
  cp -a "${src_path}"/. "${dest_path}"/
}

sync_and_install() {
  src_path="$1"
  build_path="$2"
  venv_path="$3"
  rev_file="$4"

  current_rev="$(current_src_rev "${src_path}")"
  stored_rev="$(cat "${rev_file}" 2>/dev/null || true)"
  needs_refresh=0

  if [ ! -d "${build_path}" ] || [ ! -x "${venv_path}/bin/python" ]; then
    needs_refresh=1
  fi

  if [ "${current_rev}" != "${stored_rev}" ]; then
    needs_refresh=1
  fi

  if [ "${needs_refresh}" -eq 1 ]; then
    sync_src "${src_path}" "${build_path}"
    base_rev_file="${BASE_REV_DIR}/$(basename "${rev_file}")"
    ensure_venv "${venv_path}" "${build_path}" "${rev_file}" "${base_rev_file}"
    printf '%s\n' "${current_rev}" > "${rev_file}"
  fi
}

sync_and_install "${CONTRACTS_SRC}" "${CONTRACTS_BUILD_SRC}" "${TRENNI_VENV}" "${CONTRACTS_REV_FILE}"
sync_and_install "${TRENNI_SRC}" "${TRENNI_BUILD_SRC}" "${TRENNI_VENV}" "${TRENNI_REV_FILE}"

python - <<'PY'
import sys
import time
import urllib.request
import json

deadline = time.time() + 60
url = "http://127.0.0.1:8000/health"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("status") == "ok":
                sys.exit(0)
    except Exception:
        time.sleep(2)

raise SystemExit("pasloe did not become ready within 60s")
PY

exec "${TRENNI_VENV}/bin/trenni" start -c /etc/yoitsu/trenni.yaml
