# Yoitsu CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `yoitsu` CLI that manages the full Yoitsu stack (pasloe + trenni) with JSON-first output and PID-file-based process lifecycle management.

**Architecture:** New Python package at `/home/holo/yoitsu/yoitsu/` installed into the umbrella repo via `uv`. Three modules: `process.py` owns PID files and subprocess launch/kill; `client.py` wraps pasloe + trenni HTTP APIs; `cli.py` wires them into Click commands. All commands output JSON; exit codes are 0/1.

**Tech Stack:** Python 3.11+, click 8, httpx, pyyaml, pytest, hatchling

---

## File Map

| File | Role |
|------|------|
| `pyproject.toml` | Package definition, entry point `yoitsu = yoitsu.cli:main` |
| `yoitsu/__init__.py` | Empty package marker |
| `yoitsu/process.py` | PID file I/O, liveness checks, subprocess start/stop/kill |
| `yoitsu/client.py` | Thin httpx wrappers: `PasloeClient`, `TrenniClient` |
| `yoitsu/cli.py` | Click commands: up, down, status, submit, pause, resume, logs |
| `tests/__init__.py` | Empty test package marker |
| `tests/test_process.py` | Unit tests for PID management and liveness logic |
| `tests/test_client.py` | Unit tests for HTTP client wrappers |
| `tests/test_cli.py` | Integration tests via `CliRunner` with mocked process + client |
| `.gitignore` | Add `.pids.json` |

---

## Task 1: Package Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `yoitsu/__init__.py`
- Create: `tests/__init__.py`
- Modify: `.gitignore`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "yoitsu"
version = "0.1.0"
description = "Yoitsu stack CLI"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0",
    "httpx>=0.27",
    "pyyaml>=6.0",
]

[project.scripts]
yoitsu = "yoitsu.cli:main"

[dependency-groups]
dev = [
    "pytest>=9.0",
    "pytest-asyncio>=1.3",
]

[tool.uv]
package = true

[tool.pytest.ini_options]
asyncio_mode = "auto"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create empty `yoitsu/__init__.py` and `tests/__init__.py`**

Both files are empty (zero bytes).

- [ ] **Step 3: Add `.pids.json` to `.gitignore`**

Append `.pids.json` to the existing `/home/holo/yoitsu/.gitignore` (under the "Logs & runtime state" section).

- [ ] **Step 4: Install the package**

```bash
cd /home/holo/yoitsu && uv sync
```

