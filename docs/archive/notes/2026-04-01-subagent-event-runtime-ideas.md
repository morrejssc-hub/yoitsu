# Subagent Notes: Event-Sourced Single-Task Runtime Ideas

Date: 2026-04-01
Source: subagent exploratory architecture pass with no current implementation context
Goal: challenge the existing four-stage framing and generate first-principles alternatives

## A. Root Principles

1. Authoritative state should live only in replayable events and referenceable artifacts, not in in-process return values, object graphs, or workspace directories.
2. The runtime core should do only two things: form the current view from known facts, then choose the next executable action from that view.
3. Any non-deterministic observation that can affect future decisions must be evented or frozen via an artifact reference; otherwise restart cannot recover equivalent behavior.
4. The local workspace is a materialization layer, not the source of truth. It can accelerate execution and hold side effects, but should be assumed disposable and reconstructible.
5. External side effects should cross an explicit effect boundary with causal ID, idempotency key, preconditions, and a result receipt for retry and audit.
6. Prompting, context gathering, tooling, and publication should all be swappable strategies or capabilities, not hard-coded runtime skeleton pieces.
7. Error handling, recovery, retries, human intervention, and timeouts should be first-class task events, not side-channel control flow.
8. The system should distinguish authoritative state from acceleration state.
Authoritative state: event store plus artifact references.
Acceleration state: workspace, cache, runtime memory, materialized views.

## B. Three Distinct High-Level Models

1. Event-driven decision loop
2. Derived graph / capability graph
3. Blackboard-style obligations, evidence, and actions

## C. Model Details

## Model 1: Event-Driven Decision Loop

Core abstract unit: one decision step or one effect attempt.

State surfaces:
- `event store` holds the task log and the only authoritative causal chain.
- `artifact store` holds immutable context bundles, external snapshots, tool outputs, and publication receipts.
- `local workspace` is rented and materialized only for effects that need filesystem state.
- `runtime memory` holds only the current projected view, handles, and caches.

Flow:
- Project a `TaskView` from the event stream.
- A policy selects the next `EffectSpec`.
- Execute the effect.
- Write observations, artifact refs, result summaries, errors, and retry decisions back to the event stream.
- Re-project and continue.

Must be evented:
- Task acceptance
- Input references
- Critical observations
- Each effect start and finish
- Failure reasons
- Artifact references
- Final completion or abandonment
- Human interventions

Can stay local:
- Rebuildable caches
- Temporary clone directories
- Token streams
- Pure acceleration intermediates
- Scratch outputs that do not affect later decisions

Error recovery and retry:
- Recovery boundary is the effect, not the whole task.
- Each effect has an idempotency key.
- On restart, replay events and decide which effects are done, which are safe to retry, and which need compensation.
- Recovery is "continue from the log", not "restore in-process state".

Fit for non-git-native and external-system work:
- Very strong.
- Git is just one effect category among many.

Advantages:
- Smallest kernel
- Clear recovery model
- Strong event semantics
- Good generality for external tasks
- Makes observability, audit, and retry first-class

Drawbacks:
- If a task contains a lot of parallelizable, reusable deterministic sub-computation, the pure loop is weaker than a graph model.
- Projection and effect schemas need careful design.

## Model 2: Derived Graph / Capability Graph

Core abstract unit: one executable node describing "derive these outputs from these inputs" through a capability invocation.

State surfaces:
- `event store` records graph mutations, node scheduling, attempts, invalidations, and completions.
- `artifact store` stores node inputs and outputs, snapshots, and context bundles.
- `local workspace` is a local sandbox for one node.
- `runtime memory` maintains the ready set, dependency counts, and scheduling caches.

Flow:
- The task starts from a goal and seed inputs.
- The runtime incrementally constructs or expands a graph.
- When a node's dependencies are satisfied, execute it.
- Node outputs become artifacts and unlock downstream nodes.
- Failed nodes can be retried, invalidated, or replaced.
- The graph itself is persistent.

Must be evented:
- Node definitions
- Dependencies
- Node versions
- Input and output refs
- Invalidation relations
- Acceptance and rejection decisions

Can stay local:
- Node-local temp files
- Re-downloadable caches
- Local inference scratch data

Error recovery and retry:
- Retry at node granularity.
- Failures do not poison the whole graph.
- If upstream observations change, invalidate the relevant subgraph and recompute locally.
- Restart reconstructs the graph and ready set from events.

Fit for non-git-native and external-system work:
- Good, especially for workloads heavy on deterministic preparation, validation, conversion, and publication variants.
- External calls can be nodes, but side-effect node idempotency must be designed carefully.

Advantages:
- Strong for lineage
- Supports partial recomputation
- Supports reuse
- Supports parallel expansion
- Good for deterministic substructure

Drawbacks:
- Less natural for open-ended agent loops
- Easy to force exploratory work into an unnatural DAG
- Graph management grows complicated when goals drift

## Model 3: Blackboard Obligations / Evidence / Actions

