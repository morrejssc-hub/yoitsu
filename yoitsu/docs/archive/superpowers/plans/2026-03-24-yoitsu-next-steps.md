# Yoitsu Next Steps

Date: 2026-03-24
Mode: Builder
Status: Draft

## Where The Project Actually Is

Yoitsu has crossed an important threshold:

- Quadlet deployment is real, not simulated
- `trenni` now launches one Podman container per job
- Pasloe -> Trenni -> Palimpsest -> remote git push works
- fan-out via `spawn(wait_for="all_complete")` works
- child task payloads now carry real execution intent instead of loose dicts

This means the project is no longer proving that "an agent can run". That part
is already true.

The next question is:

> What turns this from an interesting runtime into a system people can trust to
> hand real software work to?

## Recommendation

The best next step is not "more tools" and not "more providers".

The best next step is:

**Make orchestration outputs composable and reviewable.**

In practice that means building the layer above fan-out:

1. child jobs produce structured outputs
2. parent jobs resume with those outputs
3. Yoitsu records the whole job graph as a first-class artifact
4. a human can approve, reject, or replay graph nodes safely

Without that, Yoitsu remains a strong single-run engine. With that, it becomes
a real autonomous software workflow system.

## Why This Is The Highest-Leverage Move

Right now the system can:

- execute work
- branch work
- publish work

But it still cannot reliably do the thing that matters most for real use:

- decompose a larger software task
- let sub-agents explore different slices
- reunify the results
- decide what happens next based on the child outputs

That is the gap between:

- "agent runner"
- and "agent engineering system"

## The Three Best Tracks

### Track 1: Graph-Oriented Execution

Goal:
- turn fan-out into full graph execution

Concrete work:
- add continuation/join jobs back, but only on top of the new `prompt + job_spec` spawn contract
- persist structured child outputs, not just summaries
- let parent jobs consume child outputs explicitly
- store graph edges and node state in a queryable projection

Success condition:
- a parent task can spawn 3 children, wait for all, read their outputs, then produce one merged result or one PR

Why this should be first:
- it compounds every other capability already in the system

### Track 2: Approval-Native Software Delivery

Goal:
- make Yoitsu useful for real repo work with humans in the loop

Concrete work:
- add publication modes beyond direct branch push:
  - branch only
  - branch + PR draft
  - PR with approval required
- add a review gate event type:
  - `job.review.requested`
  - `job.review.approved`
  - `job.review.rejected`
- allow paused graph nodes waiting on human decisions

Success condition:
- a complex task can run, open a reviewable result, and stop before irreversible actions

Why this matters:
- trust is the product

### Track 3: Evo As A Governed Improvement Loop

Goal:
- make self-evolution safe and measurable instead of magical

Concrete work:
- define capability benchmarks for evo changes
- add a "propose evo change" workflow with automatic regression checks
- maintain a scorecard for:
  - success rate
  - token cost
  - elapsed runtime
  - publication quality
- require an explicit benchmark delta before promoting evo changes

Success condition:
- Yoitsu can improve its own prompts/tools/roles with evidence, not vibes

Why it matters:
- otherwise evo becomes entropy, not compounding capability

## Suggested Order

### Phase 1: Finish The Graph

Build next:
- continuation/join
- structured child outputs
- graph projection and inspection

Reason:
- this upgrades the core runtime model itself

### Phase 2: Add Human Checkpoints

Build next:
- approval events
- PR/review modes
- replay / retry from graph nodes

Reason:
- this makes the system deployable for real engineering work

### Phase 3: Turn Evo Into A Measured Loop

Build next:
- evo benchmark harness
- promotion rules
- regression dashboard

Reason:
- this turns "self-evolving" from a slogan into an operating discipline

## The Main Risk To Avoid

The biggest product trap from here is:

**adding more local capabilities without improving control structure**

Examples of low-leverage next steps:
- more built-in tools
- more providers
- more prompt variants
- more deployment polish

These are all useful, but they do not change the ceiling.

The ceiling changes when Yoitsu can:
- split work
- preserve intent
- merge work
- ask for approval
- learn from outcomes

## One Concrete North Star

If you want a single crisp target for the next stage, use this:

> Given one moderately large engineering task, Yoitsu should split it into
> several child jobs, run them in parallel, reunify the results in a parent
> continuation, produce one reviewable branch/PR, and stop for approval.

If the system can do that reliably, it has crossed from infrastructure demo to
useful autonomous engineering workflow.
