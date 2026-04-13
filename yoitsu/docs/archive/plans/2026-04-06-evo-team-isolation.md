# Evo Team Isolation (Phase 1.5)

**Status:** Draft, ready to execute after Task 9 smoke test

## Background

The current evo layout assumes a "global roles/tools/contexts + per-team
override" model (ADR-0011 D2 shadow semantics). In practice this has produced
two problems:

1. **Almost nothing is actually shared.** `evo/roles/` contains stub-quality
   generic roles (`worker`, `planner`, `optimizer`, `evaluator`) that no real
   job runs as-is — every team that matters provides its own. The "global
   layer" is dead weight that exists only so the shadow lookup has something
   to fall back to.

2. **The override mechanism breaks isolation it was supposed to provide.**
   Resolution order (`teams/<team>/X` → `evo/X`) means a missing team-specific
   role silently resolves to a generic global one, masking configuration
   errors. Worse, it couples teams through a shared namespace: renaming a
   global role can break unrelated teams, and there is no way to express
   "this name only exists for team X" without polluting the global view.

3. **The two-layer search complicates A/B disentanglement.** Stable
   infrastructure (`teams/factorio/lib/`) needs to be importable as a real
   Python package. A flat per-team tree is much easier to make
   `pyproject.toml`-installable than a tree with shadow semantics.

The user has decided to abandon the global+override model. Each team should
be **fully isolated** — its own roles, tools, contexts, lib code, and
evolved artifacts, with no fallback to a shared layer.

This is **not** Phase 2 multi-bundle (one repo per team). That migration is
still gated on needing a second task domain. This plan only restructures the
single-evo-repo MVP so that:

- Phase 2 becomes a near-mechanical lift (each `teams/<name>/` subtree
  becomes one bundle repo, no shadow logic to untangle).
- Today's `ModuleNotFoundError: No module named 'teams'` class of issues is
  resolved at the architectural level, not just by sys.path injection.
- Agent write surface (path allowlist for implementer/optimizer) is
  physically separated from human-reviewed infrastructure.

## Non-Goals

- Multi-repo bundle materialization (Phase 2).
- Changing how evo is materialized at a SHA (`_materialize_evo_root` stays).
- Changing `git_publication` semantics.
- Touching any team other than `factorio` (there is only one today).

## Target Layout

```
evo/                                   (still one git repo, still SHA-pinned)
├── pyproject.toml                     (NEW: declares the namespace package root)
├── teams/
│   ├── __init__.py                    (NEW: namespace marker)
│   └── factorio/
│       ├── __init__.py
│       ├── roles/                     (worker.py, implementer.py, optimizer.py,
│       │                               planner.py, evaluator.py — ALL of them,
│       │                               nothing falls back to a global layer)
│       ├── tools/                     (factorio_call_script.py, ...)
│       ├── contexts/                  (factorio_scripts.py, ...)
│       ├── prompts/                   (optimizer.md, ...)
│       ├── lib/                       (rcon.py, bridge.py — A-class infra,
│       │                               importable as
│       │                               `teams.factorio.lib.rcon`)
│       └── evolved/                   (NEW: B-class agent write surface)
│           ├── scripts/               (Lua scripts produced by implementer)
│           └── tool_specs/            (future: agent-authored tool descriptors)
└── (evo/roles/, evo/tools/, evo/contexts/, evo/prompts/ all DELETED)
```

Key properties:

- **No global layer.** `evo/roles/` etc. cease to exist. Every loader takes
  a team name and looks **only** under `teams/<team>/`. A missing role for a
  team is a hard error, not a silent fallback.
- **`teams/` is a real Python package** rooted at `evo/`. With `evo` on
  `sys.path` (which runner.py already does as of the Task 9 hotfix),
  `from teams.factorio.lib.rcon import RCONClient` Just Works for every
  module loaded by the importlib machinery.
- **`evolved/` is the only agent-writable subtree.** Implementer's path
  allowlist (Task 7) tightens to `teams/<team>/evolved/**`. Lib, roles,
  tools, contexts are human-review-only.
- **Phase 2 lift is trivial.** A bundle repo is exactly the contents of one
  `teams/<name>/` subtree plus its own `pyproject.toml`. No shadow logic to
  port, no global layer to merge.

## Plan

### Task 1 — Strip global layer from palimpsest loaders

Files: `palimpsest/runtime/roles.py`, `runtime/tools.py`, `runtime/contexts.py`

- `RoleManager.__init__` requires `team`; remove the `default` fallback path.
  Resolution becomes a single lookup under `teams/<team>/roles/<name>.py`.
  Missing role → raise, do not search `evo/roles/`.
- `RoleManager.list_definitions` lists only team roles. Drop the merge with
  `super().list_definitions()`.
- `resolve_tool_functions(evo_path, team, requested)` scans only
  `teams/<team>/tools/`. Drop the global `evo/tools/` scan and the shadow
  merge.
- `contexts.load_context_providers` scans only `teams/<team>/contexts/`.
- Delete `RoleMetadataReader` if it becomes unused after the global layer
  goes away (or keep it as `RoleManager`'s base if there's no other
  consumer).
- Update any docstring/ADR reference to "team-specific shadows global" — the
  semantics are now "team is the only namespace".

**Verification:** existing palimpsest unit tests will break in the places
that exercise global fallback. Update them to construct `RoleManager` with
an explicit team and drop fallback assertions. Do not preserve the old
behavior behind a flag — this is a clean break.

