# ADR-0004: Budget System

- Status: Accepted (Revised 2026-03-31)
- Date: 2026-03-27
- Related: ADR-0002, ADR-0003, ADR-0010

## Context

The budget system has evolved incrementally across several earlier decisions
without a unified design. Several gaps remained:

- Budget was a loose collection of independent limits with no explicit model
  of how they relate or which takes precedence.
- `max_iterations` was changed from a hard cut to a penalty threshold, but
  the behavioral contract and the wall-time dimension were not resolved.
- Budget was declared on roles and global config, but the entity that should
  own budget allocation is the task — the same role executing different tasks
  should consume different budgets.
- Provider cost tracking silently failed when pricing was unavailable,
  creating invisible degraded operation.

## Goal

The budget system serves two goals:

> 1. Guide agents to decompose work into bounded, independently verifiable
>    chunks rather than attempting to complete arbitrarily large tasks in a
>    single job.
>
> 2. Provide uncapped variance data so the system can measure the gap between
>    predicted and actual cost — a prerequisite for self-optimization (ADR-0010).

**Decomposition is achieved structurally** — via planner constraints on
per-job budget size and role `min_cost` floors — rather than through
runtime cost enforcement.

**System-level backstops** (`max_iterations_hard`, job timeout, tool timeout)
protect against bugs and failures. They are not decomposition mechanisms
and are not affected by this suspension.

## Decisions

### 1. Budget Is a Prediction, Not an Enforcement Bound

> **Suspension note (2026-03-31):** Budget was previously described as an
> "enforcement bound" at the task level. Per ADR-0010, budget is now a
> **prediction** — planner's estimate of expected cost. The runtime does
> not enforce cost-based termination. Actual spend is uncapped so that
> `observation.budget_variance` captures the true deviation.

Budget allocation follows the Kubernetes requests/limits pattern, but only
the **requests** side is active:

**Role declares constraints** (scheduling hints and floor):

```python
@role(
    min_cost=0.05,          # spawn rejected below this
    recommended_cost=0.60,  # planner's reference for allocation
    max_cost=2.00,          # per-job ceiling; planner must not exceed
)
```

**Task receives predicted budget at spawn time** (prediction, not cap):

```python
spawn(tasks=[{
    "role": "implementer",
    "goal": "...",
    "estimated_budget": 0.80,  # planner's prediction of expected cost
}])
```

**Root tasks receive allocated budget at trigger time**:

```json
{
  "team": "backend",
  "goal": "Implement feature X",
  "budget": 1.50
}
```

Budget is carried by the task object itself at every level:

- Root task: `TriggerData.budget`
- Child task: `SpawnTaskData.estimated_budget`

`recommended_cost` is a reference for the planner when distributing a
parent budget across child tasks. It is not an enforcement value. The same
role executing a trivial fix and a complex refactor should receive different
budgets — only the plan has the context to make that decision.

`min_cost` is enforced at spawn time: if the allocated budget is below
`min_cost`, the spawn is rejected with an explicit error. This prevents the
planner from allocating an amount too small for the role to operate
meaningfully.

### 1a. Planner Per-Job Budget Ceiling

To encourage decomposition without runtime enforcement, each role declares
a `max_cost` ceiling. **Trenni validates** at spawn time: if
`estimated_budget > role.max_cost`, the spawn is rejected.

This is a structural constraint, not a runtime one — it operates at task
creation, not during execution. The effect is to force planner to break
large work into multiple jobs rather than allocating a single large budget.

The `max_cost` value is per-role and tunable via `evo/`. Initial defaults
should be conservative (e.g., implementer: $2.00, reviewer: $1.00,
planner: $0.50).

### 2. Cost Tracking Remains Active for Observation

Cost (USD) is tracked per job for observability and variance analysis,
but **is no longer used as a termination condition**.

**Cost tracking states:**

- `active`: provider pricing is known; cost accumulates per token consumed.
- `degraded`: pricing unavailable for the configured model; token-cost
  accumulation is disabled. The operator is warned at job start and the
  state is recorded in job metadata/events (`JobStartedData` and
  `JobCompletedData`).

Degraded mode is not silent. If provider pricing is unavailable, the
system logs a warning and continues. In degraded mode:

- Provider token pricing contributes `0` to cost.
- Hard backstops (`max_iterations_hard`, timeout) remain active.

Cost data feeds into `observation.budget_variance` (ADR-0010) for
self-optimization. Accurate cost tracking is important for signal quality
even though it no longer triggers termination.

### ~~3. Iterations Use a Penalty Model, Not a Hard Cut~~ (Suspended)

> **Suspended (2026-03-31):** The iteration penalty model was coupled to
> cost-based termination. With cost enforcement suspended, the penalty
> formula has no enforcement target. `max_iterations` and
> `iteration_penalty_cost` are no longer active.
>
> The iteration count is still tracked and emitted in job completion events
> for observability. `max_iterations_hard` (Decision 4) remains the only
> iteration-based termination mechanism.
>
> This decision may be revisited if a future ADR reintroduces soft economic
> pressure in a form compatible with the prediction model.

### 4. Hard Iteration Ceiling as System Backstop

A separate field `max_iterations_hard` provides an absolute ceiling that the
runtime enforces regardless of cost state. It exists to protect against
infinite loops, broken tool calls that always succeed, and configurations
where cost tracking is unavailable and `max_iterations` has no effect.

