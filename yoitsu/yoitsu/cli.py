"""Yoitsu CLI — manage the full Yoitsu stack."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import httpx
import json
import os
import subprocess
import time
from pathlib import Path
from typing import NoReturn

import click
from yoitsu_contracts.client import PasloeEvent

from . import process as proc
from .client import PasloeClient, TrenniClient

_PASLOE_URL = os.environ.get("YOITSU_PASLOE_URL", "http://localhost:8000")
_TRENNI_URL = os.environ.get("YOITSU_TRENNI_URL", "http://localhost:8100")
_TRENNI_SOURCE = "trenni-supervisor"
_STOPGAP_EVENT_SCAN_LIMIT = 10_000
_TAIL_HISTORY_LIMIT = 200


def _out(data: dict) -> None:
    """Print JSON to stdout."""
    click.echo(json.dumps(data))


def _fail(error: str) -> NoReturn:
    """Print error JSON and exit 1."""
    _out({"ok": False, "error": error})
    raise SystemExit(1)


def _error_detail(exc: Exception) -> str:
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command timed out: {exc.cmd}"
    if hasattr(exc, "response") and getattr(exc, "response", None) is not None:
        response = exc.response
        body = getattr(response, "text", "")
        return f"http {response.status_code}: {body[:200] or response.reason_phrase}"
    return str(exc)


def _shorten(value: object, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass
class _TaskChainRow:
    task_id: str
    state: str
    icon: str
    role: str
    git_ref: str


async def _optional_live_detail(fetch_coro, *, label: str) -> tuple[dict | None, list[str]]:
    try:
        return await fetch_coro, []
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None, [f"{label} not present in live Trenni state"]
        raise


async def _fetch_all_events(
    client: PasloeClient,
    *,
    source: str | None = None,
    type_: str | None = None,
    order: str = "asc",
    limit: int = 1000,
) -> list[PasloeEvent]:
    # Stopgap scan strategy from ADR-0005 §4. This should be replaced by a
    # task-prefix query or dedicated subtree endpoint before operators rely on
    # scanning arbitrarily large histories.
    events: list[PasloeEvent] = []
    cursor: str | None = None
    while True:
        page, next_cursor = await client.poll(
            cursor=cursor,
            source=source,
            type_=type_,
            limit=limit,
            order=order,
        )
        events.extend(page)
        if len(events) > _STOPGAP_EVENT_SCAN_LIMIT:
            raise RuntimeError(
                f"event scan exceeded stopgap limit ({_STOPGAP_EVENT_SCAN_LIMIT}); "
                "see ADR-0005 §4"
            )
        if not next_cursor:
            return events
        cursor = next_cursor


def _task_in_subtree(candidate: str, root_task_id: str) -> bool:
    return bool(candidate) and (
        candidate == root_task_id or candidate.startswith(root_task_id + "/")
    )


def _event_task_id(event: PasloeEvent) -> str:
    return str(event.data.get("task_id") or "")


def _task_icon(state: str, semantic_verdict: str) -> str:
    if state == "completed":
        return "✓" if semantic_verdict in {"", "pass"} else "~"
    if state == "partial":
        return "~"
    if state == "failed":
        return "✗"
    if state == "cancelled":
        return "–"
    return "…"


def _task_state_from_event_type(event_type: str) -> str | None:
    suffix = event_type.rsplit(".", 1)[-1]
    mapping = {
        "completed": "completed",
        "failed": "failed",
        "partial": "partial",
        "cancelled": "cancelled",
        "eval_failed": "eval_failed",
        "evaluating": "evaluating",
        "created": "pending",
    }
    return mapping.get(suffix)


def _git_ref_from_result(result: dict) -> str:
    trace = result.get("trace", []) or []
    for entry in reversed(trace):
        git_ref = str((entry or {}).get("git_ref") or "")
        if git_ref:
            return git_ref
    return ""


async def _load_task_chain_rows(
    task_id: str,
    pasloe: PasloeClient,
    trenni: TrenniClient,
) -> tuple[list[_TaskChainRow], list[str]]:
    created_events = await _fetch_all_events(
        pasloe,
        source=_TRENNI_SOURCE,
        type_="supervisor.task.created",
    )
    subtree = {
        candidate
        for candidate in [_event_task_id(event) for event in created_events]
        if _task_in_subtree(candidate, task_id)
    }
    subtree.add(task_id)

    supervisor_events = await _fetch_all_events(
        pasloe,
        source=_TRENNI_SOURCE,
    )
    subtree_events = [event for event in supervisor_events if _task_in_subtree(_event_task_id(event), task_id)]
    terminal_events_by_task: dict[str, PasloeEvent] = {}
    for event in subtree_events:
        current_task_id = _event_task_id(event)
        if event.type in {
            "supervisor.task.completed",
            "supervisor.task.failed",
            "supervisor.task.partial",
            "supervisor.task.cancelled",
            "supervisor.task.eval_failed",
        }:
            terminal_events_by_task[current_task_id] = event

    live_tasks, warnings = await _load_live_task_details(
        root_task_id=task_id,
        task_ids=sorted(subtree),
        terminal_events_by_task=terminal_events_by_task,
        trenni=trenni,
    )

    task_ids = sorted(subtree | set(live_tasks.keys()))
    rows: list[_TaskChainRow] = []
    for current_task_id in task_ids:
        task_events = [event for event in subtree_events if _event_task_id(event) == current_task_id]
        first_job_event = next(
            (
                event for event in task_events
                if event.type in {"supervisor.job.launched", "supervisor.job.enqueued"}
            ),
            None,
        )
        role = str(first_job_event.data.get("role") or "-") if first_job_event else "-"
        terminal_event = terminal_events_by_task.get(current_task_id)
        state = ""
        semantic_verdict = ""
        git_ref = ""
        if terminal_event is not None:
            state = _task_state_from_event_type(terminal_event.type) or ""
            result = terminal_event.data.get("result") or {}
            semantic_verdict = str(((result.get("semantic") or {}).get("verdict") or ""))
            git_ref = _git_ref_from_result(result)
        else:
            live = live_tasks.get(current_task_id, {})
            state = str(live.get("state") or "pending")
        rows.append(
            _TaskChainRow(
                task_id=current_task_id,
                state=state,
                icon=_task_icon(state, semantic_verdict),
                role=role,
                git_ref=git_ref or "-",
            )
        )
    return rows, warnings


async def _load_live_task_details(
    *,
    root_task_id: str,
    task_ids: list[str],
    terminal_events_by_task: dict[str, PasloeEvent],
    trenni: TrenniClient,
) -> tuple[dict[str, dict], list[str]]:
    live_tasks: dict[str, dict] = {}
    warnings: list[str] = []
    for task_id in task_ids:
        # Only ask Trenni for tasks that are still live candidates. Historical
        # terminal tasks naturally age out of Trenni's in-memory state and
        # should not produce warning noise during chain/wait views.
        if task_id != root_task_id and task_id in terminal_events_by_task:
            continue
        detail, detail_warnings = await _optional_live_detail(
            trenni.get_task_strict(task_id),
            label=f"task {task_id}",
        )
        if detail is not None:
            live_tasks[task_id] = detail
        warnings.extend(detail_warnings)
    return live_tasks, warnings


async def _fetch_task_history(
    pasloe: PasloeClient,
    *,
    task_id: str,
    source: str | None = None,
    type_: str | None = None,
) -> list[PasloeEvent]:
    created_events = await _fetch_all_events(
        pasloe,
        source=_TRENNI_SOURCE,
        type_="supervisor.task.created",
    )
    subtree = {
        candidate
        for candidate in [_event_task_id(event) for event in created_events]
        if _task_in_subtree(candidate, task_id)
    }
    subtree.add(task_id)

    all_events = await _fetch_all_events(
        pasloe,
        source=source,
        type_=type_,
    )
    return [event for event in all_events if _event_task_id(event) in subtree]


async def _fetch_job_history(
    pasloe: PasloeClient,
    *,
    job_id: str,
    source: str | None = None,
    type_: str | None = None,
) -> list[PasloeEvent]:
    all_events = await _fetch_all_events(
        pasloe,
        source=source,
        type_=type_,
    )
    return [event for event in all_events if _event_matches_job(event, job_id)]


def _render_task_chain(rows: list[_TaskChainRow]) -> str:
    lines: list[str] = []
    for row in rows:
        depth = row.task_id.count("/")
        indent = "  " * depth
        short_task_id = _display_task_id(row.task_id)
        state = f"{row.state} {row.icon}".strip()
        lines.append(
            f"{indent}{short_task_id:<18} {state:<12} {row.role:<12} {row.git_ref}"
        )
    return "\n".join(lines)


def _display_task_id(task_id: str) -> str:
    parts = task_id.split("/")
    if len(parts) == 1:
        return task_id[:16]
    if len(parts) == 2:
        return parts[-1]
    return "/".join(parts[-2:])


def _event_matches_task(event: PasloeEvent, task_id: str | None) -> bool:
    if not task_id:
        return True
    return _task_in_subtree(_event_task_id(event), task_id)


def _event_matches_job(event: PasloeEvent, job_id: str | None) -> bool:
    if not job_id:
        return True
    return str((event.data or {}).get("job_id") or "") == job_id


def _event_detail_lines(event: PasloeEvent) -> list[str]:
    data = event.data or {}
    event_type = event.type
    lines: list[str] = []
    if event_type == "agent.job.completed":
        summary = str(data.get("summary") or "").strip()
        if summary:
            lines.append(f"    summary: {summary}")
        if data.get("code"):
            lines.append(f"    code: {data['code']}")
    elif event_type in {"agent.job.failed", "supervisor.job.failed"}:
        error = str(data.get("error") or "").strip()
        if error:
            lines.append(f"    error: {error}")
        if data.get("code"):
            lines.append(f"    code: {data['code']}")
    elif event_type == "agent.job.spawn_request":
        tasks = data.get("tasks") or []
        lines.append(f"    spawned_tasks: {len(tasks)}")
        for task in tasks[:5]:
            if not isinstance(task, dict):
                continue
            role = str(task.get("role") or "")
            goal = str(task.get("goal") or "").strip()
            lines.append(f"    - role={role or '(none)'} goal={goal[:120]}")
        if len(tasks) > 5:
            lines.append(f"    ... truncated {len(tasks) - 5} more")
    elif event_type == "agent.tool.exec":
        if data.get("tool_name"):
            lines.append(f"    tool: {data['tool_name']}")
        if data.get("arguments_preview"):
            lines.append(f"    args: {str(data['arguments_preview'])[:160]}")
    elif event_type == "agent.tool.result":
        if data.get("tool_name"):
            lines.append(f"    tool: {data['tool_name']} success={data.get('success')}")
        if data.get("output_preview"):
            lines.append(f"    output: {str(data['output_preview'])[:160]}")
    elif event_type == "agent.llm.response":
        lines.append(
            "    "
            f"finish={data.get('finish_reason', '')} "
            f"in={data.get('input_tokens', 0)} "
            f"out={data.get('output_tokens', 0)} "
            f"dur_ms={data.get('duration_ms', 0)}"
        )
    elif event_type == "supervisor.job.launched":
        if data.get("runtime_kind"):
            lines.append(f"    runtime={data['runtime_kind']} container={data.get('container_name', '')}")
    return lines


def _format_event_line(event: PasloeEvent, *, verbose: bool = False) -> str:
    ts = event.ts.strftime("%H:%M:%S")
    data = event.data or {}
    parts = [f"{ts} [{event.source_id}] {event.type}"]
    if data.get("job_id"):
        parts.append(f"job={str(data['job_id'])[:16]}")
    if data.get("task_id"):
        parts.append(f"task={str(data['task_id'])[:16]}")
    if data.get("role"):
        parts.append(f"role={data['role']}")
    line = "  ".join(parts)
    if not verbose:
        return line
    detail_lines = _event_detail_lines(event)
    if not detail_lines:
        return line
    return line + "\n" + "\n".join(detail_lines)


async def _current_tail_cursor(client: PasloeClient) -> str | None:
    page, _ = await client.poll(limit=1, order="desc")
    if not page:
        return None
    event = page[0]
    return f"{event.ts.isoformat()}|{event.id}"


def _podman_summary() -> dict:
    try:
        result = subprocess.run(
            [
                "podman", "ps", "--all",
                "--filter", "label=io.yoitsu.managed-by=trenni",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return {"available": False, "error": result.stderr.strip() or result.stdout.strip()}
        rows = json.loads(result.stdout or "[]")
        running = sum(1 for row in rows if row.get("State") == "running")
        exited = sum(1 for row in rows if row.get("State") == "exited")
        return {"available": True, "running": running, "exited": exited, "total": len(rows)}
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def _watch_event_counts() -> dict[str, int]:
    return {
        "seen": 0,
        "agent": 0,
        "supervisor": 0,
        "observation": 0,
        "other": 0,
    }


def _watch_job_counts() -> dict[str, int]:
    return {
        "started": 0,
        "completed": 0,
        "failed": 0,
    }


def _watch_task_counts() -> dict[str, int]:
    return {
        "created": 0,
        "terminal": 0,
        "completed": 0,
        "failed": 0,
        "partial": 0,
        "cancelled": 0,
        "eval_failed": 0,
        "evaluating": 0,
    }


def _watch_live_snapshot() -> dict[str, int]:
    return {
        "running": 0,
        "pending": 0,
        "ready": 0,
        "tasks_in_memory": 0,
    }


def _record_watch_event(
    event: dict,
    *,
    event_counts: dict[str, int],
    event_type_counts: dict[str, int],
    job_counts: dict[str, int],
    task_counts: dict[str, int],
    errors: list[str],
) -> list[str]:
    et = str(event.get("type") or "")
    data = event.get("data") or {}
    lines: list[str] = []

    event_counts["seen"] += 1
    prefix = et.split(".", 1)[0] if "." in et else et
    if prefix in {"agent", "supervisor", "observation"}:
        event_counts[prefix] += 1
    else:
        event_counts["other"] += 1
    event_type_counts[et] = event_type_counts.get(et, 0) + 1

    if et == "supervisor.task.created":
        task_counts["created"] += 1
        goal = str(data.get("goal") or "")[:80]
        lines.append(f"  [task] created {_shorten(goal, 80)}")
        return lines

    task_state = _task_state_from_event_type(et)
    if et.startswith("supervisor.task.") and task_state:
        if task_state == "evaluating":
            task_counts["evaluating"] += 1
            lines.append(f"  [task] evaluating {_shorten(str(data.get('task_id') or ''), 16)}")
            return lines
        task_counts["terminal"] += 1
        if task_state in task_counts:
            task_counts[task_state] += 1
        lines.append(
            f"  [task] {task_state} {_shorten(str(data.get('task_id') or ''), 16)}"
        )
        return lines

    if et == "agent.job.started":
        job_counts["started"] += 1
        lines.append(
            "  [job] started "
            f"{_shorten(str(data.get('job_id') or ''), 16)} "
            f"role={_shorten(str(data.get('role') or ''), 12)}"
        )
        return lines

    if et == "agent.job.completed":
        job_counts["completed"] += 1
        summary = _shorten(str(data.get("summary") or ""), 60)
        lines.append(
            "  [job] completed "
            f"{_shorten(str(data.get('job_id') or ''), 16)} "
            f"{summary}"
        )
        return lines

    if et in {"agent.job.failed", "supervisor.job.failed"}:
        job_counts["failed"] += 1
        err = _shorten(str(data.get("error") or ""), 80)
        if err:
            errors.append(err)
        lines.append(
            "  [job] failed "
            f"{_shorten(str(data.get('job_id') or ''), 16)} "
            f"{err}"
        )
        return lines

    return lines


def _watch_summary_payload(
    *,
    duration_seconds: float,
    event_counts: dict[str, int],
    event_type_counts: dict[str, int],
    job_counts: dict[str, int],
    task_counts: dict[str, int],
    live_snapshot: dict[str, int],
    errors: list[str],
) -> dict[str, object]:
    total_jobs = job_counts["completed"] + job_counts["failed"]
    success_rate = f"{job_counts['completed'] / total_jobs * 100:.0f}%" if total_jobs else "n/a"
    return {
        "duration_minutes": round(duration_seconds / 60, 1),
        "event": {
            "committed": event_counts["seen"],
            "by_prefix": {
                "agent": event_counts["agent"],
                "supervisor": event_counts["supervisor"],
                "observation": event_counts["observation"],
                "other": event_counts["other"],
            },
            "by_type": dict(sorted(event_type_counts.items())),
        },
        "job": {
            "started": job_counts["started"],
            "completed": job_counts["completed"],
            "failed": job_counts["failed"],
            "success_rate": success_rate,
            "live": dict(live_snapshot),
        },
        "task": {
            "created": task_counts["created"],
            "terminal": task_counts["terminal"],
            "completed": task_counts["completed"],
            "failed": task_counts["failed"],
            "partial": task_counts["partial"],
            "cancelled": task_counts["cancelled"],
            "eval_failed": task_counts["eval_failed"],
            "evaluating": task_counts["evaluating"],
            "live": {
                "in_memory": live_snapshot["tasks_in_memory"],
            },
        },
        "recent_errors": errors[-10:],
    }


async def _wait_ready(check_fn, *, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Poll check_fn() every interval seconds until True or timeout."""
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await check_fn():
            return True
        await asyncio.sleep(interval)
    return False