### Task 2 — Move generic roles into the factorio team (or delete)

Files: `evo/roles/*.py`, `evo/teams/factorio/roles/`

For each file in `evo/roles/`:

- `worker.py`: already shadowed by `teams/factorio/roles/worker.py`. Delete
  the global one.
- `planner.py`, `optimizer.py`, `evaluator.py`: check whether they are
  meaningfully used. If a real factorio job depends on them, copy (do NOT
  symlink) into `teams/factorio/roles/` and adapt to factorio context. If
  unused, delete.

After this task `evo/roles/` is empty and can be removed.

Apply the same audit to `evo/tools/`, `evo/contexts/`, `evo/prompts/` if any
of them exist with content (per current `ls` they are absent — verify and
remove the empty dirs).

**Verification:** grep for `evo/roles`, `evo/tools`, `evo/contexts` across
palimpsest and evo. Should return zero hits in code (only historical doc
references allowed).

### Task 3 — Promote `teams/` to a real package + add `evo/pyproject.toml`

Files: `evo/pyproject.toml` (new), `evo/teams/__init__.py` (new),
`evo/teams/factorio/__init__.py` (verify exists),
`evo/teams/factorio/lib/__init__.py` (verify exists).

- Add a minimal `pyproject.toml` at `evo/` declaring `teams` as a package.
  This is documentation/tooling-facing — runner.py already injects `evo/`
  into `sys.path`, so runtime resolution does not depend on installation.
  But having `pyproject.toml` makes the package discoverable by linters,
  IDEs, and future Phase 2 bundle installers.
- Confirm every directory under `teams/factorio/` that contains Python files
  has an `__init__.py`. (`lib/` already does; `roles/`, `tools/`,
  `contexts/` should be added if missing.)
- The runner.py sys.path injection from the Task 9 hotfix stays. Document
  in a comment that this is the single-bundle equivalent of Phase 2's
  per-bundle injection.

**Verification:** from a Python REPL with `evo/` on `sys.path`, both of
these must succeed:

```python
from teams.factorio.lib.rcon import RCONClient
from teams.factorio.lib.bridge import ...
```

### Task 4 — Create `evolved/` and migrate scripts

Files: `evo/teams/factorio/evolved/scripts/`,
`evo/teams/factorio/evolved/tool_specs/`,
plus any code that references the current scripts location.

- Create `evo/teams/factorio/evolved/scripts/` and move existing Lua scripts
  there. (Per current `ls`, `teams/factorio/scripts/` does not actually
  exist yet — the plan doc mentioned it but Task 5 may have used a different
  path. Locate the real script home and migrate.)
- Update the `factorio_scripts` context provider to read from
  `teams/<team>/evolved/scripts/`.
- Update the `factorio_call_script` tool's path resolution likewise.
- Update the implementer role's path allowlist (Task 7 deliverable) to
  `teams/<team>/evolved/**` only.
- Update `factorio-agent` repo's `scripts` symlink target if Task 5 wired
  one up.

**Verification:** an end-to-end smoke run where the implementer writes a
Lua file must land it under `teams/factorio/evolved/scripts/`, the worker
must be able to call it, and an attempt to write to
`teams/factorio/lib/anything.py` from the implementer must be rejected by
the allowlist.

### Task 5 — Update plan/ADR documentation

Files: `docs/plans/2026-04-06-factorio-tool-evolution-mvp.md`,
`docs/plans/2026-04-06-multi-bundle-evo-phase2.md`,
any ADR mentioning team shadowing (ADR-0011 D2 in particular).

- Remove all references to "team-specific shadows global" semantics.
  Replace with "each team is a fully isolated namespace under `teams/`".
- Update the Phase 2 plan to note that the bundle migration now consists of
  lifting one `teams/<name>/` subtree per bundle repo, with no global layer
  to reconcile.
- Add a short ADR (or amend ADR-0011) recording the decision to abandon the
  global+override model and the reasons (dead weight, false isolation,
  packaging friction).

### Task 6 — Re-run Task 9 smoke test under the new layout

After Tasks 1–5, re-run the factorio smoke test end-to-end. Confirm:

- Worker role loads without sys.path tricks beyond the runner's existing
  injection.
- Implementer can write a Lua script and the worker can execute it via
  RCON.
- Optimizer can read the resulting observation and propose a refinement.
- `git_publication` pushes the change to `evo/teams/factorio/evolved/...`
  on a branch, and the diff is contained entirely within `evolved/`.

## Sequencing notes

- Tasks 1 and 2 must land together — stripping the loader fallback without
  moving roles into the team will break startup.
- Task 3 (`pyproject.toml` + `__init__.py`) can land before or after, it is
  independent.
- Task 4 should follow Task 3 so `evolved/` is created in a tree that is
  already a real package.
- Task 5 (docs) lands last so it describes what actually shipped.

## Out of scope / explicitly deferred

- Multi-repo bundles (Phase 2). This plan deliberately keeps the single
  `evo/` repo and just disciplines its internal structure.
- Installing `evo` as a real pip package into the palimpsest container.
  `sys.path` injection is sufficient for the MVP and Phase 2 will revisit
  the install story.
- Per-team Python virtualenvs. If two teams ever need conflicting deps, that
  is a Phase 2+ problem.