Expected: no errors. `uv run yoitsu --help` should print "Error: No such command" (or similar) because `cli.py` doesn't exist yet — that's fine.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml yoitsu/__init__.py tests/__init__.py .gitignore
git commit -m "feat: add yoitsu CLI package scaffold"
```

---

## Task 2: `process.py` — PID File and Liveness

**Files:**
- Create: `yoitsu/process.py` (PID file section only)
- Create: `tests/test_process.py` (PID + liveness tests)

The repo root is computed once as `ROOT = Path(__file__).resolve().parent.parent`. All paths are relative to it.

- [ ] **Step 1: Write failing tests for PID file operations**

`tests/test_process.py`:
```python
"""Tests for PID file management and liveness checks."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

# We import after each step — keep imports at top for clarity
import yoitsu.process as proc


class TestIsAlive:
    def test_alive_process_returns_true(self):
        # os.getpid() is always alive
        assert proc.is_alive(os.getpid()) is True

    def test_dead_process_returns_false(self):
        # PID 1 exists but we simulate a dead PID via mock
        with patch("os.kill", side_effect=ProcessLookupError):
            assert proc.is_alive(99999999) is False

    def test_permission_error_treated_as_alive(self):
        with patch("os.kill", side_effect=PermissionError):
            assert proc.is_alive(1) is True


class TestPidFile:
    def test_write_and_read_pids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=100, trenni_pid=200)
        data = proc.read_pids()
        assert data["pasloe"]["pid"] == 100
        assert data["trenni"]["pid"] == 200

    def test_read_pids_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        assert proc.read_pids() is None

    def test_clear_pids_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=1, trenni_pid=2)
        proc.clear_pids()
        assert proc.read_pids() is None

    def test_clear_pids_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.clear_pids()  # file doesn't exist — should not raise
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_process.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `process.py` doesn't exist yet.

- [ ] **Step 3: Implement PID file section of `process.py`**

`yoitsu/process.py`:
```python
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
_PIDS_FILE = ROOT / ".pids.json"
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
    try:
        return json.loads(_PIDS_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_pids(*, pasloe_pid: int, trenni_pid: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    _PIDS_FILE.write_text(json.dumps({
        "pasloe": {"pid": pasloe_pid, "started_at": now},
        "trenni": {"pid": trenni_pid, "started_at": now},
    }, indent=2))


def clear_pids() -> None:
    """Remove .pids.json; no-op if already absent."""
    try:
        _PIDS_FILE.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_process.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/process.py tests/test_process.py
git commit -m "feat: add PID file management and liveness checks"
```

---

## Task 3: `process.py` — Start and Stop

**Files:**
- Modify: `yoitsu/process.py` (append start/stop functions)
- Modify: `tests/test_process.py` (append start/stop tests)

- [ ] **Step 1: Write failing tests for start/stop**

Append to `tests/test_process.py`:
```python
class TestStartStop:
    def test_start_pasloe_launches_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PASLOE_DIR", tmp_path)
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")

        fake_proc = type("P", (), {"pid": 42})()
        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            pid = proc.start_pasloe()
        assert pid == 42
        mock_popen.assert_called_once()
        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[0] == "uv"
        assert "uvicorn" in cmd

    def test_start_trenni_passes_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_TRENNI_DIR", tmp_path)
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")

        fake_proc = type("P", (), {"pid": 99})()
        config = tmp_path / "my.yaml"
        config.touch()
        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            pid = proc.start_trenni(config_path=config)
        assert pid == 99
        cmd = mock_popen.call_args[0][0]
        assert str(config) in cmd

    def test_kill_pid_sends_sigterm_then_sigkill(self):
        kill_calls: list[tuple] = []

        def fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                pass  # pretend process is still alive
            # on SIGKILL, raise ProcessLookupError to simulate dead
            if sig == signal.SIGKILL:
                raise ProcessLookupError

        with patch("os.kill", side_effect=fake_kill):
            proc.kill_pid(123, wait_s=0.05)

        sigs = [sig for _, sig in kill_calls]
        assert signal.SIGTERM in sigs
        assert signal.SIGKILL in sigs
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_process.py::TestStartStop -v
```

Expected: `AttributeError` — functions don't exist yet.

- [ ] **Step 3: Implement `start_pasloe`, `start_trenni`, `kill_pid`**

Append to `yoitsu/process.py`:
```python
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
```

- [ ] **Step 4: Run all process tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_process.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/process.py tests/test_process.py
git commit -m "feat: add process start/stop/kill helpers"
```

---

## Task 4: `client.py` — HTTP Wrappers

**Files:**
- Create: `yoitsu/client.py`
- Create: `tests/test_client.py`

- [ ] **Step 1: Write failing tests**

`tests/test_client.py`:
```python
"""Tests for PasloeClient and TrenniClient."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx

from yoitsu.client import PasloeClient, TrenniClient