async def _wait_pasloe_ready(api_key: str, *, timeout: float = 10.0) -> bool:
    """Wait for pasloe readiness and close the client on the same event loop."""
    client = PasloeClient(url=_PASLOE_URL, api_key=api_key)
    try:
        return await _wait_ready(client.check_ready, timeout=timeout)
    finally:
        await client.aclose()


async def _wait_trenni_ready(*, timeout: float = 10.0) -> bool:
    """Wait for trenni readiness and close the client on the same event loop."""
    client = TrenniClient(url=_TRENNI_URL)
    try:
        return await _wait_ready(client.check_ready, timeout=timeout)
    finally:
        await client.aclose()


@click.group()
def main() -> None:
    """Yoitsu stack management CLI."""


async def _do_up(api_key: str, config_path: str | None) -> tuple[int, int]:
    """Start both services and clean up pasloe if trenni startup fails."""
    try:
        pasloe_pid = proc.start_pasloe()
    except Exception as exc:
        _fail(f"Failed to start pasloe: {exc}")

    ready = await _wait_pasloe_ready(api_key)
    if not ready:
        proc.kill_pid(pasloe_pid)
        _fail("pasloe did not become ready within 10s")

    cfg = Path(config_path).resolve() if config_path else None
    try:
        trenni_pid = proc.start_trenni(config_path=cfg)
    except Exception as exc:
        proc.kill_pid(pasloe_pid)
        _fail(f"Failed to start trenni: {exc}")

    ready = await _wait_trenni_ready()
    if not ready:
        proc.kill_pid(trenni_pid)
        proc.kill_pid(pasloe_pid)
        _fail("trenni did not become ready within 10s")

    return pasloe_pid, trenni_pid


