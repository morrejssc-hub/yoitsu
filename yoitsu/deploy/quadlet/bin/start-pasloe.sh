#!/bin/sh
set -eu

STATE_DIR="${PASLOE_STATE_DIR:-/var/lib/pasloe}"
PASLOE_SRC="${PASLOE_SRC_ROOT:-/workspace/pasloe}"
VENV="${STATE_DIR}/venv"
SRC_REV_FILE="${STATE_DIR}/pasloe.rev"
BASE_VENV="${YOITSU_BASE_VENV:-/opt/yoitsu-base/venv}"
BASE_REV_FILE="${YOITSU_BASE_REV_DIR:-/opt/yoitsu-base/revs}/pasloe.rev"
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
  if [ -x "${BASE_VENV}/bin/python" ]; then
    cp -a "${BASE_VENV}" "${VENV}"
    if [ -f "${BASE_REV_FILE}" ]; then
      cp "${BASE_REV_FILE}" "${SRC_REV_FILE}"
    fi
  else
    python -m venv "${VENV}"
    "${VENV}/bin/pip" install --upgrade pip setuptools wheel
  fi
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

if [ "${DB_TYPE:-postgres}" = "postgres" ]; then
  "${VENV}/bin/python" - <<'PY'
import asyncio
import os
import time

import asyncpg


async def wait_for_pg() -> None:
    host = os.environ.get("PG_HOST", "127.0.0.1")
    port = int(os.environ.get("PG_PORT", "5432"))
    user = os.environ.get("PG_USER", "yoitsu")
    password = os.environ.get("PG_PASSWORD", "yoitsu")
    database = os.environ.get("PG_DB", "pasloe")

    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                timeout=5,
            )
            await conn.execute("SELECT 1")
            await conn.close()
            return
        except Exception:
            await asyncio.sleep(2)
    raise SystemExit("postgres did not become ready within 90s")


asyncio.run(wait_for_pg())
PY
fi

cd "${PASLOE_SRC}"
exec "${VENV}/bin/uvicorn" src.pasloe.app:app --host 0.0.0.0 --port 8000