Core abstract unit: an item on a blackboard such as an obligation, question, hypothesis, evidence record, proposal, or objection.

State surfaces:
- `event store` is the blackboard log itself.
- `artifact store` holds source evidence, context bundles, execution products, and external receipts.
- `local workspace` is used by a specialist handling a specific obligation.
- `runtime memory` holds current priorities, selection heuristics, and a local working set.

Flow:
- Task start injects initial obligations such as confirming the goal, collecting constraints, producing candidate actions, and validating external reachability.
- Each cycle picks one unresolved obligation.
- A specialist produces evidence or a proposal.
- Proposals can be accepted, rejected, or refined into new obligations.
- The process ends when no critical unresolved obligations remain.

Must be evented:
- Obligation creation
- Priority changes
- Evidence refs
- Proposals
- Acceptance or rejection
- Conflicts
- Human adjudication

Can stay local:
- Specialist scratch reasoning
- Temporary caches
- Non-critical temporary files

Error recovery and retry:
- A failure becomes a new unresolved obligation or objection, not just "step failed".
- Retry is re-deriving evidence or offering an alternative proposal for that obligation.
- Restart rebuilds the unresolved obligation set from events.

Fit for non-git-native and external-system work:
- Very strong, especially for ambiguous goals, changing constraints, and human-machine collaboration.

Advantages:
- Most free from four-stage assumptions
- Natural expression of uncertainty, disagreement, and waiting for human judgment
- Good fit for messy real-world tasks

Drawbacks:
- Highest implementation and observability cost
- Too heavy for simple tasks
- Lower throughput and intuition than simpler models

## D. Should Four Stages Remain the Main Abstraction?

No.

Four stages should at most be a view, a strategy template, or a default profile for one class of tasks. They should not be the runtime kernel abstraction.

Reasons:
1. They mistake time order for ontology.
2. They assume work can be cleanly divided into a few large blocks, which often fails for real external tasks.
3. They weaken rollback, repeated observation, local retry, and human intervention.
4. They carry editor, CI, and git-task bias into all workloads.

Suggested replacement:
- Make the primary abstraction "evented next-action selection".
- Use a decision-loop kernel.
- Optionally layer graph or blackboard task expressions on top.

## E. Recommended Model

Recommended model: event-driven decision loop.

Reason:
- It is the smallest and most stable kernel.
- It best matches the desired end state:
  - single-task agent loop
  - event store as source of truth
  - workspace as non-authoritative materialization
  - git as optional, not assumed
  - recovery and observability as first-class concerns

Concrete flow sketch:

1. `TaskAccepted`
- Record task goal, input refs, strategy config, and initial constraints.

2. `ProjectTaskView`
- Build the current view from the event stream.
- Derive known facts, unresolved questions, available artifacts, and retry budget.

3. `SelectNextEffect`
- A policy chooses the next step, for example:
  - `AcquireObservation`
  - `AssembleContextBundle`
  - `RunAgentTurn`
  - `InvokeExternalTool`
  - `ValidateOutcome`
  - `PublishResult`

4. `ExecuteEffect`
- If filesystem state is needed, rent a workspace and materialize the necessary inputs.
- Write large objects to the artifact store.
- Write summaries and refs to the event stream.

5. `RecordOutcome`
- On success, record observation, artifact, or receipt.
- On failure, record error class, retryability, suggested rollback point, and compensation data.

6. `Reproject`
- Recompute the task view from the event stream.
- If validation fails, go back to a new observation or a new agent turn rather than jumping to a fixed stage.

7. `Terminate`
- End on `CompletionAccepted` or `AbandonedWithReason`.
- Final output is an event chain plus artifact refs, not a process return value and not a workspace directory.

Interpretation:
- Preparation, interaction, and publication can still exist as projected views on top of this model.
- They should not define the kernel itself.

## F. Common Misleading Inertias from Editor / CI / Git Thinking

1. Treating the workspace as the source of truth.
In reality it is only the materialized environment for the current effect. What must survive restart is the event log and artifact refs.

2. Treating git commit, PR, and diff as default outputs.
Real external tasks may produce API receipts, form updates, reports, messages, screenshots, database records, or human confirmations.

3. Treating prepare-execute-publish as universal ontology.
Many tasks are observe, act locally, validate, observe again, and may repeat many times.

4. Treating logs as a side channel instead of eventing execution facts themselves.
If observability and recovery do not share the same event model, both become untrustworthy under failure.

5. Treating function return values or in-memory objects as recovery points.
After restart, the only reliable sources are the event log, artifacts, and external receipts.

6. Treating external reads as pure functions that can always be repeated.
Many external systems are time-varying; if a read affects later decisions, it should be snapshotted or versioned.

7. Treating retry as "rerun the whole job".
Effect-level, node-level, or obligation-level retry is usually more correct and preserves causality better.

8. Treating the agent transcript as the state object.
What really needs persistence is observations, proposals, artifact refs, and tool receipts useful for future decision-making, not an unbounded dialogue transcript.