@main.command()
@click.option("--config", "-c", "config_path", default=None,
              type=click.Path(), help="Path to trenni config YAML")
def up(config_path: str | None) -> None:
    """Start pasloe + trenni."""
    if not os.environ.get("PASLOE_API_KEY"):
        _fail("PASLOE_API_KEY not set")

    lock_fd = proc.acquire_lock()
    if lock_fd < 0:
        _fail("Another yoitsu instance is running")

    api_key = os.environ["PASLOE_API_KEY"]

    pids = proc.read_pids()
    if pids:
        pasloe_alive = proc.is_alive(pids["pasloe"]["pid"])
        trenni_alive = proc.is_alive(pids["trenni"]["pid"])

        if pasloe_alive and trenni_alive:
            _out({"ok": True,
                  "pasloe_pid": pids["pasloe"]["pid"],
                  "trenni_pid": pids["trenni"]["pid"]})
            return

        if pasloe_alive:
            proc.kill_pid(pids["pasloe"]["pid"])
        if trenni_alive:
            proc.kill_pid(pids["trenni"]["pid"])
        proc.clear_pids()

    try:
        pasloe_pid, trenni_pid = asyncio.run(_do_up(api_key, config_path))
    except SystemExit:
        raise
    except Exception as exc:
        _fail(f"Startup failed: {exc}")
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
        if not pasloe_alive:
            pasloe_alive = await pasloe_client.check_ready()
        if not trenni_alive:
            trenni_alive = await trenni_client.check_ready()

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

    return {"pasloe": pasloe_out, "trenni": trenni_out, "podman": _podman_summary()}


