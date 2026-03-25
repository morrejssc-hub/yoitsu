# ADR-0003: 2026-03-25 Execution Workspace And Publication Sink Decoupling

- Status: Proposed, not implemented
- Date: 2026-03-25
- Related: ADR-0001, ADR-0002

## Context

The current Palimpsest runtime assumes one dominant shape of work:

- a job clones or initializes one git workspace
- the job performs work inside that workspace
- publication commits and optionally pushes back through that same workspace

That model fits code-change tasks well, but it is a poor fit for operational and
observability jobs such as:

- stack health inspection
- queue monitoring
- benchmark and report generation
- graph inspection and diagnosis
- runtime incident summaries

Those jobs often need:

- no source repository at all, or only a scratch workspace
- rich dynamic runtime context from Pasloe and Trenni
- a durable output sink that is not the same as the execution workspace

At the same time, arbitrary cross-repo mutation would significantly expand the
trust surface and operational complexity of the system.

We also observed an execution-model tension:

- `role` / prompt content is the stable SOP or accumulated skill
- `context` is the dynamic per-run fact set
- `goal` is the concrete intent for one job run

For one-shot jobs, a role that behaves like an embedded skill is often the
right abstraction, but dynamic eventstore state still needs a dedicated runtime
channel instead of being hidden in ad hoc prompt text forever.

## Decision

We intend to decouple **execution workspace** from **publication sink**, but
only through explicit publication strategies rather than arbitrary multi-repo
mutation.

### 1. Keep Same-Repo Code Publication As The Default

The default model remains:

- execute in a git workspace
- commit inside that workspace
- push back to that same repository

This remains the primary path for code-change tasks.

### 2. Introduce Explicit Publication Kinds

Future publication behavior should be modeled as explicit strategies, not as an
implicit assumption that output always belongs in the current workspace repo.

The intended strategies are:

- `same_repo`
  - current behavior
- `artifact_sink`
  - job may execute with `workspace.repo=""` or a scratch repo
  - runtime persists declared artifacts into a dedicated hidden artifact repo
- `event_only`
  - runtime emits structured completion data and does not require git output

### 3. Treat Workspace-Less Operational Jobs As First-Class

Operational jobs should be allowed to run with:

- `workspace.repo=""`
- a scratch local workspace only
- publication that does not require the agent to know about the final sink repo

This supports monitoring and reporting jobs without forcing them to pretend they
are source-code edit tasks.

### 4. Keep Publication Sink Hidden From The Agent In Artifact Mode

For `artifact_sink`, the agent should not directly see or operate on the final
artifact repository.

Instead:

- the agent writes agreed outputs such as `artifacts/report.md` and
  `artifacts/report.json`
- the runtime copies those outputs into the publication sink after the job
  completes
- the runtime records the resulting artifact reference in terminal job output

This minimizes instability from exposing historical report state to the agent.

### 5. Do Not Generalize To Arbitrary Multi-Repo Mutation

This ADR does **not** propose:

- letting a job freely read one repo and write another arbitrary repo
- broad cross-repo mutation as a default capability
- publication targets that are fully unconstrained at task time

The design goal is controlled publication-sink decoupling, not generic
multi-repo write power.

### 6. Use Roles For Stable Procedure, Context For Dynamic Facts

For these jobs:

- `role` should encode the stable monitoring or reporting procedure
- `context` should carry dynamic runtime facts such as status snapshots and
  recent failure summaries
- `goal` should remain the concrete request for the current run

This keeps operational know-how in stable roles while avoiding the anti-pattern
of forcing all dynamic state into long free-form prompts.

## Consequences

### Positive

- operational jobs no longer need to masquerade as source-repo edit tasks
- durable report output can exist without exposing the sink repo to the agent
- code publication and artifact publication become distinct, auditable paths
- prompt/context responsibilities become cleaner for one-shot jobs

### Tradeoffs

- runtime and publication code must grow a new strategy surface
- job completion handling must understand artifact collection semantics
- output contracts for artifact-producing roles must become explicit

### Non-Goals

- arbitrary multi-repo code mutation
- replacing Pasloe event output with git output
- making roles or prompts fully stateful across runs

## Implementation Notes

This ADR is intentionally forward-looking and is **not implemented yet**.

Expected implementation steps, when prioritized:

1. add explicit publication strategy values for `same_repo`, `artifact_sink`,
   and `event_only`
2. define the runtime contract for declared artifact paths
3. teach Palimpsest publication to collect artifacts from scratch workspaces
4. record sink references in terminal job results
5. add dedicated operational roles and dynamic context providers for eventstore
   snapshots

Until then, monitoring/reporting jobs may still rely on:

- `workspace.repo=""`
- stable role prompts
- ad hoc runtime queries through built-in tools such as `bash`

but those jobs do not yet have a first-class hidden artifact sink.
