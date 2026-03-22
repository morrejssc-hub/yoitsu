"""Process lifecycle management: PID files, liveness, start/stop."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
_PASLOE_LOG = ROOT / "pasloe.log"
_TRENNI_LOG = ROOT / "trenni.log"
_PASLOE_DIR = ROOT / "pasloe"
_TRENNI_DIR = ROOT / "trenni"
_DEFAULT_CONFIG = ROOT / "config" / "trenni.yaml"


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------

def is_alive(pid: int) -> bool:
    """Return True if process pid is running (or owned by another user)."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, we just can't signal it


# ---------------------------------------------------------------------------
# PID file
# ---------------------------------------------------------------------------

def read_pids() -> dict[str, Any] | None:
    """Return parsed .pids.json or None if it doesn't exist / is corrupt."""
    pids_file = ROOT / ".pids.json"
    try:
        return json.loads(pids_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_pids(*, pasloe_pid: int, trenni_pid: int) -> None:
    pids_file = ROOT / ".pids.json"
    now = datetime.now(timezone.utc).isoformat()
    pids_file.write_text(json.dumps({
        "pasloe": {"pid": pasloe_pid, "started_at": now},
        "trenni": {"pid": trenni_pid, "started_at": now},
    }, indent=2))


def clear_pids() -> None:
    """Remove .pids.json; no-op if already absent."""
    pids_file = ROOT / ".pids.json"
    try:
        pids_file.unlink()
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Process start
# ---------------------------------------------------------------------------

def start_pasloe() -> int:
    """Launch pasloe; return its PID. Raises on immediate spawn failure."""
    log_file = open(_PASLOE_LOG, "a")
    p = subprocess.Popen(
        ["uv", "run", "uvicorn", "src.pasloe.app:app",
         "--host", "127.0.0.1", "--port", "8000"],
        cwd=_PASLOE_DIR,
        stdout=log_file,
        stderr=log_file,
    )
    return p.pid


def start_trenni(config_path: Path | None = None) -> int:
    """Launch trenni; return its PID. Raises on immediate spawn failure."""
    config = str(config_path or _DEFAULT_CONFIG)
    log_file = open(_TRENNI_LOG, "a")
    p = subprocess.Popen(
        ["uv", "run", "trenni", "start", "-c", config],
        cwd=_TRENNI_DIR,
        stdout=log_file,
        stderr=log_file,
    )
    return p.pid


# ---------------------------------------------------------------------------
# Process stop
# ---------------------------------------------------------------------------

def kill_pid(pid: int, wait_s: float = 5.0) -> None:
    """Send SIGTERM; if process survives wait_s seconds, send SIGKILL."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # already dead

    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(0.5)
        if not is_alive(pid):
            return

    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # died between check and kill