@main.command()
def status() -> None:
    """Show system status (always exits 0)."""
    api_key = os.environ.get("PASLOE_API_KEY", "")
    result = asyncio.run(_fetch_status(api_key))
    _out(result)


@main.command()
@click.option("--timeout", default=600.0, show_default=True, type=float)
@click.option("--interval", default=5.0, show_default=True, type=float)
@click.option("--quiet", is_flag=True)
@click.argument("task_args", nargs=-1)
def tasks(timeout: float, interval: float, quiet: bool, task_args: tuple[str, ...]) -> None:
    """Show live tasks, one task detail, or chain/wait views."""
    async def _do() -> dict:
        trenni = TrenniClient(url=_TRENNI_URL)
        pasloe = PasloeClient(url=_PASLOE_URL, api_key=os.environ.get("PASLOE_API_KEY", ""))
        try:
            if task_args and task_args[0] == "chain":
                if len(task_args) != 2:
                    raise click.ClickException("usage: yoitsu tasks chain <task_id>")
                rows, warnings = await _load_task_chain_rows(task_args[1], pasloe, trenni)
                if not rows:
                    raise click.ClickException(f"task chain not found: {task_args[1]}")
                text = _render_task_chain(rows)
                if warnings:
                    text += "\n\n" + "\n".join(f"[warn] {warning}" for warning in warnings)
                click.echo(text)
                return {}
            if task_args and task_args[0] == "wait":
                if len(task_args) != 2:
                    raise click.ClickException("usage: yoitsu tasks wait <task_id>")
                target_task_id = task_args[1]
                deadline = time.monotonic() + timeout
                while True:
                    rows, warnings = await _load_task_chain_rows(target_task_id, pasloe, trenni)
                    render = _render_task_chain(rows) if rows else ""
                    if not quiet and render:
                        elapsed = max(0.0, timeout - max(0.0, deadline - time.monotonic()))
                        click.echo(f"[wait {elapsed:.1f}s]")
                        click.echo(render)
                        if warnings:
                            click.echo("\n".join(f"[warn] {warning}" for warning in warnings))
                        click.echo("")
                    current = next((row for row in rows if row.task_id == target_task_id), None)
                    state = current.state if current else ""
                    if current and state in {"completed", "failed", "partial", "cancelled", "eval_failed"}:
                        if quiet and render:
                            click.echo(render)
                        raise SystemExit(0 if state == "completed" else 1)
                    if time.monotonic() >= deadline:
                        if quiet and render:
                            click.echo(render)
                        raise SystemExit(2)
                    await asyncio.sleep(interval)
            if task_args:
                task_id = task_args[0]
                detail, warnings = await _optional_live_detail(
                    trenni.get_task_strict(task_id),
                    label=f"task {task_id}",
                )
                history = await pasloe.list_jobs_strict(task_id=task_id)
                payload = {"task": detail, "job_events": history}
                if warnings:
                    payload["warnings"] = warnings
                return payload
            listing = await trenni.get_tasks_strict()
            return {"tasks": listing}
        finally:
            await trenni.aclose()
            await pasloe.aclose()

    try:
        result = asyncio.run(_do())
        if result:
            _out(result)
        elif not task_args or task_args[0] not in {"chain", "wait"}:
            _out({})
    except Exception as exc:
        _fail(f"tasks query failed: {_error_detail(exc)}")


