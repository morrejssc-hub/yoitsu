# TUI Refactor: Visibility & Interactivity

**Date**: 2026-04-13
**Status**: Approved
**File**: `yoitsu/tui.py` (370 lines, full rewrite)

## Problem

The current TUI crams five sections into a ~40-line terminal: two 10-line summary panels + three `1fr` DataTables. Each table gets ~8 visible rows. Essentially nothing is readable.

No interactivity exists beyond quit and manual refresh — no way to drill into a job or task, no filtering, no DAG navigation.

## Design

### Layout: Compact Summary + Tabbed Data

Replace the current layout with:

1. **Summary strip** (3 lines) — merges StatusPanel + LlmPanel into a dense bar
2. **TabbedContent** — three tabs (Events, Jobs, Tasks), each gets full remaining terminal height
3. **Footer** — keybindings

```
┌─ Yoitsu Monitor ──────────────────────────────────── HH:MM:SS ┐
│ Trenni 2/4 running  3 pending  │ Podman 5▶ 2✗  │ $1.23 in120k │
├─ [1 Events] [2 Jobs] [3 Tasks] ───────────────────── / filter ─┤
│                                                                 │
│   (active tab's DataTable — full remaining height, scrollable)  │
│                                                                 │
├─ q Quit  r Refresh  1-3 Tabs  Enter Detail  / Filter ──────────┤
└─────────────────────────────────────────────────────────────────┘
```

**Summary strip content** (single `Static` widget, 3 lines max):
- Line 1: Trenni status (running/max, pending, ready) + Podman counts
- Line 2: LLM cost total + token totals (input/output)
- Falls back to `[red]unreachable[/red]` per service

### Tab 1: Events

Same DataTable as current (`ts`, `type`, `source`, `refs`, `detail`) but now gets full height. No row limit — fetch up to 100 events. Existing helper functions (`_event_ts`, `_event_refs`, `_event_detail`) are reused.

### Tab 2: Jobs

DataTable columns: `job_id`, `state`, `bundle`, `role`, `task_id`. No 50-row cap — show all jobs. State cells use existing `_state_cell` color coding.

**Enter on a row** → push a `JobDetailScreen`:
- Header: job_id, state (colored), role, bundle
- Task: task_id (link-like, navigable)
- Parent: parent_job_id
- Condition: condition string if present
- Context: join/eval context dump (formatted, not raw JSON)
- Events: recent events filtered from Pasloe where `data.job_id == selected_job_id`, displayed in a small DataTable

Data sources:
- `TrenniClient.get_job(job_id)` → metadata, parent_job_id, condition, job_context
- `PasloeClient.list_events(limit=30)` → client-side filter by job_id in event data

### Tab 3: Tasks

DataTable columns: `task_id`, `state`, `bundle`, `goal`. No row cap — show all tasks.

**Enter on a row** → push a `TaskDetailScreen`:
- Header: task_id, state (colored), bundle
- Goal: full text (not truncated)
- DAG section (see below)
- Jobs: list of jobs belonging to this task (from Trenni filtered by task_id)
- Result/trace: if task is terminal, show verdict + trace entries

Data sources:
- `TrenniClient.get_task(task_id)` → metadata, eval info, job_order, result
- `TrenniClient.get_jobs(task_id=task_id)` → jobs for this task
- `TrenniClient.get_tasks()` → all tasks (for DAG computation)

### DAG Visualization

Task IDs encode hierarchy: `root/child_token/grandchild_token`. Parent is derived via `task_id.rsplit('/', 1)[0]`.

The DAG section in TaskDetailScreen renders an ASCII tree:

```
─── DAG ───
↑ root_task                     [completed]
  ├── sibling_a                 [completed]
  ├── THIS_TASK ←               [running]
  └── sibling_b                 [pending]
      └── grandchild_1          [evaluating]
```

Implementation:
- Parse all task_ids to build a tree structure (dict of parent → children)
- Locate the selected task in the tree
- Render: parent chain upward to root, siblings at same level, direct children
- State coloring applies to each node
- **Enter on a DAG node** → navigate to that task's detail screen (push another TaskDetailScreen)

### Filtering

`/` key activates an `Input` widget at the top of the active tab. Typing filters rows by case-insensitive substring match across all visible columns.

- `Escape` clears filter and hides input
- Filter state is per-tab (switching tabs preserves each tab's filter)
- Applied client-side on the already-fetched data

### Detail Screens

Both `JobDetailScreen` and `TaskDetailScreen` are Textual `Screen` subclasses pushed onto the screen stack.

- `Escape` or `q` pops back to the main dashboard
- Data is fetched once on mount (not auto-refreshed)
- `r` re-fetches detail data
- Navigation between detail screens (task→job, job→task, task→related task) pushes new screens onto the stack; Escape pops back through the chain

### Keybindings

| Key | Context | Action |
|-----|---------|--------|
| `q` | Any | Quit app (or pop screen if in detail) |
| `r` | Any | Refresh current view |
| `1` | Main | Switch to Events tab |
| `2` | Main | Switch to Jobs tab |
| `3` | Main | Switch to Tasks tab |
| `Enter` | Jobs/Tasks tab | Open detail screen |
| `/` | Main tabs | Activate filter input |
| `Escape` | Filter active | Clear filter |
| `Escape` | Detail screen | Pop back to main |

### Data Flow

```
MonitorApp
├── SummaryBar (Static)
│   ← _refresh_summary() merges Trenni status + Podman + LLM stats
├── TabbedContent
│   ├── EventsTab (DataTable)
│   │   ← _refresh_events()
│   ├── JobsTab (DataTable + optional Input filter)
│   │   ← _refresh_jobs()
│   └── TasksTab (DataTable + optional Input filter)
│       ← _refresh_tasks()
└── Footer

JobDetailScreen (pushed)
├── Static (metadata)
├── Static (DAG-lite: just shows task_id link)
├── DataTable (job events)
└── ← fetches on mount via get_job() + list_events()

TaskDetailScreen (pushed)
├── Static (metadata + goal)
├── Static (DAG tree)
├── DataTable (task's jobs)
├── Static (result/trace if terminal)
└── ← fetches on mount via get_task() + get_jobs() + get_tasks()
```

### Refresh Behavior

- Main dashboard: `set_interval(interval, _do_refresh)` continues as before
- `_do_refresh` uses `asyncio.gather` for summary + all three tabs' data (keeps inactive tabs current for instant tab switching)
- Detail screens: fetch once on mount, `r` to re-fetch

### Error Handling

Same pattern as current: each refresh method catches exceptions independently. Summary bar shows `[red]unreachable[/red]` per failed service. Tables show empty state gracefully.

## Architecture

Single file `yoitsu/tui.py` remains — this is a monitoring tool, not a framework. Expected size ~600-700 lines after refactor.

Components:
- `SummaryBar(Static)` — replaces StatusPanel + LlmPanel
- `MonitorApp(App)` — main app with tabbed layout
- `JobDetailScreen(Screen)` — job drill-down
- `TaskDetailScreen(Screen)` — task drill-down with DAG
- Helper functions — existing ones reused, new `_build_dag_tree()` and `_render_dag()` added

No new dependencies. No new files. No changes to client.py — all needed API methods already exist.

## What This Does NOT Include

- Real-time streaming/websocket (still polling)
- Log tailing within TUI
- Task creation/cancellation from TUI
- Persistent filter presets
- Custom color themes
