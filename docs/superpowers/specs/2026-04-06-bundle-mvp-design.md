# Bundle MVP Design

**Status:** Approved, ready for implementation planning
**Date:** 2026-04-06
**Supersedes:** `docs/plans/2026-04-06-evo-team-isolation.md` (Phase 1.5),
`docs/plans/2026-04-06-multi-bundle-evo-phase2.md` (old multi-repo Phase 2 vision)

## Voice

**This document describes the target state.** Every layout diagram, API
example, loader signature, and success criterion below is **what will
exist after implementation**, not current reality. The "Background" section
is the only part describing the current codebase; everything from
"Architecture" onward is prescriptive.

Concretely, at the time of writing:
- `evo/teams/factorio/roles/` contains only `worker.py` and `implementer.py`.
  The optimizer/planner/evaluator roles appearing in diagrams below are
  examples of what a bundle **may** contain, not roles that currently exist.
- `RoleManager`, `ToolLoader`, `ContextLoader`, and `RuntimeContext` all use
  `team` parameters today and implement two-layer (team-specific shadows
  global) resolution per ADR-0011.
- `TeamDefinition` with `worker_roles` / `planner_role` / `eval_role` fields
  is actively enforced by `TeamManager.resolve()`.
- Implementer's current allowlist is `teams/factorio/scripts/` and
  `mod/scripts/`, not `evolved/scripts/`.

All of that is what this spec **changes**. This is a breaking, all-at-once
architectural shift with no backwards compatibility, no deprecation window,
and no data migration. `team` is **deleted** from trenni's control-plane
semantics, not renamed.

## Background

The current evo/trenni split leaks task-domain knowledge into trenni infrastructure.
Concrete symptoms observed on 2026-04-06:

- `supervisor.py:1480-1511` categorizes roles into `planner` / `evaluator` / `worker`
  buckets and enforces a fixed topology (exactly one planner, at most one evaluator,
  at least one worker). Factorio's actual role set (worker, implementer, optimizer,
  planner, evaluator) does not fit this mold cleanly — `implementer.py` and
  `worker.py` both declare `role_type="worker"`, so categorization is ambiguous.
- `_DEFAULT_TEAM_DEFINITION` lacks a `worker_roles` field, and production config has
  no team definitions, so the system runs on an incomplete hardcoded fallback.
- Tasks submitted without a `role` go through planner-driven decomposition; the
  planner routes execution subtasks to `implementer` (whose workspace has no git
  remote) instead of `worker`, causing publication to fail and the system to retry
  indefinitely. On 2026-04-06 this burned 15 subtask attempts on a single
  iron-chest placement task with zero successful executions.
- The `evo/roles/` global layer is dead weight: every role that matters is
  team-specific, and the fallback path silently masks configuration errors.

Each time a task domain has needed a new role topology, trenni has been modified
to accommodate it. This is not sustainable — role topology belongs to the task
domain, not to the generic harness.

## Goal

Move all task-domain concerns (role catalog, topology, routing, publication
strategy) into a **bundle**: a self-contained subtree under `evo/<bundle>/`
that owns its own roles and is consumed by trenni through a minimal behavioral
contract.

**`team` is deleted from trenni's control-plane semantics.** It is not
renamed to `bundle`. `bundle` is only an addressing unit for the evo
directory — it does not carry `TeamDefinition`, topology, `worker_roles`,
`planner_role`, `eval_role`, or any other runtime semantic that `team`
carries today. Trenni stops knowing what a team *is*; it only knows how
to locate a role file inside a bundle directory and run it.

Trenni's only business entry point becomes `(bundle, role, goal, params)`:
locate `evo/<bundle>/roles/<role>.py`, load it, run it with the provided
goal and params. No categorization, no topology validation, no automatic
routing. The runtime still generically loads `tools/` and `contexts/` from
the bundle when a role's JobSpec references them — that is generic
artifact loading, not business-topology interpretation.

## Non-Goals

- **Multi-repo bundle distribution.** Bundle is a logical unit; whether each
  bundle is its own git repo is a physical packaging question deferred to a
  later phase. MVP keeps everything inside the existing `evo/` repo.