@main.command()
@click.option("--source", default=None)
@click.option("--type", "type_", default=None)
@click.option("--interval", default=2.0, show_default=True, type=float)
@click.argument("job_args", nargs=-1)
def jobs(source: str | None, type_: str | None, interval: float, job_args: tuple[str, ...]) -> None:
    """Show historical job events, one job detail, or tail one job's event stream."""
    async def _do() -> dict:
        trenni = TrenniClient(url=_TRENNI_URL)
        pasloe = PasloeClient(url=_PASLOE_URL, api_key=os.environ.get("PASLOE_API_KEY", ""))
        try:
            if job_args and job_args[0] == "tail":
                if len(job_args) != 2:
                    raise click.ClickException("usage: yoitsu jobs tail <job_id>")
                job_id = job_args[1]
                historical = await _fetch_job_history(
                    pasloe,
                    job_id=job_id,
                    source=source,
                    type_=type_,
                )
                if len(historical) > _TAIL_HISTORY_LIMIT:
                    click.echo(f"[history truncated to last {_TAIL_HISTORY_LIMIT} events]")
                    historical = historical[-_TAIL_HISTORY_LIMIT:]
                for event in historical:
                    click.echo(_format_event_line(event, verbose=True))
                cursor = await _current_tail_cursor(pasloe)
                try:
                    while True:
                        page, next_cursor = await pasloe.poll(
                            cursor=cursor,
                            source=source,
                            type_=type_,
                            limit=100,
                            order="asc",
                        )
                        for event in page:
                            if _event_matches_job(event, job_id):
                                click.echo(_format_event_line(event, verbose=True))
                        if next_cursor:
                            cursor = next_cursor
                        elif page:
                            last = page[-1]
                            cursor = f"{last.ts.isoformat()}|{last.id}"
                        await asyncio.sleep(interval)
                except KeyboardInterrupt:
                    return {}
            if job_args:
                job_id = job_args[0]
                detail, warnings = await _optional_live_detail(
                    trenni.get_job_strict(job_id),
                    label=f"job {job_id}",
                )
                history = await pasloe.list_jobs_strict(job_id=job_id)
                payload = {"job": detail, "events": history}
                if warnings:
                    payload["warnings"] = warnings
                return payload
            listing = await pasloe.list_jobs_strict()
            return {"jobs": listing}
        finally:
            await trenni.aclose()
            await pasloe.aclose()

    try:
        result = asyncio.run(_do())
        if result:
            _out(result)
    except Exception as exc:
        _fail(f"jobs query failed: {_error_detail(exc)}")


