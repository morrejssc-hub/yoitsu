#!/bin/sh
set -eu

STATE_DIR="${YOITSU_STATE_DIR:-/var/lib/yoitsu}"
PALIMPSEST_SRC="${PALIMPSEST_SRC_ROOT:-/workspace/palimpsest}"
TRENNI_SRC="${TRENNI_SRC_ROOT:-/workspace/trenni}"
PALIMPSEST_BUILD_SRC="${STATE_DIR}/src/palimpsest"
TRENNI_BUILD_SRC="${STATE_DIR}/src/trenni"
PALIMPSEST_REV_FILE="${STATE_DIR}/src/palimpsest.rev"
TRENNI_REV_FILE="${STATE_DIR}/src/trenni.rev"
PALIMPSEST_VENV="${STATE_DIR}/venvs/palimpsest"
TRENNI_VENV="${STATE_DIR}/venvs/trenni"
PIP_CACHE_DIR="${STATE_DIR}/pip-cache"

export HOME="${HOME:-${STATE_DIR}/home}"
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_CACHE_DIR
export DEBIAN_FRONTEND=noninteractive

mkdir -p "${STATE_DIR}/venvs" "${STATE_DIR}/trenni-work" "${STATE_DIR}/src" "${HOME}" "${PIP_CACHE_DIR}"

# ADR-0003: In the rootless Podman/Quadlet dev deployment we validate
# application behavior first and rely on the outer container boundary.
# Inner per-job bubblewrap is intentionally disabled here, so only git and
# basic CA material are bootstrapped in the container.
if [ ! -x /usr/bin/git ]; then
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates git
  rm -rf /var/lib/apt/lists/*
fi

ensure_venv() {
  venv_path="$1"
  package_path="$2"

  if [ ! -x "${venv_path}/bin/python" ]; then
    python -m venv "${venv_path}"
    "${venv_path}/bin/pip" install --upgrade pip setuptools wheel
  fi

  "${venv_path}/bin/pip" install --upgrade "${package_path}"
}

current_src_rev() {
  git -C "$1" rev-parse HEAD 2>/dev/null || echo "unknown"
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
    ensure_venv "${venv_path}" "${build_path}"
    printf '%s\n' "${current_rev}" > "${rev_file}"
  fi
}

sync_and_install "${PALIMPSEST_SRC}" "${PALIMPSEST_BUILD_SRC}" "${PALIMPSEST_VENV}" "${PALIMPSEST_REV_FILE}"
sync_and_install "${TRENNI_SRC}" "${TRENNI_BUILD_SRC}" "${TRENNI_VENV}" "${TRENNI_REV_FILE}"

python - <<'PY'
import sys
import time
import urllib.request

deadline = time.time() + 60
url = "http://127.0.0.1:8000/health"

while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=5):
            sys.exit(0)
    except Exception:
        time.sleep(2)

raise SystemExit("pasloe did not become ready within 60s")
PY

exec "${TRENNI_VENV}/bin/trenni" start -c /etc/yoitsu/trenni.yaml
