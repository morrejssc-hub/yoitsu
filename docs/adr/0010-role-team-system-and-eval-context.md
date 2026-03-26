# ADR-0010: 2026-03-26 Role/Team System, Planner And Evaluator Roles, Eval Context

- Status: Accepted, implementation pending
- Date: 2026-03-26
- Related: ADR-0006, ADR-0007, ADR-0009

## Context

The evolvable layer (`evo/`) currently contains a single `default` role.
ADR-0006 introduced eval jobs and ADR-0009 removed `task_complete`, but the
role and context infrastructure needed to support planners, evaluators, and
role-scoped task decomposition does not yet exist.

Several gaps:

- There is no planner role to decompose high-level goals into spawned subtasks
  with deliverables and verification criteria.
- There is no evaluator role to assess task outputs against those criteria.
- `RoleDefinition` lacks a `description` field, so roles cannot self-describe
  their capabilities to a planner.
- All roles are globally visible; there is no scoping mechanism to present a
  planner with only the relevant subset of roles.
- Eval jobs need context providers that differ fundamentally from work jobs:
  job execution traces, structural verdicts, and workspace access to the
  actual git output (not agent-reported events, which may contain
  hallucinations).

## Decision

### 1. `RoleDefinition` extension

Add a `description` field:

```python
@dataclass
class RoleDefinition:
    name: str
    description: str            # one-line capability summary for planner
    prompt: str
    contexts: list[dict[str, Any]]
    tools: list[str]
```

All existing and new roles must provide a description.

### 2. `TeamDefinition`

A team is a named, scoped composition of roles. Teams live in `evo/teams/`
and are Python modules following the same pattern as roles:

```python
# evo/teams/backend.py
from palimpsest.runtime import TeamDefinition

team = TeamDefinition(
    name="backend",
    description="Backend development and review",
    roles=["implementer", "reviewer", "researcher"],
    planner_role="planner",
    eval_role="evaluator",
)
```

- `roles`: list of role names available to the planner within this team
- `planner_role`: which role to use for the planning job (resolved from
  `evo/roles/`)
- `eval_role`: default evaluator role; used when `eval_spec.role` is omitted

Roles are defined independently in `evo/roles/`. Teams only reference them
by name. A role may appear in multiple teams.

### 3. Trigger → team → planner routing

Triggers specify a team:

```json
{"team": "backend", "goal": "Implement OAuth2 login"}
```

Trenni resolves the team definition, extracts `planner_role`, and launches
the initial planning job with that role. The team name is propagated through
the task hierarchy so child tasks inherit team context.

If no team is specified, a system default team is used.

### 4. `available_roles` context provider

A new context provider renders the roles available to the planner, scoped
to the current team:

```python
@context_provider("available_roles")
def available_roles(
    evo_root: str,
    job_config: JobConfig,
    description: str = "Available Roles",
) -> str:
    """Render role names and descriptions for the current team."""
    # Load team definition from job_config or team context
    # For each role in team.roles, load RoleDefinition and render:
    #   - name
    #   - description
    #   - tools list
    ...
```

The planner sees capability summaries, not internal prompt or context
configuration.

### 5. Planner role

```python
# evo/roles/planner.py
role = RoleDefinition(
    name="planner",
    description="Decomposes goals into concrete subtasks with deliverables and verification criteria",
    prompt="prompts/planner.md",
    contexts=[
        {"type": "task_description"},
        {"type": "available_roles"},
        {"type": "file_tree", "max_files": 200, "exclude": [".git", "__pycache__", ".venv"]},
        {"type": "version_history", "limit": 10},
    ],
    tools=[
        "read_file",
        "list_files",
    ],
)
```

The planner:

- Receives the high-level goal and available roles as context
- Explores the codebase with read-only tools and bash to understand scope
- Calls `spawn` with child tasks, each specifying:
  - `prompt`: concrete task description
  - `role`: selected from team's available roles
  - `eval_spec`: deliverables and verification criteria
- Stops calling tools when done; the interaction loop's idle detection
  (ADR-0009) handles exit
- Does NOT write code or produce file artifacts

The planner's spawn interface is minimal:

```python
spawn(tasks=[
    {
        "prompt": "Implement OAuth2 login endpoint",
        "role": "implementer",
        "eval_spec": {
            "deliverables": ["POST /auth/login endpoint", "token refresh flow"],
            "criteria": ["tests pass", "no hardcoded secrets"]
        }
    },
])
```

All other JobSpec fields (repo, init_branch, evo_sha, llm, workspace,
publication) are inherited from the parent job or resolved from role
defaults.

### 6. Evaluator role

```python
# evo/roles/evaluator.py
role = RoleDefinition(
    name="evaluator",
    description="Assesses task outputs against deliverables and verification criteria",
    prompt="prompts/evaluator.md",
    contexts=[
        {"type": "task_description"},
        {"type": "eval_context"},
        {"type": "job_trace"},
        {"type": "file_tree", "max_files": 200},
    ],
    tools=[
        "read_file",
        "list_files",
    ],
)
```

The evaluator:

- Receives goal, deliverables, criteria, structural verdict, and child eval
  results through context