- **Manifest files (bundle.yaml / pyproject per bundle).** Pure directory
  convention is sufficient. Code > config.
- **Automatic role routing.** Task submissions must specify `role` explicitly.
  Missing `role` is a hard 400.
- **Enforced planner/evaluator topology.** Bundles freely choose which roles
  to include. Self-evolution topology is per-bundle business; trenni provides
  templates as guidance, not constraints.
- **Centralized publication declaration.** Publication strategy remains an
  attribute of the role file itself (`worker_publication`, `implementer_publication`).
- **Adapting `2026-04-04-autonomous-review-loop-output-closure.md`.** That plan
  assumes the current supervisor consumption path; bundle MVP will break its
  assumptions. Re-adapting it is a follow-up, not in this scope.
- **Backwards compatibility.** Direct replacement. No deprecation window, no
  data migration, no config shims.

## Architecture

### Bundle = self-contained subtree (Target Post-Migration Layout)

A bundle is a directory under `evo/<bundle>/`. The target layout for the
factorio bundle, **after migration**, is:

```
evo/
└── factorio/                      (the bundle, top-level under evo)
    ├── __init__.py
    ├── roles/                     (role catalog — files named by role)
    │   ├── worker.py              (RCON execution, skip publication)
    │   └── implementer.py         (writes Lua, git publication + allowlist)
    ├── tools/                     (factorio_call_script.py, ...)
    ├── contexts/                  (factorio_scripts.py, ...)
    ├── prompts/                   (worker.md, implementer.md, ...)
    ├── lib/                       (rcon.py, bridge.py — human-reviewed infra)
    └── evolved/                   (agent write surface)
        └── scripts/               (Lua scripts produced by implementer)
```

Only `worker.py` and `implementer.py` appear in the post-migration state
because those are the only roles currently implemented. If the factorio
bundle later grows an optimizer, planner, or evaluator, those are
per-bundle choices and are not required by this spec. Other bundles are
free to have a different set of roles entirely; trenni imposes no minimum
or maximum.

Key properties:

- **No global layer.** `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/`
  cease to exist. Loaders only look under `evo/<bundle>/`. Missing role is a hard
  error, not a silent fallback.
- **No `teams/` wrapper.** Bundle name is the first-level directory under `evo/`.
  Python import path is `factorio.lib.rcon`, not `teams.factorio.lib.rcon`.
- **`evolved/` is the only agent-writable subtree.** Implementer's path allowlist
  is tightened to `evo/<bundle>/evolved/**`. Under MVP, agents **only** write
  to `evo/<bundle>/evolved/**`. Any subsequent flow that moves an approved
  evolved artifact into a mod-executable location (e.g. syncing
  `evolved/scripts/foo.lua` into the factorio mod's real script directory,
  registering it with the mod loader, running review gates) is a
  **per-bundle internal process** and is **not** part of trenni's contract.
  Trenni never writes into `lib/`, `tools/`, `contexts/`, `roles/`, or any
  mod directory, and neither do agents — those are human-reviewed surfaces.
  This explicitly overrides the current `teams/factorio/scripts/` +
  `mod/scripts/` allowlist in `evo/teams/factorio/roles/implementer.py`.
- **Role catalog is discovered by filename.** `evo/<bundle>/roles/*.py` is the
  entire catalog. The filename (minus `.py`) is the canonical role name. No
  manifest, no registration.

### Worker vs Implementer: both kept

These two roles have similar prompts but different publication strategies, and
the separation is load-bearing:

- **worker.py** — executes in-game operations via RCON. `publication=skip`.
  Never produces git commits. Workspace is ephemeral scratch.
- **implementer.py** — writes Lua scripts into `evolved/scripts/`. Uses
  `git_publication` with a path allowlist. All file changes must pass
  allowlist validation before commit. Workspace requires a real git remote.

The ideal workflow is: worker drafts scripts during or after execution, but
scripts must pass human review before landing in the mod. Separate roles allow
publication policy to diverge even when the underlying prompt is similar.
This is an intentional instance of the principle "similar prompt + different
publication = different role."

