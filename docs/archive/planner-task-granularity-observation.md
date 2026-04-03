# Planner Spawn Smoke Observations

Updated: 2026-03-28

## Context

This note records the recent end-to-end smoke attempts around the
`planner -> spawn -> eval` path.

The purpose is to separate:

- infrastructure failures
- monitoring/tooling gaps
- planner prompt/behavior problems
- runtime contract problems
- model/provider behavior problems

The current conclusion is that we are no longer blocked on basic
observability. We are now blocked on the planner path itself, and the
remaining failures are severe enough that prompt-only iteration is no longer
the only sensible debugging strategy.

## What Is Already Working

The following pieces now work well enough to expose real orchestration
failures:

- fresh deploy and runtime reset
- Pasloe and Trenni health checks
- `yoitsu status`
- `yoitsu tasks chain <task_id>`
- `yoitsu tasks wait <task_id>`
- `yoitsu events tail --task <task_id>`
- `yoitsu jobs tail <job_id>`
- child task live detail for hierarchical task ids
- planner continuation jobs with `mode=join`
- richer `join_context` for continuation planning

So the current failures are not "we cannot see what happened". They are
"we can now see the system failing more clearly".

## Attempt Timeline

### Attempt 1: Fixed-file smoke against `yoitsu.git`

Representative root tasks:

- `069c6924b1da7b65`
- `069c6983df257fba`

Observed behavior:

- root planner completed directly
- no child task was created
- no `agent.job.spawn_request`
- no eval job

Observed root-cause candidate:

- planner inspected existing repo state and decided the task was already
  complete
- the smoke goal targeted a fixed artifact path such as `smoke/SMOKE.txt`
- earlier smoke attempts had already polluted the repo state

Conclusion:

- this did not validate spawn-mode at all
- the task fixture itself was too easy to satisfy from historical state

### Attempt 2: Spawn-mode version bump task against `palimpsest-test.git`

Representative root task:

- `069c69a1ccb47aa5`

Observed behavior:

- root planner emitted a real `agent.job.spawn_request`
- child tasks and child jobs were created
- child implementer jobs ran
- child eval jobs ran
- monitoring surface could observe the entire chain

But the decomposition looked like:

1. child A edits README and bumps version
2. child B stages and commits README changes

Why this mattered:

- the planner finally used `spawn`
- but it split work at a granularity that does not match the current runtime
  model
- child tasks are isolated execution units and should not implicitly depend on
  another child's unpublished workspace state

Conclusion:

- this was the first strong evidence that the planner needed stronger
  decomposition guidance
- the system had crossed from "cannot spawn" into "spawns the wrong kind of
  child task"

### Attempt 3: Parent continuation / join did not converge

Representative root tasks:

- `069c64cb295f7827`
- `069c67681ee570c9`

Observed behavior:

- child tasks completed
- child eval jobs completed or progressed correctly
- the parent task still remained pending
- Trenni scheduled continuation planner jobs on the same parent goal
- continuation planners kept replanning instead of settling

Issues found and fixed afterward:

1. child task live detail route bug
   - `/control/tasks/{task_id}` did not handle hierarchical ids with `/`
   - fixed by switching to a path-style route
2. continuation planner had the same role but not enough contextual
   distinction
   - root planner and continuation planner are now still one role, but use
     `mode=initial` and `mode=join`
3. continuation planner lacked enough result evidence
   - `join_context` now includes richer child result evidence:
     - semantic summary
     - criteria results
     - trace
     - `git_ref`

Conclusion:

- this was not just a monitoring bug
- the continuation path exposed a real planner-policy problem

### Attempt 4: Prompt strengthening around child-task granularity

Changes applied before the next smoke:

- planner prompt now explicitly states:
  - child tasks must be self-contained
  - child tasks must be independently verifiable
  - do not split "one child edits, another child commits"
- join planner prompt also gained the same self-contained follow-up rule
- root planner and join planner now differ by `mode`, which changes
  `context_fn`

Observed behavior afterward:

- planner did start to use `spawn` in some runs
- but the decomposition still tended to reflect a human serial workflow rather
  than runtime-isolated child tasks

Conclusion:

- prompt improvements helped
- prompt-only control was not sufficient

### Attempt 5: Switch model to `glm-5`

Changes applied:

- provider remained the same
- default model was switched from `kimi-k2.5` to `glm-5`

Observed behavior:

- fresh deploy remained possible
- the root planner often spent much longer in its first turn
- some runs looked like they stalled at the first LLM call

Important note:

- this made it harder to tell whether we were seeing:
  - planner prompt problems
  - provider/model latency problems
  - runtime integration problems

