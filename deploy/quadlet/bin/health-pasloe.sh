#!/bin/sh
set -eu

python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as resp:
    payload = json.loads(resp.read().decode("utf-8"))

if payload.get("status") != "ok":
    raise SystemExit(1)
PY