**Why not a single role with a `mode` parameter?** Because the differences
between worker and implementer are **safety boundaries**, not prompt
variants: different publication guardrails, different workspace
requirements (ephemeral scratch vs. real git remote), different writable
surfaces, different human-review requirements. Folding these into a mode
flag on one role would move safety-critical policy into runtime parameters
where a bug or misconfiguration could let an executor write where only a
reviewed implementer should. Keeping them as distinct files means the
allowlist, publication strategy, and tool set are statically attached to
the role identity and cannot be swapped at call time.

The earlier instinct to delete one as "duplication" was based on a
misreading. Both stay. The only deletion in this area is the *global*
`evo/roles/worker.py`, which is genuinely legacy.

### Trenni contract

Trenni's only **business entry point** into a bundle is the role file at
`evo/<bundle>/roles/<role>.py`. That is the single unit of task-domain
knowledge trenni looks up by name.

This does **not** mean trenni ignores the rest of the bundle at runtime.
When the loaded role produces a JobSpec that references tools or contexts,
the runtime generically loads them from `evo/<bundle>/tools/` and
`evo/<bundle>/contexts/` (and prompts from `evo/<bundle>/prompts/`, lib
imports from `evo/<bundle>/lib/`). That generic artifact loading is not
business-topology interpretation — trenni neither categorizes tools, nor
validates that a context exists for a given role, nor enforces any shape
on what a bundle chooses to put in those directories. It just resolves
names that role code asked for.

**Task submission API** (replaces the current `{team, goal, ...}` shape):

```
{bundle: <name>, role: <name>, goal: <string>, params: <object>}
```

- `bundle` and `role` are both required. Missing either is a hard 400
  at the API boundary. Trenni does not infer a default, does not run a
  planner, does not categorize.
- `goal` is the human-readable task description handed to the role
  prompt, equivalent to today's `goal` field.
- `params` is a bundle-defined object that the role interprets itself.
  It is a transport envelope; trenni does not inspect it.

Field mapping vs. today's spawn API: current fields like
`repo`, `init_branch`, scheduling hints etc. remain part of the underlying
JobSpec, but they are produced **by the role code** from `(goal, params)`,
not taken from the submission envelope. This keeps the submission contract
minimal and moves all task-shape decisions into the bundle.

Subtask spawning: role code that wants to decompose or chain work submits
new tasks with explicit `(bundle, role, goal, params)` through the same
API. Trenni treats them identically to externally submitted tasks.

## Changes

### Deletions

- `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/` (global layer)
- `supervisor.py:1480-1511` role categorization block
- `_DEFAULT_TEAM_DEFINITION` and all references to `worker_roles`,
  `planner_role`, `eval_role` fields on team definitions
- `RoleManager` global fallback path
- `docs/plans/2026-04-06-evo-team-isolation.md` → moved to `docs/archive/`
- `docs/plans/2026-04-06-multi-bundle-evo-phase2.md` → moved to `docs/archive/`

### Renames

- Directory: `evo/teams/factorio/` → `evo/factorio/`
- Python imports: `teams.factorio.*` → `factorio.*` (repo-wide)
- Vocabulary: `team` → `bundle` in API field names, config keys, error
  messages, logs, documentation. `config/trenni.yaml` `teams:` section
  becomes `bundles:`.

### New behavior

- `RoleManager(bundle=...)`, `ToolLoader(bundle=...)`, `ContextLoader(bundle=...)`
  only search `evo/<bundle>/<kind>/`. Missing → raise.
- Task submission requires `role` field. Missing → 400.
- Supervisor execution path: resolve `(bundle, role)` → load role file →
  run. No categorization, no topology validation.

### Unchanged

- Publication strategies (`worker_publication`, `implementer_publication`)
  remain as attributes of role files.
- SHA pinning, evo materialization (`_materialize_evo_root`), and sys.path
  injection mechanisms.
- `evolved/` conventions and implementer allowlist semantics (just rooted at
  `evo/<bundle>/evolved/` instead of `evo/teams/<team>/evolved/`).
