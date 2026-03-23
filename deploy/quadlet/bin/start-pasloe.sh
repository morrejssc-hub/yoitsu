#!/bin/sh
set -eu

STATE_DIR="${PASLOE_STATE_DIR:-/var/lib/pasloe}"
PASLOE_SRC="${PASLOE_SRC_ROOT:-/workspace/pasloe}"
VENV="${STATE_DIR}/venv"

export PIP_DISABLE_PIP_VERSION_CHECK=1

mkdir -p "${STATE_DIR}"

if [ ! -x "${VENV}/bin/python" ]; then
  python -m venv "${VENV}"
  "${VENV}/bin/pip" install --upgrade pip setuptools wheel
fi

"${VENV}/bin/pip" install --upgrade "${PASLOE_SRC}"

cd "${PASLOE_SRC}"
exec "${VENV}/bin/uvicorn" src.pasloe.app:app --host 0.0.0.0 --port 8000
