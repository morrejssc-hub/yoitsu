"""Yoitsu monitor TUI — real-time dashboard for the running stack."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static, TabbedContent, TabPane

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


def _matches_filter(row: tuple[str, ...], query: str) -> bool:
    """Return True if any cell in row contains query (case-insensitive)."""
    if not query:
        return True
    q = query.lower()
    return any(q in str(cell).lower() for cell in row)


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


# ── job detail screen ────────────────────────────────────────────────────────

class JobDetailScreen(Screen[None]):
    """Detail view for a single job, showing metadata and related events."""

    TITLE = "Job Detail"
    CSS = """
    JobDetailScreen {
        layout: vertical;
    }
    .job-meta {
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: solid $primary;
    }
    .job-events-label {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    #job-events-table {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh_detail", "Refresh"),
        Binding("t", "go_task", "Go to Task"),
    ]

    def __init__(
        self,
        job_id: str,
        pasloe: PasloeClient,
        trenni: TrenniClient,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._pasloe = pasloe
        self._trenni = trenni

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="job-meta", classes="job-meta")
        yield Label("Job Events", classes="job-events-label")
        yield DataTable(id="job-events-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#job-events-table", DataTable)
        table.add_columns("ts", "type", "source", "detail")
        self.run_worker(self._load(), exclusive=True, exit_on_error=False)

    def action_refresh_detail(self) -> None:
        self.run_worker(self._load(), exclusive=True, exit_on_error=False)

    def action_go_task(self) -> None:
        """Navigate to the task this job belongs to."""
        self.run_worker(self._go_task(), exclusive=True, exit_on_error=False)

    async def _go_task(self) -> None:
        """Fetch job to get task_id and push TaskDetailScreen."""
        job = await self._trenni.get_job(self._job_id)
        if job and job.get("task_id"):
            self.app.push_screen(TaskDetailScreen(job["task_id"], self._pasloe, self._trenni))

    async def _load(self) -> None:
        """Fetch job details and events, update display."""
        # Fetch job details from trenni
        job = await self._trenni.get_job(self._job_id)

        # Update meta widget
        meta: Static = self.query_one("#job-meta", Static)
        if job:
            state = job.get("state", "?")
            bundle = job.get("bundle", "?")
            role = job.get("role", "?")
            task_id = job.get("task_id", "-")
            created = job.get("created_at", "-")
            if created:
                created = _event_ts(created)
            meta.update(
                f"[b]Job:[/b] {self._job_id}  "
                f"[b]State:[/b] {_state_cell(state)}  "
                f"[b]Bundle:[/b] {bundle}  "
                f"[b]Role:[/b] {role}  "
                f"[b]Task:[/b] {task_id}  "
                f"[b]Created:[/b] {created}"
            )
        else:
            meta.update(f"[red]Job {self._job_id} not found[/red]")

        # Fetch events from pasloe and filter by job_id
        events = await self._pasloe.list_events(limit=100) or []
        job_events = [
            e for e in events
            if (e.get("data") or {}).get("job_id") == self._job_id
        ]

        # Update events table
        table: DataTable = self.query_one("#job-events-table", DataTable)
        table.clear()
        for event in job_events:
            table.add_row(
                _event_ts(event.get("ts")),
                _shorten(event.get("type"), 30),
                _shorten(event.get("source_id"), 18),
                _event_detail(event),
            )


# ── task detail screen ───────────────────────────────────────────────────────