- `factorio-tool-evolution-mvp.md` main line (Task 9 smoke verified) — bundle
  MVP is its infrastructure upgrade, not a replacement.

## Factorio Bundle: Target Post-Migration State

After the structural changes, `evo/factorio/roles/` contains:

- `worker.py` — RCON execution (from current `teams/factorio/roles/worker.py`,
  which is already the RCON executor)
- `implementer.py` — Lua script author (from current
  `teams/factorio/roles/implementer.py`)

These are the only two roles currently implemented. If the factorio bundle
later adds optimizer, planner, or evaluator roles, those are per-bundle
choices and are not required by this spec.

Tonight's iron-chest task becomes:
```
{bundle: factorio, role: worker, goal: "place iron-chest at (0,0), (2,0), (4,0)", params: {}}
```
Zero decomposition, zero implementer misrouting, zero publication failure.

## Known Breakage

`docs/plans/2026-04-04-autonomous-review-loop-output-closure.md` assumes the
existing supervisor consumption path in `_handle_job_done` and a specific
shape for spawning follow-up tasks. Bundle MVP changes the task submission
contract (explicit `role` required) and removes the categorization logic it
implicitly relies on.

This plan is **retained, not archived**, because the goal (closing the
optimizer → follow-up task loop) remains valid. A follow-up task after
bundle MVP lands will re-adapt its consumption logic to the new API:
ReviewProposal parsing stays the same, but the spawn path must explicitly
specify `(bundle, role)` for each follow-up task.

## Implementation tasks (outline)

Detailed plan will be produced by `writing-plans` skill. Outline only:

1. **Archive conflicting plans** — move Phase 1.5 and old Phase 2 docs to
   `docs/archive/`.
2. **Delete global evo layer** — remove `evo/roles/`, `evo/tools/`,
   `evo/contexts/`, `evo/prompts/`. Grep-verify no references remain.
3. **Flatten bundle layout** — move `evo/teams/factorio/` to `evo/factorio/`,
   delete `evo/teams/` wrapper.
4. **Repo-wide rename** — `teams.factorio.` → `factorio.` (Python imports);
   `teams/factorio/` → `factorio/` (path literals in configs, docs, tools);
   `team` → `bundle` (API field names, config keys, messages, logs).
5. **Loader refactor** — `RoleManager` / `ToolLoader` / `ContextLoader`
   accept `bundle`, search `evo/<bundle>/<kind>/` only, no fallback.
6. **Supervisor simplification** — delete `supervisor.py:1480-1511` role
   categorization, delete `_DEFAULT_TEAM_DEFINITION`, remove all references
   to `worker_roles` / `planner_role` / `eval_role`.
7. **API change** — task submission requires `role` field. Missing → 400.
   Update CLI, API handlers, and any submission helpers.
8. **Smoke verification** —
   (a) `(bundle=factorio, role=worker)` runs the ping script via RCON (Task 9 equivalent).
   (b) `(bundle=factorio, role=implementer)` writes a Lua script and commits it
   through `implementer_publication` to `evo/factorio/evolved/scripts/`.
   (c) Iron-chest placement task succeeds end-to-end.

## Success criteria

- Submitting `{bundle: factorio, role: worker, payload: ...}` runs worker
  directly without decomposition or misrouting.
- Submitting a task without `role` returns 400 immediately.
- `supervisor.py` contains zero references to `planner_role`, `worker_roles`,
  `eval_role`, or `_DEFAULT_TEAM_DEFINITION`.
- `evo/roles/`, `evo/tools/`, `evo/contexts/`, `evo/prompts/`, and `evo/teams/`
  do not exist.
- `grep -r "teams\.factorio\|teams/factorio" yoitsu palimpsest trenni` returns
  zero hits in code (documentation archive references allowed).
- Factorio smoke test (Task 9) still passes under the new layout.
- An implementer-produced Lua script lands in `evo/factorio/evolved/scripts/`
  on a publication branch, and an attempt to write outside `evolved/` is
  rejected by the allowlist.
