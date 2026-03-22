# Self-Evolving Agent System — Architecture

Draft v0.4 · 2026-03

## Core Principle

The system splits the Agent into an **immutable skeleton (Runtime)** and a **freely evolvable muscle (evo repo)**. The evo repo is a normal Git repository; self-evolution uses the same mechanics as external tasks — branch, modify, commit, merge.

Two real data sources: **Git repositories** and the **event stream**. All other state is derived and can be rebuilt from these.

Two evolution axes:
- **Context assembly** — how to select and compose relevant context
- **Workflow orchestration** — how to assign prompts and coordinate sub-tasks

## Permission Model

| Layer | Content | Permission |
|-------|---------|------------|
| Locked | Runtime code, event gateway, sandbox, EventStore, schema validation | Agent cannot touch. Changes require PR. |
| Stable | spawn tool interface, evo directory structure conventions | Agent can use but not modify. |
| Free | All files in the evo repo (prompts, contexts, tools, roles) | Agent evolves freely via Git. |

The boundary between Stable and Free is enforced by convention, not code. The Supervisor detects violations by comparing `changed_files` in the event stream.

## Workflow Primitives

The only orchestration primitive is **fork-join + failure trigger**:

- Initiator spawns child tasks (specifying role and parameters)
- Trigger condition: `all_complete` or `any_failed` → resume initiator
- Initiator decides next steps on resume — it may fork again

This single primitive expresses: sequential chains, parallel batches, conditional branching, nested forks, and iteration. No additional primitives are needed.

## Self-Evolution Loop

### Dual Gate Validation

- **Hard gate (immediate):** new evo version must pass CI/smoke test and the first job must start successfully. Failure triggers automatic rollback by the Supervisor.
- **Soft gate (record now, enforce later):** quantifiable metrics (LLM call rounds, task completion time, etc.) are recorded in the event stream. Version progression events include `changed_files` for precise A/B comparison.

### Evaluation Anchors

To avoid Goodhart's Law, no single metric is the optimization target:

- Automated tests (hard metrics, always on)
- External output quality (objective measure)
- LLM cross-review (on demand; scoring prompt is outside evolution scope)
- Human feedback (high latency, highest trust)

## System Invariants

- **Single source of truth:** Git repos + event stream only. Everything else is derived.
- **Skeleton/muscle separation:** Runtime is immutable. Evo repo is freely evolvable.
- **Transparent event capture:** Agent cannot touch event emission. The Runtime emits on its behalf.
- **Three-layer permissions:** locked / stable / free boundaries enforced by Supervisor.
- **Job terminal determinism:** every job ends in success or failure. No infinite hangs.
- **Branch isolation:** job output does not affect trunk until merged.

## Implementation Phases

- **Phase 0 — Minimal loop:** Fixed-role Agent → events + branch → Supervisor merges.
- **Phase 1 — Evo repo:** Prompts and context templates move from hardcoded to repo. Role resolution, version reading.
- **Phase 2 — Context assembly:** Event stream query tools. Agent retrieves context from the stream.
- **Phase 3 — Fork-join:** Supervisor orchestration. Agent spawns child tasks.
- **Phase 4 — Self-evolution:** Agent modifies evo repo. Hard gate enabled.
- **Phase 5 — Optimization loop:** Context template optimization tasks. Soft gate comparison.
