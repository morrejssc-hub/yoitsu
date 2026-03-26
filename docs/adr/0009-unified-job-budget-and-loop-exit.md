# ADR-0009: 2026-03-26 Unified Job Budget And Interaction Loop Exit

- Status: Accepted, implementation pending
- Date: 2026-03-26
- Related: ADR-0007

## Context

The interaction loop currently has three independent exit mechanisms with
inconsistent ownership:

1. `task_complete` tool — agent explicitly signals exit; carries a `status`
   field that was originally intended for task-level quality signaling
2. `max_iterations` — checked in the `for` loop of `interaction.py`
3. Budget exhaustion (iterations only) — introduced by ADR-0007

Several problems:

- `task_complete` carries task-level semantics (`status: complete/failed`)
  but operates at the job level. With the eval mechanism (ADR-0006) handling
  all semantic judgment, agent self-reporting of task quality is redundant.
- In practice agents call `task_complete` unreliably; the runtime already has
  a fallback path for when the LLM stops calling tools.
- `max_iterations` is the only budget dimension with a hard stop. Context
  window consumption and cost are tracked per-call by the LLM gateway
  (`input_tokens`, `output_tokens` in `LLMResponseData`) but have no
  cumulative budget enforcement.
- Budget proximity warnings (`LoopWarning`) only check iteration count, not
  tokens or cost.

## Decision

### 1. Remove `task_complete` tool

The `task_complete` tool is removed entirely:

- `palimpsest/palimpsest/runtime/tools.py`: delete `task_complete` function
- `palimpsest/evo/tools/task_complete.py`: delete file
- `ToolResult.terminal` field: remove (no tool needs to signal loop exit)
- `interaction.py`: remove terminal detection logic (`result.terminal` checks)

Job exit is no longer agent-initiated. All jobs exit through one of two paths:
idle detection or budget exhaustion.

### 2. Idle detection as the primary exit path

When the LLM returns a response with no tool calls:

1. First occurrence: capture the response text as the **candidate summary**
   and inject a single confirmation prompt ("if you have more work, continue
   calling tools; otherwise this job will end")
2. Second consecutive occurrence (or first occurrence after confirmation):
   exit the loop using the **candidate summary** from step 1, not the
   confirmation response
3. If the agent resumes tool calls after the confirmation prompt, reset the
   idle state — the candidate summary is discarded

This ensures the summary in the job completion event reflects the agent's
natural conclusion, not its response to a system prompt.

The returned result uses `status: "complete"` for idle exit. All idle exits
are `job.completed` with no special code.

### 3. Unified budget tracking at the LLM gateway

The LLM gateway (`UnifiedLLMGateway`) becomes the single source of truth for
all budget dimensions. It accumulates per-call metrics that it already
receives from provider responses:

**New cumulative state on the gateway:**
- `total_iterations: int`
- `total_input_tokens: int`
- `total_output_tokens: int`
- `total_cost: float` (estimated from model pricing)

**New budget configuration on `LLMConfig`:**
```python
max_iterations: int = 50          # existing, moved to gateway enforcement
max_total_input_tokens: int = 0   # 0 = unlimited
max_total_output_tokens: int = 0  # 0 = unlimited
max_total_cost: float = 0.0       # USD, 0 = unlimited
```

**Gateway exposes two methods:**
- `budget_exhausted() -> str | None` — returns the exhaustion reason
  (e.g. `"max_iterations"`, `"input_tokens"`, `"cost"`) or `None`
- `budget_remaining() -> dict` — returns remaining quantities per dimension
  for proximity warning checks

The interaction loop checks `budget_exhausted()` before each LLM call. If
exhausted, the loop exits with the candidate summary (if any) or a
descriptive fallback, `status: "partial"`, and `code: "budget_exhausted"`.

### 4. Unified `LoopWarning` integration

`LoopWarning` triggers are refactored to consume `budget_remaining()` instead
of receiving a raw iteration count. Each warning can define thresholds across
any budget dimension:

```python
@dataclass
class LoopWarning:
    trigger: Callable[[dict], bool]   # receives budget_remaining()
    message: Callable[[dict], str]
```

This allows warnings like "you have ~20% of your token budget remaining"
alongside the existing iteration warning.

### 5. Interaction loop structure

```
while True:
    if llm.budget_exhausted():
        → exit with candidate_summary, status="partial", code="budget_exhausted"

    check LoopWarning triggers against llm.budget_remaining()

    response = llm.call(...)

    if no tool calls:
        if first idle:
            save candidate_summary, inject confirmation prompt, continue
        else:
            → exit with candidate_summary, status="complete"

    else:
        reset idle state
        execute tool calls
```

All exits produce `job.completed`. The distinction between idle exit
(`status: "complete"`) and budget exit (`status: "partial"`,
`code: "budget_exhausted"`) flows into the job completion event for
trenni to route to the appropriate task-level state.

## Consequences

### Positive

- Single budget authority (LLM gateway) for all dimensions; no split
  ownership between interaction loop and gateway
- `task_complete` removal eliminates the task/job semantic confusion and
  the unreliable agent self-reporting path
- Context and cost budgets become enforceable hard limits, using the same
  `budget_exhausted → task.partial` path established in ADR-0007
- Summary selection is deterministic: always the agent's first idle response
- Tool framework simplifies: `ToolResult.terminal` is removed, no tool
  can forcibly exit the loop

### Tradeoffs

- Agents lose the ability to explicitly signal "I'm done" — they must
  simply stop calling tools. In practice this is how most LLMs naturally
  behave when finished.
- The confirmation prompt adds one extra LLM call per job exit. This is
  a small cost for avoiding premature exits from mid-thought text responses.
- Cost estimation requires per-model pricing tables; initially this can be
  approximate or disabled (`max_total_cost: 0`).

### Non-Goals

- Dynamic budget reallocation mid-job
- Per-tool-call cost attribution
- Cross-job budget pooling at the task level

## Implementation Scope

**yoitsu_contracts**
- `LLMConfig`: add `max_total_input_tokens`, `max_total_output_tokens`,
  `max_total_cost` fields
- `JobCompletedData.code` already supports `"budget_exhausted"` (ADR-0007)

**palimpsest**
- `runtime/tools.py`: delete `task_complete`; remove `ToolResult.terminal`
  field and all terminal detection in tool execution path
- `evo/tools/task_complete.py`: delete file
- `runtime/llm.py` (`UnifiedLLMGateway`): add cumulative tracking,
  `budget_exhausted()`, `budget_remaining()` methods
- `stages/interaction.py`: rewrite loop — remove `for` range and terminal
  checks; replace with `while True` + `budget_exhausted()` gate + idle
  detection with candidate summary capture
- `stages/interaction.py` (`LoopWarning`): refactor trigger signature from
  `Callable[[int], bool]` to `Callable[[dict], bool]`

**trenni**
- No changes required; `job.completed` with `code="budget_exhausted"` already
  routes to `task.partial` (ADR-0007)