class TaskDetailScreen(Screen[None]):
    """Detail view for a single task with DAG visualization."""

    CSS = """
    TaskDetailScreen {
        layout: vertical;
    }
    #task-meta {
        height: auto;
        max-height: 8;
        padding: 1 2;
        border-bottom: solid $primary;
    }
    #task-dag {
        height: auto;
        max-height: 15;
        padding: 0 2;
        border-bottom: solid $accent;
    }
    #task-jobs-label {
        background: $primary;
        color: $text;
        padding: 0 1;
        height: 1;
    }
    #task-jobs {
        height: 1fr;
    }
    #task-result {
        height: auto;
        max-height: 6;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("q", "dismiss", "Back"),
        Binding("r", "refresh_detail", "Refresh"),
        Binding("p", "go_parent", "Parent Task"),
    ]

    def __init__(self, task_id: str, pasloe: "PasloeClient", trenni: "TrenniClient") -> None:
        super().__init__()
        self._task_id = task_id
        self._pasloe = pasloe
        self._trenni = trenni
        self._all_tasks: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(f"[b]Task:[/b] {self._task_id}\nloading…", id="task-meta")
        yield Static("loading DAG…", id="task-dag")
        yield Label(" Jobs for this Task", id="task-jobs-label")
        yield DataTable(id="task-jobs", cursor_type="row", zebra_stripes=True)
        yield Static("", id="task-result")
        yield Footer()

    def on_mount(self) -> None:
        table: DataTable = self.query_one("#task-jobs", DataTable)
        table.add_columns("job_id", "state", "role")
        self.run_worker(self._load(), exclusive=False, exit_on_error=False)

    async def action_refresh_detail(self) -> None:
        self.run_worker(self._load(), exclusive=True, exit_on_error=False)

    def action_go_parent(self) -> None:
        """Navigate to parent task in the DAG."""
        if "/" in self._task_id:
            parent_id = self._task_id.rsplit("/", 1)[0]
            self.app.push_screen(TaskDetailScreen(parent_id, self._pasloe, self._trenni))

    async def _load(self) -> None:
        meta_widget: Static = self.query_one("#task-meta", Static)
        dag_widget: Static = self.query_one("#task-dag", Static)
        table: DataTable = self.query_one("#task-jobs", DataTable)
        result_widget: Static = self.query_one("#task-result", Static)

        task_detail, all_tasks, task_jobs = await asyncio.gather(
            self._trenni.get_task(self._task_id),
            self._trenni.get_tasks(),
            self._trenni.get_jobs(task_id=self._task_id),
            return_exceptions=True,
        )

        # Task metadata
        if isinstance(task_detail, Exception) or not task_detail:
            meta_widget.update(f"[red]Task {self._task_id} not found[/red]")
            return

        state = str(task_detail.get("state", ""))
        lines = [
            f"[b]Task:[/b] {task_detail.get('task_id', '')}  {_state_cell(state, task=True)}",
            f"[b]Bundle:[/b] {task_detail.get('bundle', '')}",
            f"[b]Goal:[/b] {task_detail.get('goal', '')}",
        ]
        if task_detail.get("eval_spawned"):
            lines.append(f"[b]Eval job:[/b] {task_detail.get('eval_job_id', '')}")
        meta_widget.update("\n".join(lines))

        # DAG
        if isinstance(all_tasks, Exception) or not all_tasks:
            dag_widget.update("[dim]DAG unavailable[/dim]")
        else:
            tasks_by_id = {t["task_id"]: t for t in all_tasks}
            tree, roots = _build_task_tree(all_tasks)
            dag_text = _render_dag(tree, tasks_by_id, self._task_id, roots)
            dag_widget.update(f"[b]DAG[/b]\n{dag_text}")
            self._all_tasks = all_tasks

        # Jobs
        table.clear()
        if not isinstance(task_jobs, Exception) and task_jobs:
            for j in task_jobs:
                job_state = str(j.get("state", ""))
                table.add_row(
                    _shorten(j.get("job_id"), 24),
                    _state_cell(job_state),
                    j.get("role", ""),
                    key=j.get("job_id", ""),
                )

        # Result
        result = task_detail.get("result")
        if result:
            r_lines = []
            sem = result.get("semantic", {})
            if sem.get("verdict"):
                r_lines.append(f"[b]Verdict:[/b] {sem['verdict']}  {_shorten(sem.get('summary', ''), 60)}")
            trace = result.get("trace", [])
            if trace:
                r_lines.append(f"[b]Trace:[/b] {len(trace)} entries")
                for entry in trace[:5]:
                    r_lines.append(
                        f"  {entry.get('role', '?')}: {entry.get('outcome', '?')} — {_shorten(entry.get('summary', ''), 50)}"
                    )
            result_widget.update("\n".join(r_lines) if r_lines else "")
        else:
            result_widget.update("")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a job in this task → push job detail."""
        row_key = str(event.row_key.value)
        if row_key:
            self.app.push_screen(JobDetailScreen(row_key, self._pasloe, self._trenni))


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
        layout: vertical;
        padding: 0;
    }
    DataTable {
        height: 1fr;
    }
    .filter-input {
        dock: top;
        height: 1;
        display: block;
    }
    .filter-input.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("slash", "filter", "Filter"),
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
        # Data caching for client-side filtering
        self._events_data: list[tuple[str, ...]] = []
        self._jobs_data: list[tuple[str, ...]] = []
        self._tasks_data: list[tuple[str, ...]] = []
        self._filter_text: dict[str, str] = {
            "tab-events": "",
            "tab-jobs": "",
            "tab-tasks": "",
        }

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SummaryBar(id="summary")
        with TabbedContent(id="tabs", initial="tab-events"):
            with TabPane("Events", id="tab-events"):
                yield Input(placeholder="filter…", id="filter-events", classes="filter-input hidden")
                yield DataTable(id="events-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Jobs", id="tab-jobs"):
                yield Input(placeholder="filter…", id="filter-jobs", classes="filter-input hidden")
                yield DataTable(id="jobs-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Tasks", id="tab-tasks"):
                yield Input(placeholder="filter…", id="filter-tasks", classes="filter-input hidden")
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

        self.set_interval(self._interval, self._schedule_refresh)
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """Sync wrapper for interval callback to properly run async refresh."""
        self.run_worker(self._do_refresh(), exclusive=True, exit_on_error=False)

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

    def action_filter(self) -> None:
        """Toggle filter input for the current tab."""
        tabs = self.query_one("#tabs", TabbedContent)
        active_tab = tabs.active
        filter_id = f"filter-{active_tab.replace('tab-', '')}"
        try:
            filter_input = self.query_one(f"#{filter_id}", Input)
            if filter_input.has_class("hidden"):
                filter_input.remove_class("hidden")
                filter_input.focus()
            else:
                filter_input.add_class("hidden")
                filter_input.value = ""
                self._filter_text[active_tab] = ""
                self._apply_filter(active_tab)
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle filter input changes."""
        input_widget = event.input
        if input_widget.id and input_widget.id.startswith("filter-"):
            tab_id = f"tab-{input_widget.id.replace('filter-', '')}"
            self._filter_text[tab_id] = event.value
            self._apply_filter(tab_id)

    def on_key(self, event: Key) -> None:
        """Handle Escape key to clear/hide filter."""
        if event.key == "escape":
            tabs = self.query_one("#tabs", TabbedContent)
            active_tab = tabs.active
            filter_id = f"filter-{active_tab.replace('tab-', '')}"
            try:
                filter_input = self.query_one(f"#{filter_id}", Input)
                if not filter_input.has_class("hidden"):
                    filter_input.add_class("hidden")
                    filter_input.value = ""
                    self._filter_text[active_tab] = ""
                    self._apply_filter(active_tab)
            except Exception:
                pass

    def _apply_filter(self, tab_id: str) -> None:
        """Re-filter cached data for the given tab."""
        query = self._filter_text.get(tab_id, "")
        if tab_id == "tab-events":
            table: DataTable = self.query_one("#events-table", DataTable)
            table.clear()
            for row in self._events_data:
                if _matches_filter(row, query):
                    table.add_row(*row)
        elif tab_id == "tab-jobs":
            table = self.query_one("#jobs-table", DataTable)
            table.clear()
            for row in self._jobs_data:
                # row[0] is full job_id (key), row[1:] are display columns
                if _matches_filter(row[1:], query):
                    table.add_row(row[1], row[2], row[3], row[4], row[5], key=row[0])
        elif tab_id == "tab-tasks":
            table = self.query_one("#tasks-table", DataTable)
            table.clear()
            for row in self._tasks_data:
                # row[0] is full task_id (key), row[1:] are display columns
                if _matches_filter(row[1:], query):
                    table.add_row(row[1], row[2], row[3], row[4], key=row[0])

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter on a table row."""
        table = event.data_table
        if table.id == "jobs-table":
            row_key = str(event.row_key.value)
            if row_key and self._pasloe and self._trenni:
                self.push_screen(JobDetailScreen(row_key, self._pasloe, self._trenni))
        elif table.id == "tasks-table":
            row_key = str(event.row_key.value)
            if row_key and self._pasloe and self._trenni:
                self.push_screen(TaskDetailScreen(row_key, self._pasloe, self._trenni))

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
            self._events_data = []
            return
        # Cache the data
        self._events_data = [
            (
                _event_ts(event.get("ts")),
                _shorten(event.get("type"), 30),
                _shorten(event.get("source_id"), 18),
                _event_refs(event.get("data") or {}),
                _event_detail(event),
            )
            for event in events
        ]
        # Apply current filter
        self._apply_filter("tab-events")

    # ── jobs table ────────────────────────────────────────────────────────────

    async def _refresh_jobs(self) -> None:
        assert self._trenni is not None
        jobs = await self._trenni.get_jobs()
        table: DataTable = self.query_one("#jobs-table", DataTable)
        table.clear()
        if not jobs:
            self._jobs_data = []
            return
        # Cache the data (full job_id as first element for lookup)
        self._jobs_data = [
            (
                j.get("job_id", ""),  # full job_id for row key
                _shorten(j.get("job_id"), 16),
                _state_cell(str(j.get("state") or "")),
                _shorten(j.get("bundle"), 16),
                _shorten(j.get("role"), 12),
                _shorten(j.get("task_id"), 16),
            )
            for j in jobs
        ]
        # Apply current filter, using job_id as row key
        query = self._filter_text.get("tab-jobs", "")
        for row in self._jobs_data:
            if _matches_filter(row[1:], query):  # filter on display columns
                table.add_row(row[1], row[2], row[3], row[4], row[5], key=row[0])

    # ── tasks table ──────────────────────────────────────────────────────────

    async def _refresh_tasks(self) -> None:
        assert self._trenni is not None
        tasks = await self._trenni.get_tasks()
        table: DataTable = self.query_one("#tasks-table", DataTable)
        table.clear()
        if not tasks:
            self._tasks_data = []
            return
        # Cache the data (full task_id as first element for lookup)
        self._tasks_data = [
            (
                t.get("task_id", ""),  # full task_id for row key
                _shorten(t.get("task_id"), 16),
                _state_cell(str(t.get("state") or ""), task=True),
                _shorten(t.get("bundle"), 16),
                _shorten(t.get("goal"), 60),
            )
            for t in tasks
        ]
        # Apply current filter, using task_id as row key
        query = self._filter_text.get("tab-tasks", "")
        for row in self._tasks_data:
            if _matches_filter(row[1:], query):  # filter on display columns
                table.add_row(row[1], row[2], row[3], row[4], key=row[0])


# ── entry point ──────────────────────────────────────────────────────────────

def run_tui(pasloe_url: str, trenni_url: str, api_key: str, interval: int = 5) -> None:
    app = MonitorApp(
        pasloe_url=pasloe_url,
        trenni_url=trenni_url,
        api_key=api_key,
        interval=interval,
    )
    app.run()