Conclusion:

- model changes may affect planner stability
- but they also introduced additional uncertainty into smoke interpretation

### Attempt 6: Planner lacked `spawn` at role-config level

Representative root task:

- `069c6acb9a107210`

Observed behavior:

- planner was running
- no spawn happened

Container log revealed:

- `Resolved role 'planner' -> JobSpec (source_role='planner', tools=['read_file', 'list_files'])`

Root cause:

- `planner.py` no longer exposed `spawn` in its tool list

Fix:

- `spawn` was added back to the planner role

Conclusion:

- this was a hard configuration bug, not a model behavior issue

### Attempt 7: Planner had `spawn`, but runtime still warned about missing tool

Representative root task:

- `069c6adef8447119`

Observed behavior:

- planner resolved with `tools=['spawn', 'read_file', 'list_files']`
- container log still printed:
  - `Tools not found in /opt/yoitsu/palimpsest/evo/tools: {'spawn'}`

Root cause:

- builtin/evo tool handling was not cleanly separated
- `spawn` is a builtin tool
- the runtime still tried to scan `evo/tools` for it and warned even though
  the builtin implementation was already present

Fix:

- builtin tool names are now filtered out before `resolve_tool_functions()`
  scans `evo/tools`

Conclusion:

- this warning was misleading noise, not the real blocker
- but it materially complicated debugging and needed to be removed

### Attempt 8: Clean smoke after builtin/evo tool separation

Representative root task:

- `069c6af7afa6722f`

Observed behavior:

- fresh deploy succeeded
- `spawn` warning disappeared
- planner again resolved with:
  - `tools=['spawn', 'read_file', 'list_files']`
- but the job still remained in the first LLM turn:
  - `agent.llm.request`
  - no `agent.llm.response`
  - no `agent.job.spawn_request`
  - no terminal event

Conclusion:

- by this point:
  - deploy path was working
  - monitoring was working
  - planner tool config was corrected
  - builtin/evo tool loading was corrected
- the remaining failure was still in the live planner path itself

This is the point where the problem starts to look "severe" rather than
"another prompt iteration away from fixed".

## Consolidated Findings

The smoke attempts exposed multiple layers of issues:

1. Some early failures were caused by bad smoke fixtures.
2. Some mid-stage failures were caused by missing runtime support:
   - hierarchical task id route
   - insufficient `join_context`
   - continuation planner input mode
3. Some later failures were caused by hard implementation bugs:
   - planner missing `spawn`
   - builtin/evo tool confusion
4. Even after those were fixed, the planner path still did not become
   reliably healthy in a real end-to-end smoke.

So the current state is:

- the debugging surface is good enough
- the deploy path is good enough
- the core planner path is still not stable enough

## Current Interpretation

At this point, "keep editing the smoke task" is not the right primary move.

Likewise, "keep editing the planner prompt and rerunning full deploys" is now
too slow and too noisy as the only feedback loop.

The system now needs a shorter debugging loop that isolates:

- the exact prompt
- the exact tools
- the exact model/provider response

without involving the full supervisor/runtime/container/replay pipeline.

## Recommended Next Step: Short-Circuit Planner Harness

Build a small debug script that:

1. loads the planner prompt and assembled context exactly as the runtime would
2. constructs the tool schemas explicitly
3. sends one direct LLM request to the configured model/provider
4. prints the raw assistant response and raw tool-call payload
5. optionally replays a few prompt variants quickly

The script should not:

- launch a real job container
- emit real events
- depend on Supervisor scheduling
- depend on child tasks or replay

The script should answer one concrete question:

> Given this exact planner prompt, this exact assembled context, and this exact
> tool schema, does the model produce the `spawn` call shape we want?

That is the shortest loop for debugging:

- whether the prompt is clear enough
- whether the model obeys the contract
- whether the tool schema shape is pushing it in the wrong direction

## Why This Short-Circuit Harness Is Needed

The current full smoke loop is too expensive for prompt-level debugging:

- fresh deploy is not free
- first-turn latency is large
- model behavior and runtime behavior are intertwined
- every run has many moving pieces

The short-circuit harness would let us iterate on:

- planner prompt
- join prompt
- task description shape
- tool schema shape
- model choice

until the first-turn response reliably produces the intended `spawn`
structure.

Only after that should we go back to repeated end-to-end smoke.

## Immediate Recommendation

Do both of the following:

1. keep this document as the historical record of live smoke attempts
2. implement a direct planner-debug script before the next major smoke cycle

The system has now reached the point where full-runtime smoke is good for
validation, but not good enough as the only debugging loop.