class TestPasloeClient:
    def _client(self) -> PasloeClient:
        return PasloeClient(url="http://localhost:8000", api_key="test-key")

    async def test_check_ready_returns_true_on_200(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            assert await c.check_ready() is True

    async def test_check_ready_returns_false_on_connect_error(self):
        c = self._client()
        with patch.object(c._http, "get", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            assert await c.check_ready() is False

    async def test_get_stats_returns_dict(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "total_events": 5,
            "by_source": {},
            "by_type": {"task.submit": 3},
        }
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            stats = await c.get_stats()
        assert stats["total_events"] == 5
        assert "by_source" not in stats  # stripped by client
        assert stats["by_type"]["task.submit"] == 3

    async def test_get_stats_returns_none_on_error(self):
        c = self._client()
        with patch.object(c._http, "get", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            assert await c.get_stats() is None

    async def test_post_event_sends_correct_body(self):
        c = self._client()
        mock_resp = MagicMock(status_code=201)
        mock_resp.json.return_value = {"id": "abc"}
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)) as mock_post:
            event_id = await c.post_event(type_="task.submit", data={"task": "hello"})
        assert event_id == "abc"
        body = mock_post.call_args.kwargs["json"]
        assert body["type"] == "task.submit"
        assert body["source_id"] == "yoitsu-cli"
        assert body["data"]["task"] == "hello"


class TestTrenniClient:
    def _client(self) -> TrenniClient:
        return TrenniClient(url="http://localhost:8100")

    async def test_check_ready_returns_true_on_200(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            assert await c.check_ready() is True

    async def test_get_status_returns_dict(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "running": True, "paused": False,
            "running_jobs": 2, "max_workers": 4,
            "pending_jobs": 0, "ready_queue_size": 0,
        }
        with patch.object(c._http, "get", new=AsyncMock(return_value=mock_resp)):
            status = await c.get_status()
        assert status["running"] is True
        assert status["running_jobs"] == 2

    async def test_post_control_stop_returns_none_on_success(self):
        c = self._client()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"ok": True}
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)):
            err = await c.post_control("stop")
        assert err is None  # None = success

    async def test_post_control_returns_error_string_on_connect_error(self):
        c = self._client()
        with patch.object(c._http, "post", new=AsyncMock(
                side_effect=httpx.ConnectError("refused"))):
            err = await c.post_control("pause")
        assert err is not None
        assert "unreachable" in err.lower()

    async def test_post_control_surfaces_non_200_status_and_body(self):
        c = self._client()
        mock_resp = MagicMock(status_code=409)
        mock_resp.text = "already paused"
        with patch.object(c._http, "post", new=AsyncMock(return_value=mock_resp)):
            err = await c.post_control("pause")
        assert err is not None
        assert "409" in err
        assert "already paused" in err
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_client.py -v
```

Expected: `ModuleNotFoundError` — `client.py` doesn't exist yet.

- [ ] **Step 3: Implement `client.py`**

`yoitsu/client.py`:
```python
"""Thin httpx wrappers for pasloe and trenni HTTP APIs."""
from __future__ import annotations

from typing import Any

import httpx


class PasloeClient:
    def __init__(self, url: str, api_key: str) -> None:
        self._url = url.rstrip("/")
        self._headers = {"X-API-Key": api_key}
        self._http = httpx.AsyncClient(
            base_url=self._url, headers=self._headers, timeout=10.0
        )

    async def check_ready(self) -> bool:
        """Return True if pasloe responds with HTTP 200."""
        try:
            r = await self._http.get("/events", params={"limit": "1"})
            return r.status_code == 200
        except Exception:
            return False

    async def get_stats(self) -> dict[str, Any] | None:
        """Return pasloe stats (total_events + by_type) or None on error."""
        try:
            r = await self._http.get("/events/stats")
            r.raise_for_status()
            raw = r.json()
            return {"total_events": raw["total_events"], "by_type": raw["by_type"]}
        except Exception:
            return None

    async def post_event(self, *, type_: str, data: dict) -> str | None:
        """POST a single event; return event id or None on failure."""
        try:
            r = await self._http.post("/events", json={
                "source_id": "yoitsu-cli",
                "type": type_,
                "data": data,
            })
            r.raise_for_status()
            return r.json().get("id")
        except Exception:
            return None

    async def aclose(self) -> None:
        await self._http.aclose()


class TrenniClient:
    def __init__(self, url: str) -> None:
        self._url = url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self._url, timeout=10.0)

    async def check_ready(self) -> bool:
        """Return True if trenni control API responds with HTTP 200."""
        try:
            r = await self._http.get("/control/status")
            return r.status_code == 200
        except Exception:
            return False

    async def get_status(self) -> dict[str, Any] | None:
        """Return trenni status dict or None on error."""
        try:
            r = await self._http.get("/control/status")
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    async def post_control(self, endpoint: str) -> str | None:
        """POST to /control/<endpoint>. Returns None on success, error string on failure."""
        try:
            r = await self._http.post(f"/control/{endpoint}")
            if r.status_code == 200:
                return None
            return f"trenni returned {r.status_code}: {r.text}"
        except httpx.ConnectError:
            return "trenni unreachable"
        except Exception as exc:
            return str(exc)

    async def aclose(self) -> None:
        await self._http.aclose()
```

- [ ] **Step 4: Run tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_client.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/client.py tests/test_client.py
git commit -m "feat: add pasloe and trenni HTTP client wrappers"
```

---

## Task 5: `cli.py` — `up` Command

**Files:**
- Create: `yoitsu/cli.py` (skeleton + `up`)
- Create: `tests/test_cli.py` (up tests)

