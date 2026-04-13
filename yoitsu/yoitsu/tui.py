"""Yoitsu monitor TUI — real-time dashboard for the running stack."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Label, Static

from .client import PasloeClient, TrenniClient


# ── helpers ──────────────────────────────────────────────────────────────────

def _podman_summary() -> dict[str, Any]:
    """Return podman container counts; safe if podman not available."""
    import subprocess
    try:
        out = subprocess.run(
            ["podman", "ps", "-a", "--format", "{{.State}}"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode != 0:
            return {"available": False}
        lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        running = sum(1 for s in lines if s.lower().startswith("running"))
        exited = sum(1 for s in lines if s.lower().startswith("exited"))
        return {"available": True, "running": running, "exited": exited, "total": len(lines)}
    except Exception:
        return {"available": False}


def _shorten(s: str | None, n: int) -> str:
    if not s:
        return ""
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _event_ts(raw: Any) -> str:
    if isinstance(raw, datetime):
        return raw.strftime("%H:%M:%S")
    text = str(raw or "")
    if not text:
        return ""
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%H:%M:%S")
    except ValueError:
        if "T" in text:
            return text.split("T", 1)[1][:8]
        return text[:8]


def _event_refs(data: dict[str, Any]) -> str:
    refs: list[str] = []
    if data.get("job_id"):
        refs.append(f"job:{_shorten(str(data['job_id']), 12)}")
    if data.get("task_id"):
        refs.append(f"task:{_shorten(str(data['task_id']), 12)}")
    return " ".join(refs) or "-"


def _event_detail(event: dict[str, Any]) -> str:
    data = event.get("data") or {}
    if data.get("summary"):
        return _shorten(str(data["summary"]), 72)
    if data.get("error"):
        return _shorten(str(data["error"]), 72)
    if data.get("goal"):
        return _shorten(str(data["goal"]), 72)
    parts: list[str] = []
    if data.get("role"):
        parts.append(f"role={data['role']}")
    if data.get("bundle"):
        parts.append(f"bundle={data['bundle']}")
    if data.get("reason"):
        parts.append(f"reason={data['reason']}")
    if data.get("state"):
        parts.append(f"state={data['state']}")
    return _shorten(" ".join(parts), 72)


def _state_cell(state: str, *, task: bool = False) -> str:
    style = (
        "green" if state == "completed"
        else "red" if state in ("failed", "cancelled", "eval_failed")
        else "yellow" if state in ("running", "pending", "ready", "evaluating")
        else ""
    )
    return f"[{style}]{state}[/{style}]" if style else state


# ── widgets ──────────────────────────────────────────────────────────────────

class StatusPanel(Static):
    """Left top panel: Trenni + Podman."""

    DEFAULT_CSS = """
    StatusPanel {
        border: round $primary;
        padding: 0 1;
        height: 10;
        width: 1fr;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:  # type: ignore[override]
        return self.content


class LlmPanel(Static):
    """Right top panel: LLM usage stats."""

    DEFAULT_CSS = """
    LlmPanel {
        border: round $accent;
        padding: 0 1;
        height: 10;
        width: 1fr;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:  # type: ignore[override]
        return self.content


# ── main app ─────────────────────────────────────────────────────────────────

class MonitorApp(App[None]):
    """Yoitsu real-time monitor."""

    TITLE = "Yoitsu Monitor"
    CSS = """
    Screen {
        layout: vertical;
    }
    #top-row {
        height: 10;
    }
    #events-label, #jobs-label, #tasks-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
    }
    #events-table {
        height: 1fr;
        border: none;
    }
    #jobs-table {
        height: 1fr;
        border: none;
    }
    #tasks-table {
        height: 1fr;
        border: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(
        self,
        pasloe_url: str,
        trenni_url: str,
        api_key: str,
        interval: int = 5,
    ) -> None:
        super().__init__()
        self._pasloe_url = pasloe_url
        self._trenni_url = trenni_url
        self._api_key = api_key
        self._interval = interval
        self._pasloe: PasloeClient | None = None
        self._trenni: TrenniClient | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="top-row"):
            yield StatusPanel(id="status-panel")
            yield LlmPanel(id="llm-panel")
        yield Label(" Event Layer", id="events-label")
        yield DataTable(id="events-table", cursor_type="row", zebra_stripes=True)
        yield Label(" Job Layer", id="jobs-label")
        yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
        yield Label(" Task Layer", id="tasks-label")
        yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self._pasloe = PasloeClient(url=self._pasloe_url, api_key=self._api_key)
        self._trenni = TrenniClient(url=self._trenni_url)

        events_table: DataTable = self.query_one("#events-table", DataTable)
        events_table.add_columns("ts", "type", "source", "refs", "detail")

        jobs_table: DataTable = self.query_one("#jobs-table", DataTable)
        jobs_table.add_columns("job_id", "state", "bundle", "role", "task_id")

        tasks_table: DataTable = self.query_one("#tasks-table", DataTable)
        tasks_table.add_columns("task_id", "state", "bundle", "goal")

        self.set_interval(self._interval, self._do_refresh)
        self.run_worker(self._do_refresh(), exclusive=False, exit_on_error=False)

    async def on_unmount(self) -> None:
        if self._pasloe:
            await self._pasloe.aclose()
        if self._trenni:
            await self._trenni.aclose()

    async def action_refresh(self) -> None:
        await self._do_refresh()

    async def _do_refresh(self) -> None:
        try:
            await asyncio.gather(
                self._refresh_status(),
                self._refresh_llm(),
                self._refresh_events(),
                self._refresh_jobs(),
                self._refresh_tasks(),
                return_exceptions=True,
            )
        except Exception:
            pass

    # ── status panel ─────────────────────────────────────────────────────────

    async def _refresh_status(self) -> None:
        assert self._trenni is not None
        st = await self._trenni.get_status()
        lines: list[str] = []
        if st:
            lines.append(
                f"[b]Trenni[/b]  jobs [green]{st.get('running_jobs', '?')}"
                f"[/green]/[dim]{st.get('max_workers', '?')}[/dim]  "
                f"pending [yellow]{st.get('pending_jobs', '?')}[/yellow]  "
                f"ready {st.get('ready_queue_size', '?')}"
            )
            tasks_map: dict = st.get("tasks", {}) or {}
            lines.append(f"        tasks in memory: {len(tasks_map)}")
        else:
            lines.append("[red]Trenni  unreachable[/red]")

        ps = await asyncio.get_running_loop().run_in_executor(None, _podman_summary)
        if ps.get("available"):
            lines.append(
                f"\n[b]Podman[/b]  running [green]{ps['running']}[/green]  "
                f"exited [dim]{ps['exited']}[/dim]  "
                f"total {ps['total']}"
            )
        else:
            lines.append("\n[b]Podman[/b]  [dim]not available[/dim]")

        panel: StatusPanel = self.query_one("#status-panel", StatusPanel)
        panel.content = "\n".join(lines)

    # ── llm panel ────────────────────────────────────────────────────────────

    async def _refresh_llm(self) -> None:
        assert self._pasloe is not None
        stats = await self._pasloe.get_llm_stats()
        panel: LlmPanel = self.query_one("#llm-panel", LlmPanel)
        if not stats:
            panel.content = "[red]LLM stats  unreachable[/red]"
            return

        lines = ["[b]LLM Usage[/b]"]
        by_model = stats.get("by_model", [])
        total_input = total_output = total_cost = 0.0
        for row in by_model:
            model = _shorten(row.get("model", ""), 24)
            inp = row.get("total_input_tokens", 0) or 0
            out = row.get("total_output_tokens", 0) or 0
            cost = row.get("total_cost", 0.0) or 0.0
            total_input += inp
            total_output += out
            total_cost += cost
            lines.append(
                f"  [dim]{model}[/dim]  in {inp:,}  out {out:,}  "
                f"[yellow]${cost:.3f}[/yellow]"
            )
        if by_model:
            lines.append(
                f"\n  [b]total[/b]  in {total_input:,.0f}  out {total_output:,.0f}  "
                f"[bold yellow]${total_cost:.3f}[/bold yellow]"
            )
        else:
            lines.append("  [dim](no data yet)[/dim]")
        panel.content = "\n".join(lines)

    # ── events table ──────────────────────────────────────────────────────────

    async def _refresh_events(self) -> None:
        assert self._pasloe is not None
        events = await self._pasloe.list_events(limit=40)
        table: DataTable = self.query_one("#events-table", DataTable)
        table.clear()
        if not events:
            return
        for event in events:
            data = event.get("data") or {}
            table.add_row(
                _event_ts(event.get("ts")),
                _shorten(event.get("type"), 30),
                _shorten(event.get("source_id"), 18),
                _event_refs(data),
                _event_detail(event),
            )

    # ── jobs table ────────────────────────────────────────────────────────────

    async def _refresh_jobs(self) -> None:
        assert self._trenni is not None
        jobs = await self._trenni.get_jobs()
        table: DataTable = self.query_one("#jobs-table", DataTable)
        table.clear()
        if not jobs:
            return
        for j in jobs[:50]:
            state = str(j.get("state") or "")
            table.add_row(
                _shorten(j.get("job_id"), 16),
                _state_cell(state),
                _shorten(j.get("bundle"), 16),
                _shorten(j.get("role"), 12),
                _shorten(j.get("task_id"), 16),
            )

    # ── tasks table ──────────────────────────────────────────────────────────

    async def _refresh_tasks(self) -> None:
        assert self._trenni is not None
        tasks = await self._trenni.get_tasks()
        table: DataTable = self.query_one("#tasks-table", DataTable)
        table.clear()
        if not tasks:
            return
        for t in tasks[:50]:
            state = str(t.get("state") or "")
            table.add_row(
                _shorten(t.get("task_id"), 16),
                _state_cell(state, task=True),
                _shorten(t.get("bundle"), 16),
                _shorten(t.get("goal"), 60),
            )


# ── entry point ──────────────────────────────────────────────────────────────

def run_tui(pasloe_url: str, trenni_url: str, api_key: str, interval: int = 5) -> None:
    app = MonitorApp(
        pasloe_url=pasloe_url,
        trenni_url=trenni_url,
        api_key=api_key,
        interval=interval,
    )
    app.run()
