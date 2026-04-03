# ADR-0010: Self-Optimization Governance

- Status: Accepted
- Date: 2026-03-31
- Related: ADR-0002, ADR-0007

## Context

Palimpsest's long-horizon goal is self-improvement: the system should identify inefficiencies in its own operation and address them over time. The question is how to structure this without building a separate optimization subsystem with special privileges or code paths.

A prior attempt (palimpsest-v1) relied on single-prompt self-reflection — the agent reviewed its own event history and wrote its own memory. This proved insufficient: a single prompt cannot genuinely evaluate its own behavior, and self-authored memory has limited reliability.

The yoitsu architecture already separates observer (Trenni) from executor (Palimpsest), providing the structural prerequisite for external evaluation. The remaining design question is how optimization signals flow from observation to action.

## Decisions

### 1. Structured observation signals, not AI-generated summaries

Optimization begins with data. The system collects structured observation events mechanically — no LLM involved in signal generation.

Observation events use the `observation.*` type namespace and are emitted by Trenni and the tool gateway based on deterministic criteria:

- `observation.budget_usage` — job spent >N% of budget, with breakdown (prompt vs completion, retry overhead)
- `observation.tool_retry` — tool call failed and was retried, with failure count and pattern
- `observation.context_overflow` — job queried Pasloe for additional context beyond what preparation provided
- `observation.round_efficiency` — ratio of LLM rounds to concrete outputs (tool calls, commits, spawns)
- `observation.spawn_depth` — task recursion depth exceeded threshold
- `observation.budget_variance` — planner's estimated budget vs actual spend per job, with deviation ratio

These are append-only events written to Pasloe through the normal event pipeline. They carry structured data, not natural language assessments. The set of observation types is expected to grow as the system matures.

### 2. Optimization discovery is a normal task

Periodically (via Trenni trigger rules, per ADR-0007 D8), the system creates a review task:

```yaml
trigger:
  match:
    type: "observation.*"
    accumulate: 20
  spawn:
    goal: "review recent observation signals and propose improvements"
```

This review task is a normal task. It goes through the normal lifecycle — Trenni schedules it, a planner or reviewer role executes it, results are evaluated. The review job queries Pasloe for recent observation events, identifies recurring patterns, and produces concrete improvement proposals.

There is no special "optimization mode", no privileged access, no separate scheduler. The review task competes for resources like any other task.

### 3. Optimization execution is a normal task

Improvement proposals produced by review tasks become new tasks through normal spawn. Each proposal is a task with a goal like "reduce retry overhead in API tool" or "add caching to PR diff fetching in reviewer preparation".

These tasks are indistinguishable from externally submitted work. They go through planner (if role is unspecified, per ADR-0007 D3), get scheduled, executed, and evaluated through the standard pipeline.

This means the system's self-improvement uses exactly the same mechanisms as its regular work. No special code paths, no optimization-specific roles (though a role may be particularly suited to certain optimization work), no privileged event types.

### 4. Signal collection is incremental; optimization is deferred

Observation event types should be defined in contracts early (Phase 1-2 of the roadmap) and emitted as the relevant code paths are built. However, optimization tasks should not be triggered until there is sufficient signal volume — the accumulation threshold in trigger rules serves as the gate.

The rationale: optimization with sparse signals produces false patterns and premature changes. The system needs months of real task execution data before self-optimization becomes valuable. Collecting signals early and acting on them late is the correct sequencing.

Phase mapping:
- **Phase 1-2**: Define `observation.*` schemas in contracts. Emit signals from tool gateway and Trenni as relevant code is written.
- **Phase 3**: Reviewer role can read observation events as additional context.
- **Phase 4**: Pasloe query capability enables aggregation over time windows.
- **Phase 5**: Trigger rules activate review tasks. The optimization loop closes.

Each phase adds a small increment. No phase requires building optimization-specific infrastructure.

### 5. Budget prediction accuracy as a system health proxy