The CLI uses `asyncio.run()` internally for HTTP waits. Click commands are synchronous; they call `asyncio.run(some_async_fn())` where needed.

- [ ] **Step 1: Write failing tests for `up`**

`tests/test_cli.py`:
```python
"""CLI integration tests via CliRunner."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from yoitsu.cli import main


def _runner() -> CliRunner:
    return CliRunner(mix_stderr=False)


class TestUp:
    def test_up_fails_if_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("PASLOE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = _runner().invoke(main, ["up"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "PASLOE_API_KEY" in out["error"]

    def test_up_succeeds_when_both_already_alive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=1, trenni_pid=2)

        with patch("yoitsu.process.is_alive", return_value=True):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True

    def test_up_starts_services_and_writes_pids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")
        monkeypatch.setattr(proc, "_DEFAULT_CONFIG", tmp_path / "trenni.yaml")
        (tmp_path / "trenni.yaml").touch()

        with (
            patch("yoitsu.process.is_alive", return_value=False),
            patch("yoitsu.process.start_pasloe", return_value=100),
            patch("yoitsu.process.start_trenni", return_value=200),
            patch("yoitsu.cli._wait_ready", new=AsyncMock(return_value=True)),
        ):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert out["pasloe_pid"] == 100
        assert out["trenni_pid"] == 200
        pids = proc.read_pids()
        assert pids["pasloe"]["pid"] == 100
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestUp -v
```

Expected: `ModuleNotFoundError` — `cli.py` doesn't exist yet.

- [ ] **Step 3: Implement `cli.py` skeleton + `up`**

`yoitsu/cli.py`:
```python
"""Yoitsu CLI — manage the full Yoitsu stack."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import click

from . import process as proc
from .client import PasloeClient, TrenniClient

_PASLOE_URL = "http://localhost:8000"
_TRENNI_URL = "http://localhost:8100"


def _out(data: dict) -> None:
    """Print JSON to stdout."""
    click.echo(json.dumps(data))


def _fail(error: str) -> None:
    """Print error JSON and exit 1."""
    _out({"ok": False, "error": error})
    sys.exit(1)


async def _wait_ready(check_fn, *, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Poll check_fn() every interval seconds until True or timeout."""
    import time
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await check_fn():
            return True
        await asyncio.sleep(interval)
    return False


@click.group()
def main() -> None:
    """Yoitsu stack management CLI."""


@main.command()
@click.option("--config", "-c", "config_path", default=None,
              type=click.Path(), help="Path to trenni config YAML")
def up(config_path: str | None) -> None:
    """Start pasloe + trenni."""
    # 1. Validate env vars
    for var in ("PASLOE_API_KEY", "OPENAI_API_KEY"):
        if not os.environ.get(var):
            _fail(f"{var} not set")

    api_key = os.environ["PASLOE_API_KEY"]

    # 2. Check if already running
    pids = proc.read_pids()
    if pids:
        pasloe_alive = proc.is_alive(pids["pasloe"]["pid"])
        trenni_alive = proc.is_alive(pids["trenni"]["pid"])

        if pasloe_alive and trenni_alive:
            _out({"ok": True,
                  "pasloe_pid": pids["pasloe"]["pid"],
                  "trenni_pid": pids["trenni"]["pid"]})
            return

        # Partial-running state: kill survivor and restart cleanly
        if pasloe_alive:
            proc.kill_pid(pids["pasloe"]["pid"])
        if trenni_alive:
            proc.kill_pid(pids["trenni"]["pid"])
        proc.clear_pids()

    # 3. Crash residue: PID file exists but all dead — already cleaned above or not present

    # 4. Start pasloe
    try:
        pasloe_pid = proc.start_pasloe()
    except Exception as exc:
        _fail(f"Failed to start pasloe: {exc}")

    # 5. Wait for pasloe ready
    pasloe_client = PasloeClient(url=_PASLOE_URL, api_key=api_key)
    ready = asyncio.run(_wait_ready(pasloe_client.check_ready))
    asyncio.run(pasloe_client.aclose())
    if not ready:
        proc.kill_pid(pasloe_pid)
        _fail("pasloe did not become ready within 10s")

    # 6. Start trenni
    cfg = Path(config_path).resolve() if config_path else None
    try:
        trenni_pid = proc.start_trenni(config_path=cfg)
    except Exception as exc:
        proc.kill_pid(pasloe_pid)
        _fail(f"Failed to start trenni: {exc}")

    # 7. Wait for trenni ready
    trenni_client = TrenniClient(url=_TRENNI_URL)
    ready = asyncio.run(_wait_ready(trenni_client.check_ready))
    asyncio.run(trenni_client.aclose())
    if not ready:
        proc.kill_pid(trenni_pid)
        proc.kill_pid(pasloe_pid)
        _fail("trenni did not become ready within 10s")

    # 8. Write PID file
    proc.write_pids(pasloe_pid=pasloe_pid, trenni_pid=trenni_pid)
    _out({"ok": True, "pasloe_pid": pasloe_pid, "trenni_pid": trenni_pid})
```