@main.command()
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--source", default=None)
@click.option("--type", "type_", default=None)
@click.option("--task", "task_id", default=None)
@click.option("--interval", default=2.0, show_default=True, type=float)
@click.argument("event_args", nargs=-1)
def events(limit: int, source: str | None, type_: str | None, task_id: str | None, interval: float, event_args: tuple[str, ...]) -> None:
    """Show recent committed Pasloe events, or tail them."""
    async def _do() -> dict:
        client = PasloeClient(url=_PASLOE_URL, api_key=os.environ.get("PASLOE_API_KEY", ""))
        try:
            if event_args and event_args[0] == "tail":
                if len(event_args) != 1:
                    raise click.ClickException("usage: yoitsu events tail [--task <task_id>]")
                if task_id:
                    historical = await _fetch_task_history(
                        client,
                        task_id=task_id,
                        source=source,
                        type_=type_,
                    )
                    if len(historical) > _TAIL_HISTORY_LIMIT:
                        click.echo(f"[history truncated to last {_TAIL_HISTORY_LIMIT} events]")
                        historical = historical[-_TAIL_HISTORY_LIMIT:]
                    for event in historical:
                        click.echo(_format_event_line(event))
                cursor = await _current_tail_cursor(client)
                try:
                    while True:
                        page, next_cursor = await client.poll(
                            cursor=cursor,
                            source=source,
                            type_=type_,
                            limit=100,
                            order="asc",
                        )
                        for event in page:
                            if _event_matches_task(event, task_id):
                                click.echo(_format_event_line(event))
                        if next_cursor:
                            cursor = next_cursor
                        elif page:
                            last = page[-1]
                            cursor = f"{last.ts.isoformat()}|{last.id}"
                        await asyncio.sleep(interval)
                except KeyboardInterrupt:
                    return {}
            return {"events": await client.list_events_strict(limit=limit, source=source, type_=type_)}
        finally:
            await client.aclose()

    try:
        result = asyncio.run(_do())
        if result:
            _out(result)
    except Exception as exc:
        _fail(f"events query failed: {_error_detail(exc)}")


@main.command("llm-stats")
@click.option("--model", default=None)
def llm_stats(model: str | None) -> None:
    """Show Pasloe LLM token and cost statistics."""
    async def _do() -> dict:
        client = PasloeClient(url=_PASLOE_URL, api_key=os.environ.get("PASLOE_API_KEY", ""))
        try:
            return await client.get_llm_stats_strict(model=model)
        finally:
            await client.aclose()

    try:
        _out(asyncio.run(_do()))
    except Exception as exc:
        _fail(f"llm-stats query failed: {_error_detail(exc)}")


