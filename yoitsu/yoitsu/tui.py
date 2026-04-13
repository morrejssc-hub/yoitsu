"""Yoitsu monitor TUI — real-time dashboard for the running stack."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static, TabbedContent, TabPane

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


def _build_task_tree(
    tasks: list[dict[str, Any]],
) -> tuple[dict[str, list[str]], list[str]]:
    """Build parent→children mapping from hierarchical task_ids.

    Returns (tree, roots) where tree maps each task_id to its direct children
    and roots is the list of task_ids with no parent in the dataset.
    """
    all_ids = {t["task_id"] for t in tasks}
    tree: dict[str, list[str]] = {tid: [] for tid in all_ids}
    roots: list[str] = []

    for tid in sorted(all_ids):
        if "/" not in tid:
            roots.append(tid)
            continue
        parent = tid.rsplit("/", 1)[0]
        if parent in tree:
            tree[parent].append(tid)
        else:
            roots.append(tid)

    return tree, roots


def _render_dag(
    tree: dict[str, list[str]],
    tasks_by_id: dict[str, dict[str, Any]],
    current_task_id: str,
    roots: list[str] | None = None,
) -> str:
    """Render ASCII DAG centered on current_task_id.

    Shows: parent chain → siblings (with current marked) → children of current.

    Args:
        tree: Parent→children mapping from _build_task_tree
        tasks_by_id: Task metadata dict keyed by task_id
        current_task_id: The task to center the DAG around
        roots: Optional list of root task_ids. If not provided, computed from tasks_by_id.
    """
    lines: list[str] = []

    def _state_tag(tid: str) -> str:
        t = tasks_by_id.get(tid, {})
        st = t.get("state", "?")
        return _state_cell(st, task=True)

    # Compute roots if not provided
    if roots is None:
        roots = [tid for tid in tasks_by_id if "/" not in tid]

    # Find parent
    parent_id = current_task_id.rsplit("/", 1)[0] if "/" in current_task_id else None
    if parent_id and parent_id in tasks_by_id:
        lines.append(f"  ↑ {parent_id}  {_state_tag(parent_id)}")
    elif parent_id:
        lines.append(f"  ↑ {parent_id}  [dim](not loaded)[/dim]")

    # Siblings (children of parent, or all roots if current is root)
    if parent_id and parent_id in tree:
        siblings = tree[parent_id]
    else:
        # current is a root — show all roots as siblings
        siblings = roots

    for i, sib in enumerate(siblings):
        is_last = i == len(siblings) - 1
        prefix = "└── " if is_last else "├── "
        marker = " ←" if sib == current_task_id else ""
        lines.append(f"  {prefix}{sib}  {_state_tag(sib)}{marker}")

        # Show children of the current task
        if sib == current_task_id and sib in tree:
            children = tree[sib]
            for j, child in enumerate(children):
                child_is_last = j == len(children) - 1
                indent = "    " if is_last else "│   "
                child_prefix = "└── " if child_is_last else "├── "
                lines.append(f"  {indent}{child_prefix}{child}  {_state_tag(child)}")

    return "\n".join(lines)


def _format_summary(
    trenni: dict[str, Any] | None,
    podman: dict[str, Any],
    llm: dict[str, Any] | None,
) -> str:
    """Format compact 2-line summary for SummaryBar."""
    parts_line1: list[str] = []
    parts_line2: list[str] = []

    # Trenni
    if trenni:
        parts_line1.append(
            f"[b]Trenni[/b] [green]{trenni.get('running_jobs', '?')}[/green]"
            f"/[dim]{trenni.get('max_workers', '?')}[/dim] running  "
            f"[yellow]{trenni.get('pending_jobs', '?')}[/yellow] pending  "
            f"ready {trenni.get('ready_queue_size', '?')}"
        )
        tasks_map = trenni.get("tasks") or {}
        if isinstance(tasks_map, dict):
            parts_line2.append(f"tasks: {len(tasks_map)}")
    else:
        parts_line1.append("[red]Trenni unreachable[/red]")

    # Podman
    if podman.get("available"):
        parts_line1.append(
            f"[b]Podman[/b] [green]{podman['running']}[/green]▶ "
            f"[dim]{podman['exited']}[/dim]✗"
        )
    else:
        parts_line1.append("[b]Podman[/b] [dim]n/a[/dim]")

    # LLM
    if llm:
        by_model = llm.get("by_model", [])
        total_input = sum(r.get("total_input_tokens", 0) or 0 for r in by_model)
        total_output = sum(r.get("total_output_tokens", 0) or 0 for r in by_model)
        total_cost = sum(r.get("total_cost", 0.0) or 0.0 for r in by_model)
        parts_line1.append(f"[bold yellow]${total_cost:.2f}[/bold yellow]")
        parts_line2.append(f"in {total_input:,.0f}  out {total_output:,.0f}")
    else:
        parts_line1.append("[red]LLM ?[/red]")

    line1 = "  │  ".join(parts_line1)
    line2 = "  │  ".join(parts_line2) if parts_line2 else ""
    return f"{line1}\n{line2}" if line2 else line1


# ── widgets ──────────────────────────────────────────────────────────────────

class SummaryBar(Static):
    """Compact 2-3 line summary strip replacing StatusPanel + LlmPanel."""

    DEFAULT_CSS = """
    SummaryBar {
        height: auto;
        max-height: 3;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    """

    content: reactive[str] = reactive("loading…", layout=True)

    def render(self) -> str:
        return self.content


# ── main app ─────────────────────────────────────────────────────────────────

class MonitorApp(App[None]):
    """Yoitsu real-time monitor."""

    TITLE = "Yoitsu Monitor"
    CSS = """
    Screen {
        layout: vertical;
    }
    #summary {
        height: auto;
        max-height: 3;
    }
    TabbedContent {
        height: 1fr;
    }
    TabPane {
        padding: 0;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab_events", "Events"),
        Binding("2", "tab_jobs", "Jobs"),
        Binding("3", "tab_tasks", "Tasks"),
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
        yield SummaryBar(id="summary")
        with TabbedContent(id="tabs", initial="tab-events"):
            with TabPane("Events", id="tab-events"):
                yield DataTable(id="events-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Jobs", id="tab-jobs"):
                yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Tasks", id="tab-tasks"):
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

    def action_tab_events(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-events"

    def action_tab_jobs(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-jobs"

    def action_tab_tasks(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-tasks"

    async def _do_refresh(self) -> None:
        try:
            await asyncio.gather(
                self._refresh_summary(),
                self._refresh_events(),
                self._refresh_jobs(),
                self._refresh_tasks(),
                return_exceptions=True,
            )
        except Exception:
            pass

    async def _refresh_summary(self) -> None:
        assert self._trenni is not None and self._pasloe is not None
        trenni_st, podman_info, llm_stats = await asyncio.gather(
            self._trenni.get_status(),
            asyncio.get_running_loop().run_in_executor(None, _podman_summary),
            self._pasloe.get_llm_stats(),
            return_exceptions=True,
        )
        # If any returned an exception, treat as None/unavailable
        if isinstance(trenni_st, Exception):
            trenni_st = None
        if isinstance(podman_info, Exception):
            podman_info = {"available": False}
        if isinstance(llm_stats, Exception):
            llm_stats = None

        bar: SummaryBar = self.query_one("#summary", SummaryBar)
        bar.content = _format_summary(trenni_st, podman_info, llm_stats)

    # ── events table ──────────────────────────────────────────────────────────

    async def _refresh_events(self) -> None:
        assert self._pasloe is not None
        events = await self._pasloe.list_events(limit=100)
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
        for j in jobs:
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
        for t in tasks:
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