- [ ] **Step 4: Run tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestUp -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/cli.py tests/test_cli.py
git commit -m "feat: add yoitsu up command"
```

---

## Task 6: `cli.py` — `down` Command

**Files:**
- Modify: `yoitsu/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for `down`**

Append to `tests/test_cli.py`:
```python
class TestDown:
    def test_down_succeeds_when_not_running(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        r = _runner().invoke(main, ["down"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert out["stopped"] == []

    def test_down_stops_both_services(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=100, trenni_pid=200)

        killed: list[int] = []
        with (
            patch("yoitsu.process.is_alive", return_value=True),
            patch("yoitsu.process.kill_pid", side_effect=lambda pid, **kw: killed.append(pid)),
            patch("yoitsu.cli._trenni_graceful_stop", new=AsyncMock(return_value=False)),
        ):
            r = _runner().invoke(main, ["down"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert set(out["stopped"]) == {"trenni", "pasloe"}
        assert 100 in killed
        assert 200 in killed
        assert proc.read_pids() is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestDown -v
```

Expected: FAIL — `down` command not implemented yet.

- [ ] **Step 3: Implement `down`**

Append to `yoitsu/cli.py`:
```python
async def _trenni_graceful_stop(pid: int) -> bool:
    """POST /control/stop; poll for exit. Return True if exited cleanly."""
    client = TrenniClient(url=_TRENNI_URL)
    await client.post_control("stop")
    await client.aclose()

    deadline = asyncio.get_running_loop().time() + 30.0
    while asyncio.get_running_loop().time() < deadline:
        if not proc.is_alive(pid):
            return True
        await asyncio.sleep(0.5)
    return False


@main.command()
def down() -> None:
    """Stop trenni + pasloe."""
    pids = proc.read_pids()
    if not pids:
        _out({"ok": True, "stopped": []})
        return

    pasloe_pid = pids["pasloe"]["pid"]
    trenni_pid = pids["trenni"]["pid"]

    if not proc.is_alive(pasloe_pid) and not proc.is_alive(trenni_pid):
        proc.clear_pids()
        _out({"ok": True, "stopped": []})
        return

    stopped: list[str] = []

    # Stop trenni gracefully, then force if needed
    if proc.is_alive(trenni_pid):
        exited = asyncio.run(_trenni_graceful_stop(trenni_pid))
        if not exited:
            proc.kill_pid(trenni_pid)
        stopped.append("trenni")

    # Stop pasloe
    if proc.is_alive(pasloe_pid):
        proc.kill_pid(pasloe_pid)
        stopped.append("pasloe")

    proc.clear_pids()
    _out({"ok": True, "stopped": stopped})
```

- [ ] **Step 4: Run tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestDown -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/cli.py tests/test_cli.py
git commit -m "feat: add yoitsu down command"
```

---

## Task 7: `cli.py` — `status` Command

**Files:**
- Modify: `yoitsu/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for `status`**