@main.command()
@click.argument("input_value")
@click.option("--budget", type=float, default=0.0, help="Allocated budget for a raw goal submission")
@click.option("--team", default="default", help="Team for a raw goal submission")
@click.option("--goal", "as_goal", is_flag=True, help="Treat INPUT_VALUE as a raw goal string instead of a YAML file")
def submit(input_value: str, budget: float, team: str, as_goal: bool) -> None:
    """Submit tasks from a YAML file, or one explicit raw goal string."""
    import yaml

    api_key = os.environ.get("PASLOE_API_KEY", "")
    path = Path(input_value)

    if as_goal:
        if budget <= 0:
            _fail("Raw goal submission requires --budget > 0")
        tasks = [{"goal": input_value, "team": team, "budget": budget}]
    else:
        try:
            raw = path.read_text()
            doc = yaml.safe_load(raw)
            tasks = doc["tasks"]
            if not isinstance(tasks, list):
                raise ValueError(f"'tasks' must be a list, got {type(tasks).__name__}")
        except FileNotFoundError:
            _fail(f"File not found: {input_value}. Use --goal to submit a raw goal string.")
        except Exception as exc:
            _fail(f"Invalid YAML: {exc}")

    async def _do_submit() -> dict:
        client = PasloeClient(url=_PASLOE_URL, api_key=api_key)
        submitted = 0
        failed = 0
        errors: list[str] = []
        try:
            for task in tasks:
                raw = dict(task)
                # Canonical fields only
                goal = raw.pop("goal", "")
                if not goal:
                    failed += 1
                    errors.append("missing goal")
                    continue
                role = raw.pop("role", "")
                budget = raw.pop("budget", 0.0)
                bundle = raw.pop("bundle", "")  # Bundle for artifact loading
                repo = raw.pop("repo", "")
                init_branch = raw.pop("init_branch", "")
                raw.pop("team", "")  # Deprecated: TriggerData no longer accepts team
                params = raw.pop("params", {})
                eval_spec = raw.pop("eval_spec", None)
                sha = raw.pop("sha", None)
                input_artifacts = raw.pop("input_artifacts", [])  # ADR-0013

                # Check for forbidden legacy fields
                forbidden = {"prompt", "task", "repo_url", "branch", "context"}
                found = forbidden & set(raw.keys())
                if found:
                    failed += 1
                    errors.append(f"legacy field(s) not allowed: {found}")
                    continue

                # Check for any other unknown fields
                if raw:
                    failed += 1
                    errors.append(f"unknown field(s): {set(raw.keys())}")
                    continue

                payload = {
                    "goal": goal,
                    "role": role,
                    "budget": float(budget) if isinstance(budget, (int, float)) else 0.0,
                    "bundle": bundle,
                    "repo": repo,
                    "init_branch": init_branch,

                    "params": params,
                    "sha": sha,
                    "eval_spec": eval_spec,
                    "input_artifacts": input_artifacts,  # ADR-0013
                }

                event_id = await client.post_event(type_="trigger.external.received", data=payload)
                if event_id is None:
                    failed += 1
                    errors.append(goal)
                else:
                    submitted += 1
        finally:
            await client.aclose()
        return {"submitted": submitted, "failed": failed, "errors": errors}

    _out(asyncio.run(_do_submit()))


async def _control(endpoint: str) -> str | None:
    """Returns None on success, error string on failure."""
    client = TrenniClient(url=_TRENNI_URL)
    try:
        err = await client.post_control(endpoint)
    finally:
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
@click.option("--reset", is_flag=True, help="Wipe runtime data before deploy")
@click.option("--skip-build", is_flag=True, help="Skip job image build")
@click.option("--no-start", is_flag=True, help="Install units but don't start services")
def deploy(reset: bool, skip_build: bool, no_start: bool) -> None:
    """Deploy via Quadlet (containerized mode)."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "deploy-quadlet.sh"
    cmd = [str(script)]
    if skip_build:
        cmd.append("--skip-build")
    if no_start:
        cmd.append("--no-start")
    env = dict(os.environ)
    if reset:
        env["YOITSU_RESET_RUNTIME"] = "1"
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        _fail(result.stderr.strip() or result.stdout.strip() or "deploy failed")
    _out({"ok": True, "stdout": result.stdout.strip()})


@main.command()
def build() -> None:
    """Build the Palimpsest job container image."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "build-job-image.sh"
    if not script.exists():
        _fail(f"build script not found: {script}")
    result = subprocess.run([str(script)], text=True)
    if result.returncode != 0:
        _fail("image build failed")
    _out({"ok": True})


@main.command()
@click.option("--hours", default=5.0, show_default=True, type=float,
              help="Duration in hours (0 = run until Ctrl-C)")
@click.option("--interval", default=30, show_default=True, type=int,
              help="Poll interval in seconds")
