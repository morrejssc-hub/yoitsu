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


async def _trenni_graceful_stop(pid: int) -> bool:
    """POST /control/stop; poll for exit. Return True if exited cleanly."""
    client = TrenniClient(url=_TRENNI_URL)
    try:
        await client.post_control("stop")
    except Exception:
        pass  # best-effort; proceed to poll
    finally:
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


@main.command()
@click.argument("tasks_file", type=click.Path(exists=False))
def submit(tasks_file: str) -> None:
    """Submit tasks from a YAML file to pasloe."""
    import yaml

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
