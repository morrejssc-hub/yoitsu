# ADR-0006: Task-Level Publication via Planner Tool

- Status: Proposed
- Date: 2026-03-28
- Related: ADR-0002, ADR-0003

## Context

The current publication model operates at the job level:

- Worker jobs commit and push to a branch (`strategy="branch"`).
- Eval jobs skip publication (`strategy="skip"`).
- Planner jobs skip publication.

This was designed before the task/job two-layer model was fully realized.
The result is that completed tasks leave branches in the target repository
but never create pull requests or trigger any merge flow. The branch is the
terminal artifact.

For agent-produced work to be actionable, the system needs a task-level
publication step that creates a pull request when a task is semantically
confirmed as complete.

Three design constraints shape this decision:

1. **Job vs task semantics must remain separate.** Job-level publication is
   mechanical workspace persistence. Task-level delivery is an agent-driven
   logical decision. These must not be conflated.
2. **`publication_fn` was designed to decouple delivery format from the
   runtime.** Deliverables are not always git repos — they can be reports,
   API calls, or other artifacts. Introducing PR logic into `publication_fn`
   or the supervisor would re-couple the runtime to git.
3. **PR creation is a semantic decision, not a mechanical one.** The agent
   must decide _whether_ to create a PR, what title and body to use, and
   which base branch to target. This is analogous to how `spawn` lets the
   planner decide decomposition — the decision belongs to the agent, not
   the infrastructure.

## Decision

### 1. `create_pr` Is a Builtin Planner Tool

PR creation is exposed as a new builtin tool `create_pr`, available to the
planner agent in join mode. It follows the same pattern as `spawn`:

- `spawn` lets the planner create child tasks (agent decides decomposition).
- `create_pr` lets the planner create pull requests (agent decides delivery).

Both are agent-driven actions that the runtime merely executes.

### 2. Join Mode Is the Natural Site

The planner's join phase is the correct location because:

- It runs after all child tasks have completed and been evaluated.
- It has access to `join_context`, which includes each child's eval verdict,
  `git_ref` (branch:sha), semantic summary, and criteria results.
- It already makes the terminal semantic decision about the parent task
  (complete vs. needs more work).
- It is the only agent in the lifecycle that has the full picture: which
  children passed, which branches exist, what the original goal was.

The eval agent remains a pure assessor — it does not gain side effects.
The supervisor remains delivery-agnostic — it does not learn about PRs.

### 3. Tool Contract

```
create_pr(
    repo:        str   # Repository URL (e.g. "https://github.com/org/repo")
    head_branch: str   # Branch containing the work (from child's git_ref)
    base_branch: str   # Target branch for the PR (e.g. "main")
    title:       str   # PR title
    body:        str   # PR body (markdown)
)
```

Returns: `{"pr_url": "https://github.com/org/repo/pull/42"}`

The planner extracts `head_branch` from the child's `git_ref` in
`join_context`. The runtime also renders a `publication_target` line for
publishable child outputs:

```
publication_target: repo=https://github.com/org/repo base_branch=main head_branch=palimpsest/job/...
```

The planner uses this published target directly rather than guessing repo or
base branch. The planner decides the PR title and body based on the task goal
and eval results.

### 4. Job-Level Publication Is Unchanged

| Layer | Trigger | Strategy | Artifact |
|-------|---------|----------|----------|
| Job (worker) | Job completes successfully | `branch` | Git branch + commit |
| Job (eval) | — | `skip` | None |
| Job (planner) | — | `skip` | None |

Worker jobs still auto-commit and push to a branch. This is mechanical
workspace persistence — the `publication_fn` contract is unchanged.

The `git_ref` field retains its existing semantics: always `branch:sha`,
never a PR URL.

### 5. Supervisor Is Unchanged

The supervisor does not gain PR awareness. It continues to:

- Build eval jobs with `publication_overrides={"strategy": "skip"}`.
- Parse eval verdicts from `data.summary` via `_semantic_from_eval_event`.
- Schedule continuation planner jobs in join mode when children complete.

PR creation is invisible to the supervisor — it is a tool call within a
planner job, like `spawn`.

### 6. Implementation Scope

| Change | Location | Notes |
|--------|----------|-------|
| New `create_pr` builtin tool | `palimpsest/runtime/tools.py` | Add to `BUILTIN_TOOL_NAMES`, implement GitHub API call, hand-craft schema (like `spawn`) |
| Planner role registers `create_pr` | `evo/roles/planner.py` | Add to tools list |
| Join context publication target | `evo/contexts/loaders.py` | Render `repo`, `base_branch`, and `head_branch` from child task traces |
| Join prompt guidance | `evo/prompts/planner-join.md` | When and how to call `create_pr` |
| Clean up unused `PublicationConfig` fields | `yoitsu-contracts/config.py` | Deferred follow-up; not required for the tool path |

### 7. GitHub API Access

PR creation requires authenticated access to the hosting platform. The
tool uses the same git token already available via `git_token_env` in the
job container. For GitHub repositories, it calls the GitHub REST API.

No new credentials are needed. The job container already has network access
and the auth token.

### 8. Multi-Child Task Publication

When a parent task has multiple child tasks:

- The join planner sees all children's eval results in `join_context`.
- It can call `create_pr` once per child that passed eval, creating one PR
  per independently-publishable unit of work.
- It can also choose to create fewer PRs if the task semantics warrant it.

The planner makes this decision — not the infrastructure. This matches the
vertical-slice decomposition model while leaving room for the planner to
adapt.

### 9. Eval-Failed Tasks

When all children fail eval, the join planner sees this in `join_context`
and does not call `create_pr`. The worker branches still exist in the
remote repository for manual inspection, but no PRs are created.

This is an agent decision, not a runtime constraint — the planner can see
the verdicts and act accordingly.

### 10. Failure Semantics

If `create_pr` fails (API error, auth issue, network failure):

- The tool returns an error to the planner.
- The planner can report the failure in its response but still mark the
  task as complete — the work itself is done, only delivery failed.
- This is non-fatal: the task's semantic status is independent of PR
  creation success.

This avoids the problem where `publication_fn` failure would cause
`agent.job.failed` — the PR call is a tool invocation, not a job
lifecycle hook.

## Consequences

### Positive

- Task completion produces an actionable artifact (PR) without manual
  intervention.
- Publication is gated by semantic eval — only verified work reaches the
  planner join phase with passing verdicts.
- Follows the established pattern: agent-driven decisions are tools
  (`spawn`, `create_pr`), mechanical guarantees are runtime hooks
  (`publication_fn`).
- Supervisor and runner remain delivery-agnostic. No git coupling is added
  to the orchestration layer.
- `publication_fn` contract is unchanged — future non-git deliverables
  remain possible without conflicting with PR logic.
- PR parameters (title, body, base branch) are decided by the planner with
  full task context, not by configuration or convention.
- Failure is non-fatal and visible to the agent, not a silent runtime error.

### Tradeoffs

- The planner must be prompted to call `create_pr` correctly. This is a
  prompt engineering concern, not an infrastructure guarantee. However,
  `spawn` already works this way and has proven reliable.
- One PR per child task may produce multiple PRs for a multi-child
  decomposition. The planner can consolidate, but the default behavior
  mirrors the decomposition structure.
- `create_pr` is GitHub-specific initially. Other platforms require
  additional tool implementations.

### Non-Goals

- Automatic merge of PRs (PRs are for review, not auto-merge).
- Consolidated multi-branch PRs (planner can create multiple PRs; branch
  merging is a future extension).
- Non-GitHub hosting platforms (GitHub-first; extensible later).
- PR template customization beyond what the planner decides to write.
- Runtime-enforced PR creation (this is an agent decision, not a guarantee).
