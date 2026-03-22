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