- Has workspace access to the actual git output (checkout of work branch)
- Can run bash commands (tests, linting) to verify criteria
- Produces a verdict summary; the interaction loop captures it on idle exit

### 7. Meta jobs and repoless pipeline degradation

Jobs fall into two categories:

**Work jobs** (implementer, reviewer, etc.): have a specific `repo`, create
branches, produce git artifacts through publication.

**Meta jobs** (planner, root eval): have no `repo`. They consume context
and events to make decisions, not to produce code.

The existing four-stage pipeline (workspace → context → interaction →
publication) gracefully degrades when `repo=""`:

- **Workspace setup**: creates an empty temp directory as scratch space;
  skips git clone. The planner can manually clone reference repos via bash
  if it needs to explore codebases — this is part of the planning work and
  consumes job budget normally.
- **Context and interaction**: unchanged; context providers and tools work
  against the scratch directory.
- **Publication**: skipped entirely; `git_ref` returns `None`.

No second pipeline is introduced. The distinction is purely in workspace
config.

### 8. Eval job workspace setup

Eval jobs come in two forms depending on their position in the task
hierarchy:

**Leaf eval** (evaluating a task with a repo): accesses the actual git
output of the work it evaluates.

- Trenni extracts the git_ref from the last completed job (or join job)
  in the task's job trace
- Eval job workspace config: `repo=same, init_branch=work_branch,
  new_branch=False`
- Eval job starts with the exact workspace state the work jobs produced

This is critical because agent-submitted events may contain hallucinations.
Git is the ground truth for what was actually produced.

**Root eval** (evaluating a repoless parent task): has no repo to check
out. Its input comes entirely from event context:

- Child eval verdicts (via `eval_context` + `join_context`)
- Job execution traces (via `job_trace`)
- Structural verdict snapshot
- Workspace is a scratch directory (repoless degradation)

The single-repo-per-job constraint is not a limitation: multi-repo work
naturally decomposes into separate spawned tasks, each with its own repo
and leaf eval. Root eval synthesizes child eval verdicts without needing
direct repo access.

### 9. Eval-specific context providers

Two new context providers for eval jobs:

**`eval_context`**: Renders the evaluation specification.

```python
@context_provider("eval_context")
def eval_context(job_config: JobConfig, description: str = "Evaluation Context") -> str:
    """Render goal, deliverables, criteria, structural verdict, and
    child task eval results for the evaluator."""
    # Sources: EvalContextConfig from job_config.context.eval
    # Includes: goal, deliverables list, criteria list,
    #   structural verdict snapshot, child task verdicts
    ...
```

**`job_trace`**: Renders the execution history of the task being evaluated.

```python
@context_provider("job_trace")
def job_trace(job_config: JobConfig, description: str = "Job Execution Trace") -> str:
    """Read job.completed/job.failed events for the evaluated task,
    render as an ordered execution trace."""
    # From pasloe: filter events by task_id
    # Render per job: job_id, role, status, summary, git_ref
    ...
```

The existing `join_context` provider already handles child task terminal
state rendering and is reused by the evaluator context.

### 10. Evo directory structure

```
evo/
├── roles/
│   ├── default.py
│   ├── planner.py
│   ├── implementer.py
│   ├── reviewer.py
│   └── evaluator.py
├── teams/
│   └── backend.py
├── contexts/
│   └── loaders.py          # existing + new providers
├── tools/
│   └── file_tools.py
└── prompts/
    ├── default.md
    ├── planner.md
    ├── evaluator.md
    └── ...
```

## Consequences

### Positive

- Planner only sees relevant roles scoped by team; no information overload
- Team composition is evolvable (in evo/) — agents can modify team structure
  during self-optimization without touching runtime code
- Eval jobs verify against git ground truth, not agent self-reports
- Context providers cleanly separate work context from eval context
- Same role can be reused across teams; team is purely organizational

### Tradeoffs

- Team definition adds one more indirection layer between trigger and
  execution
- `available_roles` context provider must load and render role definitions
  at job startup; cache-worthy if role count grows
- Eval workspace checkout adds one git clone operation per eval job

### Non-Goals

- Dynamic team composition during task execution
- Cross-team role sharing within a single task tree
- Role capability negotiation (planner picks from a fixed list, does not
  negotiate)

## Implementation Scope

**palimpsest**
- `runtime/roles.py`: add `description` to `RoleDefinition`; add
  `TeamDefinition` dataclass and `TeamManager` for loading `evo/teams/`
- `runtime/contexts.py`: no changes (provider loading is generic)
- `evo/contexts/loaders.py`: add `available_roles`, `eval_context`,
  `job_trace` context providers
- `evo/roles/`: add `planner.py`, `evaluator.py`, `implementer.py`,
  `reviewer.py`; update `default.py` with `description`
- `evo/teams/`: add initial team definition(s)
- `evo/prompts/`: add `planner.md`, `evaluator.md`

**yoitsu_contracts**
- `TriggerData`: add optional `team: str` field
- `JobConfig` or context: propagate team name for `available_roles` provider

**trenni**
- `supervisor.py`: resolve team from trigger, extract `planner_role`,
  launch planning job
- Eval job spawn: set workspace config with `init_branch=work_branch,
  new_branch=False` from last job's git_ref