Planner, when spawning sub-tasks, includes an `estimated_budget` field — a prediction, not a cap. The job runs without budget enforcement; actual spend is unconstrained. Upon job completion, Trenni mechanically emits `observation.budget_variance` with the estimated vs actual values.

Budget prediction accuracy serves as a **proxy metric for system modeling fidelity**:

- **Consistently accurate predictions** indicate that the planner understands task complexity, role definitions are clear, and preparation functions provide the right context — the system's model of its own work aligns with reality.
- **Systematic underestimation** signals that role scopes are unclear, preparation is missing context (forcing agents to spend extra rounds discovering it), or task decomposition is too coarse.
- **Systematic overestimation** signals that preparation does redundant work, role capabilities are undervalued, or tasks are over-decomposed.
- **High variance for specific task types** pinpoints which domains have weak context functions or role definitions.

Because prediction accuracy is normalized (deviation ratio, not absolute cost), it is comparable across task types and over time. This makes it a first-class input for optimization review tasks: the review goal shifts from "reduce spend" to "improve prediction accuracy", which structurally implies improving role definitions, preparation functions, and task decomposition — the upstream causes rather than the downstream symptom.

The optimization role's goal is not to enforce budgets, but to drive prediction–reality convergence. Budget reduction is a likely side effect, not the objective.

## Issues and Suggestions

### 1. Observation events must include causal chain (Adopted)

`observation.*` events must include `task_id`, `job_id`, and `role` to
establish causality and enable per-role aggregation. Without this, optimization
tasks cannot trace problems to their source or compare role performance.

Example:

```json
{
  "type": "observation.tool_retry",
  "data": {
    "task_id": "task-abc123",
    "job_id": "job-def456",
    "role": "implementer",
    "tool": "api_call",
    "failure_pattern": "timeout",
    "retry_count": 3,
    "context": {"endpoint": "github.api.pr"}
  }
}
```

**Status:** Adopted. Schema must be defined in contracts during Phase 1-2.
The `role` field is required for aggregation queries like "retry rate by role".

### 2. Review task uses prompt-based check items, not strict eval_spec

~~Review task goal is underspecified~~

The review task's output is a special event (proposal), but it does not need
to be heavily structured. The review role's prompt includes a set of **check
items** that guide the review without imposing rigid output schema:

Suggested prompt check items:

- Does any role's `PreparationConfig` usage exceed N parameters? If so,
  propose splitting the role (ADR-0003 D4).
- What is the budget prediction variance trend for each role? Are specific
  task types systematically off? (ADR-0010 Decision 5, ADR-0004).
- Are tool retry rates elevated for specific roles or tools?
- Is observation signal volume growing in ways that suggest trigger
  threshold adjustment?

These check items are maintained in `evo/` as part of the review role
definition and can themselves be evolved. Adding a new check item is a
normal code change — no schema migration needed.

The review task's eval (if configured) verifies only that proposals are
actionable — i.e., each proposal names a concrete change target and can be
spawned as a task. It does not verify proposal quality; that is measured
downstream by whether the spawned optimization task improves prediction
accuracy (Decision 5 feedback loop).

### 3. Accumulation threshold — kept simple

~~Fixed accumulation threshold lacks adaptability~~

The fixed `accumulate: 20` threshold is kept as-is. Adaptive thresholds
(time windows, cooldown, self-tuning) are deferred to Phase 5. The current
concern — early in system lifetime events may take months to accumulate —
is a feature, not a bug: optimization with sparse signals produces false
patterns. Slow accumulation is correct early-stage behavior.

See also ADR-0007 Non-Goals (trigger batching deferred to Phase 5).

### ~~4. Missing feedback closed loop~~

Addressed by Decision 5. Budget prediction accuracy provides a continuous, normalized feedback signal. Prediction–reality convergence naturally verifies whether optimizations are effective: if an optimization improves role definitions or preparation functions, prediction accuracy improves measurably. Degradation in accuracy after a change is a rollback signal. No separate verification mechanism needed — the same `observation.budget_variance` stream serves as both optimization input and effectiveness measure.

