# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Structure

Yoitsu is a monorepo containing four interdependent packages plus a CLI and bundle definitions:

| Directory | Package | Role |
|---|---|---|
| `pasloe/` | `pasloe` | Append-only event store (FastAPI + SQLAlchemy) |
| `palimpsest/` | `palimpsest` | Single-job LLM agent runtime |
| `trenni/` | `trenni` | Scheduler and isolation control plane |
| `yoitsu-contracts/` | `yoitsu-contracts` | Shared wire contracts (events, config, conditions) |
| `yoitsu/` | `yoitsu` | User-facing CLI wrapping the stack |
| `evo/` | — | Evolving bundle definitions (roles, prompts, contexts) |
| `deploy/` | — | Quadlet/Podman deployment units |

All packages use `uv` and `hatchling`. `yoitsu-contracts` is an editable local dependency in every package's `pyproject.toml`.

## Common Commands

Each package is developed independently. Run from the package root:

```bash
# Install deps for a specific package
cd trenni && uv sync

# Run all tests in a package
cd yoitsu && uv run pytest

# Run a single test file
cd yoitsu && uv run pytest tests/test_cli.py

# Run a single test by name
cd yoitsu && uv run pytest tests/test_cli.py -k test_submit

# Start the yoitsu CLI (from repo root)
uv run yoitsu --help
uv run yoitsu up
uv run yoitsu submit <task.yaml>
uv run yoitsu watch
```

Build container images (from `deploy/podman/`):
```bash
podman build -f yoitsu-python-base.Containerfile -t localhost/yoitsu-python-base:dev ../..
podman build -f palimpsest-job.Containerfile -t localhost/yoitsu-palimpsest-job:dev ../..
```

## Architecture: Data Flow

```
User → yoitsu CLI → Trenni (scheduler)
                        ↓ spawns
                    Palimpsest (job runtime, runs in Podman)
                        ↓ emits events
                    Pasloe (event store)
                        ↑ Trenni polls for triggers/completion
```

**Pasloe** is the single source of truth. All state changes are recorded as events. Trenni replays Pasloe on startup for crash recovery; it holds no durable state of its own.

**Palimpsest** executes exactly one job per process. Its 4-stage pipeline: `preparation → context assembly → LLM+tool loop → finalization`. Completion is detected by idle behavior (two consecutive tool-free LLM responses), not by an explicit `task_complete` call — see ADR-0002.

**Trenni** manages the task DAG: evaluates spawn conditions, enqueues jobs, manages isolation backends (Podman), and runs post-hoc observation analysis after job completion.

**yoitsu-contracts** defines `events.py`, `config.py`, `conditions.py`, `events.py`, `role_metadata.py`, and HTTP client helpers shared by all four services.

## Palimpsest Runtime Internals

Key modules in `palimpsest/palimpsest/`:

- `runner.py` — top-level pipeline orchestrator
- `stages/context.py` — assembles system prompt + context sections; **silent failure**: if a `system` path ends in `.md`/`.txt` but the file doesn't exist, it uses the literal path string as the system message (no warning)
- `stages/interaction.py` — LLM + tool call loop with budget enforcement
- `runtime/roles.py` — `@role` decorator, `JobSpec`, `context_spec`
- `runtime/llm.py` — `UnifiedLLMGateway` (native OpenAI + Anthropic SDKs, no litellm)
- `runtime/tools.py` — built-in tool implementations including `spawn`

## Bundle System (`evo/`)

A bundle is a Python package providing role definitions, prompts, and context providers. The active bundles are `evo/default/` and `evo/factorio/`.

**Role definition pattern** (`evo/factorio/roles/planner.py` is a good reference):
```python
@role(name="planner", output_authority="analysis", needs=[], ...)
def planner(**params) -> JobSpec:
    return JobSpec(
        context_fn=context_spec(system="prompts/planner.md", sections=[...]),
        tools=["spawn"],
    )
```

Key ADRs governing bundle behavior:
- **ADR-0018**: `needs=[]` for analysis roles (no capability setup/finalize lifecycle)
- **ADR-0019**: `output_authority` values: `"analysis"` (read-only, spawn only) vs `"live_runtime"` (can write/publish)
- **ADR-0021**: Bundle trust boundary — what bundles can and cannot do

Prompt files live at `evo/<bundle>/prompts/<role>.md` and are referenced in roles as `"prompts/<role>.md"` (relative path resolved from the bundle root).

## Trenni Internals

Key modules in `trenni/trenni/`:

- `supervisor.py` (~98KB) — main orchestrator, handles the event polling loop, spawn expansion, observation aggregation
- `state.py` — in-memory task/job state reconstructed from Pasloe replay
- `spawn_handler.py` — evaluates spawn conditions and creates child job records
- `workspace_manager.py` — creates git worktrees for job execution; sanitizes `job_id` by replacing `/` with `-` for use in directory names
- `bundle_repository.py` — clones/fetches bundle repos and manages worktree lifecycle via `tempfile.mkdtemp`
- `control_plane_executor.py` — launches Palimpsest jobs as subprocesses or Podman containers

## Deployment (Quadlet)

Production uses systemd Quadlet units in `deploy/quadlet/`. The stack runs as a single Podman pod (`yoitsu.pod`). Key env files: `deploy/pasloe.env.example`, `deploy/trenni.env.example`.

Dev config: `deploy/quadlet/trenni.dev.yaml` — controls LLM model, bundle sources, workspace paths, Podman socket, and observation thresholds.

## Architectural Decisions

Active ADRs are in `docs/adr/`. The most load-bearing for day-to-day work:

- **ADR-0006**: Task-level publication and join-mode planner pattern
- **ADR-0015**: Bundle-as-repo (bundles live in external git repos, fetched at runtime)
- **ADR-0016**: Capability model (setup/finalize lifecycle, hallucination gate)
- **ADR-0019**: Role output authority (who can write what)
- **ADR-0021**: Bundle trust boundary and capability surface

Full architecture reference: `docs/architecture.md`.