def watch(hours: float, interval: int) -> None:
    """Continuously monitor the stack in event/job/task layers."""
    import signal
    from datetime import datetime, timedelta

    api_key = os.environ.get("PASLOE_API_KEY", "")
    stop = False

    def _sigint(*_a: object) -> None:
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _sigint)

    start_time = datetime.now()
    end_time = start_time + timedelta(hours=hours) if hours > 0 else None
    event_cursor: str | None = None
    event_counts = _watch_event_counts()
    event_type_counts: dict[str, int] = {}
    job_counts = _watch_job_counts()
    task_counts = _watch_task_counts()
    live_snapshot = _watch_live_snapshot()
    errors: list[str] = []

    async def _poll_once(pasloe: PasloeClient, trenni: TrenniClient) -> None:
        nonlocal event_cursor

        # Poll new events
        try:
            params: dict = {"limit": 100}
            if event_cursor:
                params["cursor"] = event_cursor
            r = await pasloe._http.get("/events", params=params)
            if r.status_code == 200:
                events = r.json()
                next_cursor = r.headers.get("X-Next-Cursor")
                last_event_type = ""
                for ev in events:
                    last_event_type = str(ev.get("type") or "")
                    for line in _record_watch_event(
                        ev,
                        event_counts=event_counts,
                        event_type_counts=event_type_counts,
                        job_counts=job_counts,
                        task_counts=task_counts,
                        errors=errors,
                    ):
                        click.echo(line)
                if events:
                    click.echo(
                        f"  [event] new={len(events)} committed={event_counts['seen']} "
                        f"last={last_event_type}"
                    )
                if next_cursor:
                    event_cursor = next_cursor
                elif events:
                    last = events[-1]
                    ts, eid = last.get("ts", ""), last.get("id", "")
                    if ts and eid:
                        event_cursor = f"{ts}|{eid}"
        except Exception as exc:
            click.echo(f"  [warn] pasloe poll: {exc}", err=True)

        # Trenni status
        try:
            st = await trenni.get_status()
            if st:
                live_snapshot["running"] = int(st.get("running_jobs") or 0)
                live_snapshot["pending"] = int(st.get("pending_jobs") or 0)
                live_snapshot["ready"] = int(st.get("ready_queue_size") or 0)
                live_snapshot["tasks_in_memory"] = len(st.get("tasks", {}) or {})
                click.echo(
                    "  [job] live "
                    f"running={live_snapshot['running']}/{st.get('max_workers')} "
                    f"pending={live_snapshot['pending']} ready={live_snapshot['ready']} "
                    f"started={job_counts['started']} ok={job_counts['completed']} fail={job_counts['failed']}"
                )
                click.echo(
                    "  [task] live "
                    f"in_memory={live_snapshot['tasks_in_memory']} "
                    f"created={task_counts['created']} terminal={task_counts['terminal']} "
                    f"done={task_counts['completed']} fail={task_counts['failed']} "
                    f"partial={task_counts['partial']}"
                )
        except Exception as exc:
            click.echo(f"  [warn] trenni: {exc}", err=True)

        # Podman
        ps = _podman_summary()
        if ps.get("available"):
            click.echo(f"  [podman] running={ps['running']} exited={ps['exited']} total={ps['total']}")

    async def _run() -> None:
        pasloe = PasloeClient(url=_PASLOE_URL, api_key=api_key)
        trenni = TrenniClient(url=_TRENNI_URL)
        try:
            while not stop:
                if end_time and datetime.now() >= end_time:
                    break
                elapsed = (datetime.now() - start_time).total_seconds()
                remaining = (end_time - datetime.now()).total_seconds() if end_time else float("inf")
                click.echo(
                    f"[watch] {elapsed / 60:.0f}min | "
                    f"event={event_counts['seen']} "
                    f"job={job_counts['started']}/{job_counts['completed']}/{job_counts['failed']} "
                    f"task={task_counts['created']}/{task_counts['terminal']}"
                )
                await _poll_once(pasloe, trenni)
                # interruptible sleep
                for _ in range(interval):
                    if stop or (end_time and datetime.now() >= end_time):
                        break
                    await asyncio.sleep(1)
        finally:
            await pasloe.aclose()
            await trenni.aclose()

    asyncio.run(_run())

    # Print summary
    elapsed = (datetime.now() - start_time).total_seconds()
    summary = _watch_summary_payload(
        duration_seconds=elapsed,
        event_counts=event_counts,
        event_type_counts=event_type_counts,
        job_counts=job_counts,
        task_counts=task_counts,
        live_snapshot=live_snapshot,
        errors=errors,
    )
    click.echo("\n=== Watch Summary ===")
    click.echo(json.dumps(summary, indent=2))


@main.command()
@click.option("--interval", default=5, show_default=True, type=int,
              help="Refresh interval in seconds")
def tui(interval: int) -> None:
    """Interactive TUI dashboard (q to quit, r to refresh)."""
    from .tui import run_tui
    api_key = os.environ.get("PASLOE_API_KEY", "")
    run_tui(pasloe_url=_PASLOE_URL, trenni_url=_TRENNI_URL,
            api_key=api_key, interval=interval)


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


@main.command()
def setup() -> None:
    """Clone or update all component repos + submodules."""
    script = Path(__file__).resolve().parent.parent / "scripts" / "setup.sh"
    if not script.exists():
        _fail(f"setup script not found: {script}")
    result = subprocess.run([str(script)], text=True)
    if result.returncode != 0:
        _fail("setup failed")
    _out({"ok": True})