Append to `tests/test_cli.py`:
```python
class TestStatus:
    def test_status_returns_both_services(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=100, trenni_pid=200)

        pasloe_stats = {"total_events": 10, "by_type": {"task.submit": 3}}
        trenni_status = {
            "running": True, "paused": False,
            "running_jobs": 1, "max_workers": 4,
            "pending_jobs": 0, "ready_queue_size": 0,
        }

        with (
            patch("yoitsu.process.is_alive", return_value=True),
            patch("yoitsu.client.PasloeClient.get_stats",
                  new=AsyncMock(return_value=pasloe_stats)),
            patch("yoitsu.client.TrenniClient.get_status",
                  new=AsyncMock(return_value=trenni_status)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["status"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is True
        assert out["pasloe"]["total_events"] == 10
        assert out["trenni"]["running"] is True

    def test_status_marks_dead_service_as_not_alive(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        # No PID file — both dead

        r = _runner().invoke(main, ["status"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is False
        assert out["trenni"]["alive"] is False
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestStatus -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `status`**

Append to `yoitsu/cli.py`:
```python
async def _fetch_status(api_key: str) -> dict:
    pids = proc.read_pids()
    pasloe_pid = pids["pasloe"]["pid"] if pids else None
    trenni_pid = pids["trenni"]["pid"] if pids else None
    pasloe_alive = proc.is_alive(pasloe_pid) if pasloe_pid else False
    trenni_alive = proc.is_alive(trenni_pid) if trenni_pid else False

    pasloe_client = PasloeClient(url=_PASLOE_URL, api_key=api_key)
    trenni_client = TrenniClient(url=_TRENNI_URL)

    try:
        if pasloe_alive:
            stats = await pasloe_client.get_stats()
            pasloe_out = {"alive": True, **(stats or {"error": "stats unavailable"})}
        else:
            pasloe_out = {"alive": False, "error": "process not running"}

        if trenni_alive:
            st = await trenni_client.get_status()
            trenni_out = {"alive": True, **(st or {"error": "status unavailable"})}
        else:
            trenni_out = {"alive": False, "error": "process not running"}
    finally:
        await pasloe_client.aclose()
        await trenni_client.aclose()

    return {"pasloe": pasloe_out, "trenni": trenni_out}


@main.command()
def status() -> None:
    """Show system status (always exits 0)."""
    api_key = os.environ.get("PASLOE_API_KEY", "")
    result = asyncio.run(_fetch_status(api_key))
    _out(result)
```

- [ ] **Step 4: Run tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestStatus -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/cli.py tests/test_cli.py
git commit -m "feat: add yoitsu status command"
```

---

## Task 8: `cli.py` — `submit` Command