```
max_iterations_hard >> max_iterations  (typically 3–5x)
```

The hard ceiling is a system-level guarantee. It is not meant to trigger
during normal operation. If it triggers, it indicates either a bug in the
agent, a misconfigured budget, or degraded cost tracking that should have
been noticed earlier.

### 5. Job Timeout as Wide System Backstop

Job timeout remains in the runtime as a wall-clock backstop. It is not part
of the planning budget model and should be configured far above normal job
durations.

Its purpose is operational safety:

- Kill pathological jobs that stop making progress but also fail to hit
  other ceilings.
- Protect the runtime from unexpected deadlocks or provider hangs.
- Provide an operator-controlled final stop even when cost/backstop logic
  is misconfigured.

Like `max_iterations_hard`, this timeout is not meant to trigger during
normal operation. It is a coarse safety guarantee, not a decomposition
guidance mechanism.

### 6. Wall Time Policy Applies Per Tool Call, Not Per Job

Job-level wall time is the sum of all tool call durations plus LLM
round-trip times. The risk is not a job running "too long" in aggregate —
it is a single tool call hanging indefinitely (network timeout, subprocess
block, filesystem deadlock).

Each tool call is subject to a configurable `tool_timeout_seconds`. If a
tool call exceeds this limit, the runtime raises a `ToolTimeoutError`,
which surfaces to the agent as a failed tool call. The agent can decide
whether to retry, abandon, or declare partial work.

Enforcement depends on the tool execution path:

- Subprocess/callout tools can be hard-timed out directly.
- In-process Python evo tools require a stronger isolation boundary or
  cooperative timeout mechanism to guarantee interruption.

Until evo tool isolation is strengthened, `tool_timeout_seconds` is only a
hard guarantee for timeout-capable tool paths.

### 7. Budget Exhaustion Terminal Path (Narrowed)

> **Partially suspended (2026-03-31):** Cost-based exhaustion (`"cost"`) is
> removed. The `budget_exhausted()` check now only triggers on system
> backstop dimensions.

The interaction loop checks `budget_exhausted()` before each LLM call. When
exhausted:

```
budget_exhausted() → "max_iterations_hard" | "input_tokens" | "output_tokens"
    ↓
job exits cleanly, publication attempted
    ↓
publication succeeded → agent.job.completed(code="budget_exhausted") → task.partial
publication failed   → agent.job.failed
```

The budget dimension that triggered exhaustion is recorded in
`JobCompletedData.budget_dim` for observability.

Jobs that exceed their `estimated_budget` without hitting a system backstop
complete normally. The variance is captured by `observation.budget_variance`
(ADR-0010) and serves as optimization input, not as a termination trigger.

The `task.partial` state and routing are described in ADR-0002. The
publication guarantee is described in ADR-0003.

### 8. Deferred: fn-ization and Agent-Initiated Suspension

Two mechanisms were considered for handling long-running operations:

**fn-ization** (non-agent code jobs): would introduce executor-type jobs
that run code without an LLM. Deferred because spawn is currently the
exclusive right of agents — allowing code jobs to spawn would introduce a
path to pre-defined orchestration graphs, eroding the system's autonomous
character. The existing spawn mechanism already handles task decomposition.

**Agent-initiated suspension**: agents declare long-running operations in
advance and request job suspension. Deferred pending a clear design for the
resume mechanism and context preservation across suspension boundaries.

Neither mechanism is required to make the budget system correct. Both
remain open for future ADRs.

### ~~9. Deferred: Barrier Function~~ (Suspended)

> **Suspended (2026-03-31):** The barrier function was designed to create
> convergence pressure near a cost ceiling. With cost enforcement suspended,
> there is no ceiling to converge against. This deferral is now a suspension
> — it will only be revisited if cost-based termination is reintroduced.

## Consequences

### Positive

- Budget allocation is owned by the entity with the most context (the plan),
  not by the role definition.
- Cost tracking degradation is visible, not silent.
- Tool timeout is the right granularity for operational hangs, while job
  timeout remains a wide safety backstop.
- The system goal (decompose into verifiable chunks) is explicit, making
  future budget design decisions easier to evaluate.
- Budget variance data is uncapped, giving the optimization loop (ADR-0010)
  true signal about prediction accuracy.
- Planner per-job ceiling (`max_cost`) encourages decomposition at spawn
  time without truncating runtime cost data.

### Tradeoffs

- Without runtime cost enforcement, a misbehaving agent can spend
  significantly more than predicted. System backstops (`max_iterations_hard`,
  job timeout) are the only hard stops.
- Degraded mode warning at job start adds noise when pricing tables are
  incomplete; pricing tables must be maintained.
- Tool timeout enforcement is asymmetric until evo tool isolation improves.

### Non-Goals

- Dynamic budget reallocation mid-job.
- Per-tool-call cost attribution.
- Cross-job budget pooling at the task level.
- Per-budget-dimension distinction in the partial terminal signal (all
  budget types collapse to `code="budget_exhausted"`; the triggering
  dimension is in `budget_dim`).

## Suspension Log

| Date | Decisions Affected | Reason |
|---|---|---|
| 2026-03-31 | 1 (reframed), 2 (narrowed), 3 (suspended), 7 (narrowed), 9 (suspended) | ADR-0010 reframes budget as prediction/optimization signal. Cost enforcement truncates variance data needed for self-optimization. Planner per-job ceiling (Decision 1a) replaces runtime enforcement as the decomposition incentive. |