**Files:**
- Modify: `yoitsu/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests for `submit`**

Append to `tests/test_cli.py`:
```python
class TestSubmit:
    def test_submit_fails_on_missing_file(self):
        r = _runner().invoke(main, ["submit", "/nonexistent/tasks.yaml"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False

    def test_submit_fails_on_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(":::invalid:::")
        r = _runner().invoke(main, ["submit", str(f)])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False

    def test_submit_posts_all_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - task: hello\n    role: default\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(return_value="event-id-1")), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 0

    def test_submit_counts_failures(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - task: t1\n  - task: t2\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(side_effect=[None, "id-2"])), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestSubmit -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `submit`**

Append to `yoitsu/cli.py`:
```python
@main.command()
@click.argument("tasks_file", type=click.Path(exists=False))
def submit(tasks_file: str) -> None:
    """Submit tasks from a YAML file to pasloe."""
    import yaml  # import here to avoid making yaml mandatory at import time

    api_key = os.environ.get("PASLOE_API_KEY", "")

    try:
        raw = Path(tasks_file).read_text()
    except FileNotFoundError:
        _fail(f"File not found: {tasks_file}")

    try:
        doc = yaml.safe_load(raw)
        tasks = doc["tasks"]
    except Exception as exc:
        _fail(f"Invalid YAML: {exc}")

    async def _do_submit() -> dict:
        client = PasloeClient(url=_PASLOE_URL, api_key=api_key)
        submitted = 0
        failed = 0
        errors: list[str] = []
        try:
            for task in tasks:
                event_id = await client.post_event(type_="task.submit", data=dict(task))
                if event_id is None:
                    failed += 1
                    errors.append(str(task.get("task", "?")))
                else:
                    submitted += 1
        finally:
            await client.aclose()
        return {"submitted": submitted, "failed": failed, "errors": errors}

    _out(asyncio.run(_do_submit()))
```

- [ ] **Step 4: Run tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestSubmit -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add yoitsu/cli.py tests/test_cli.py
git commit -m "feat: add yoitsu submit command"
```

---

## Task 9: `cli.py` — `pause`, `resume`, `logs`

**Files:**
- Modify: `yoitsu/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:
```python
class TestPauseResume:
    def test_pause_returns_ok(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value=None)), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["pause"])
        assert r.exit_code == 0
        assert json.loads(r.output)["ok"] is True

    def test_resume_returns_ok(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value=None)), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["resume"])
        assert r.exit_code == 0
        assert json.loads(r.output)["ok"] is True

    def test_pause_fails_and_surfaces_error_detail(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value="trenni returned 409: already paused")), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["pause"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "409" in out["error"]


class TestLogs:
    def test_logs_returns_last_n_lines(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")
        (tmp_path / "pasloe.log").write_text("line1\nline2\nline3\n")
        (tmp_path / "trenni.log").write_text("tline1\ntline2\n")

        r = _runner().invoke(main, ["logs", "--service", "pasloe", "--lines", "2"])
        assert r.exit_code == 0
        assert "line2" in r.output
        assert "line3" in r.output
        assert "line1" not in r.output

    def test_logs_missing_file_returns_empty(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")

        r = _runner().invoke(main, ["logs", "--service", "pasloe"])
        assert r.exit_code == 0
        assert r.output.strip() == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd /home/holo/yoitsu && uv run pytest tests/test_cli.py::TestPauseResume tests/test_cli.py::TestLogs -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `pause`, `resume`, `logs`**

Append to `yoitsu/cli.py`:
```python
async def _control(endpoint: str) -> str | None:
    """Returns None on success, error string on failure."""
    client = TrenniClient(url=_TRENNI_URL)
    err = await client.post_control(endpoint)
    await client.aclose()
    return err


@main.command()
def pause() -> None:
    """Pause job dispatch (running jobs continue)."""
    err = asyncio.run(_control("pause"))
    if err is None:
        _out({"ok": True})
    else:
        _fail(err)


@main.command()
def resume() -> None:
    """Resume job dispatch."""
    err = asyncio.run(_control("resume"))
    if err is None:
        _out({"ok": True})
    else:
        _fail(err)


@main.command()
@click.option("--service", type=click.Choice(["pasloe", "trenni", "all"]),
              default="all", show_default=True)
@click.option("--lines", default=100, show_default=True, type=int)
def logs(service: str, lines: int) -> None:
    """Print last N lines from service logs (plain text)."""
    targets: list[tuple[str, Path]] = []
    if service in ("pasloe", "all"):
        targets.append(("pasloe", proc._PASLOE_LOG))
    if service in ("trenni", "all"):
        targets.append(("trenni", proc._TRENNI_LOG))

    for name, path in targets:
        if service == "all":
            click.echo(f"=== {name} ===")
        try:
            text = path.read_text()
            tail = text.splitlines()[-lines:]
            click.echo("\n".join(tail))
        except FileNotFoundError:
            pass  # return empty, no error
```

- [ ] **Step 4: Run all tests**

```bash
cd /home/holo/yoitsu && uv run pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 5: Smoke-test the CLI**

```bash
cd /home/holo/yoitsu && uv run yoitsu --help
```

Expected: shows `up`, `down`, `status`, `submit`, `pause`, `resume`, `logs` subcommands.

```bash
uv run yoitsu status
```

Expected: JSON with both services `alive: false` (stack not running).

- [ ] **Step 6: Commit**

```bash
git add yoitsu/cli.py tests/test_cli.py
git commit -m "feat: add yoitsu pause, resume, logs commands — CLI complete"
```

---

## Task 10: Final Cleanup

**Files:**
- Modify: `scripts/start.sh` — add deprecation notice pointing to `yoitsu up`
- Modify: `README.md` — update Quick Start to use `yoitsu up/down/status`

- [ ] **Step 1: Update `scripts/start.sh` header**

Add a comment block after the shebang line:
```bash
# DEPRECATED: Use `uv run yoitsu up` instead.
# This script is kept for reference only.
```

- [ ] **Step 2: Update `README.md` Quick Start section**

Replace the Quick Start block:
```markdown
## Quick Start

```bash
# 1. Clone components
./scripts/setup.sh

# 2. Set env vars
export PASLOE_API_KEY=yoitsu-test-key-2026
export OPENAI_API_KEY=<your-key>

# 3. Start the stack
uv run yoitsu up

# 4. Submit tasks
uv run yoitsu submit scripts/trenni.yaml

# 5. Monitor
uv run yoitsu status

# 6. Stop
uv run yoitsu down
```
```

- [ ] **Step 3: Commit**

```bash
git add scripts/start.sh README.md
git commit -m "docs: update Quick Start to use yoitsu CLI"
```
