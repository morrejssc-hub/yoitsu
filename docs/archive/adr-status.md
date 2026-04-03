# ADR Status and Reorganization

Date: 2026-04-02

## Current ADR Inventory

| ADR | Title | Status | Current Validity |
|-----|-------|--------|-----------------|
| 0001 | System Architecture | Accepted | Valid, but needs update for artifact store |
| 0002 | Task and Job Lifecycle | Accepted | Valid, stable |
| 0003 | Runtime Execution Architecture | Accepted | Valid, stable |
| 0004 | Budget System | Accepted (Revised) | Valid, stable |
| 0005 | CLI Task Observability | Accepted | Valid, partially implemented |
| 0006 | Task-Level Publication via Planner Tool | Proposed | Valid, not yet implemented |
| 0007 | Task/Job Information Boundary | Accepted | Valid, implemented |
| 0008 | Task Creation and Ingestion | Accepted | Valid, implemented |
| 0009 | Preparation and Publication Functions | Accepted | Valid, implemented |
| 0010 | Self-Optimization Governance | Accepted | Valid, phases 1-2 in progress |
| 0011 | Team as First-Class Isolation Boundary | Accepted | Valid, implemented |
| 0012 | Factorio as Stateful Task Source | Proposed | Valid, depends on ADR-0011 |
| 0013 | Artifact Store | Proposed | New, under review |

## Overlap Analysis

Several ADRs cover overlapping ground due to incremental evolution:

### Runtime cluster: 0003, 0009, 0011

- ADR-0003 defines the four-stage pipeline and role model
- ADR-0009 renames workspace->preparation, broadens semantics
- ADR-0011 adds team-aware resolution, RuntimeContext, two-layer evo

These three together define the current Palimpsest runtime. They are
consistent but spread across three documents. A future consolidation
could merge them into a single "Runtime Execution Contract" ADR.

### Task semantics cluster: 0002, 0007, 0008

- ADR-0002 defines task/job lifecycle, verdicts, spawn, idle detection
- ADR-0007 defines information boundaries (goal/budget/repo channels)
- ADR-0008 defines task creation, ingestion, default role

These define the task/job contract. They are consistent. Could be
consolidated into "Task and Spawn Contract" but no urgency.

### Standalone ADRs (no overlap)

- ADR-0004 (budget): self-contained
- ADR-0005 (CLI observability): self-contained
- ADR-0006 (task-level publication): self-contained, not yet implemented
- ADR-0010 (self-optimization): self-contained
- ADR-0012 (Factorio): domain-specific, depends on 0011
- ADR-0013 (artifact store): new infrastructure

## Updates Needed

### ADR-0001: System Architecture

Should be updated to reflect:
- Artifact store as a new persistence layer alongside Pasloe
- "Dual source of truth" framing (events + artifacts) replacing
  "git + events"
- Artifact store configuration in Trenni
- Container mount/access mechanism for artifact store

### ADR-0003: Runtime Execution Architecture

Should be updated to reflect:
- publication_fn's canonical output is artifact bindings, git_ref is
  compatibility receipt
- RuntimeContext carries artifact_backend
- workspace is a private copy materialized from artifacts (not only git)

### ADR-0012: Factorio Task Source

Should be updated when artifact store is implemented:
- World checkpoint stored as tree artifact instead of ad-hoc save
- Publication produces artifact bindings, not just git_ref
- RCON logs stored as blob artifacts

### Events (yoitsu-contracts)

- JobCompletedData needs artifact_bindings field
- JobStartedData may need input artifact_bindings field

## Recommended Reorganization

### Phase 1: No changes needed now

All ADRs are internally consistent and match the implemented code.
ADR-0013 is the only new addition. No existing ADR needs immediate
rewriting.

### Phase 2: After ADR-0013 implementation

Update ADR-0001 and ADR-0003 to reflect artifact store integration.
Update ADR-0012 if Factorio implementation proceeds.

### Phase 3: Optional consolidation (low priority)

If the ADR count becomes a readability burden, consider merging:
- 0003 + 0009 + 0011 -> "Runtime Execution Contract"
- 0002 + 0007 + 0008 -> "Task and Spawn Contract"

This is cosmetic, not structural. The current ADRs are correct.

## Non-ADR Documentation

### Active reference documents

| Document | Status | Notes |
|----------|--------|-------|
| docs/architecture.md | Outdated | Predates artifact store; to be replaced |
| docs/test-operations.md | Valid | Testing procedures |
| docs/TODO-open-items.md | Valid | Implementation gaps |
| TODO.md | Valid | Roadmap and cleanup items |
| README.md | Valid | Quick start guide |

### Historical / exploratory (retain but not normative)

| Document | Status | Notes |
|----------|--------|-------|
| docs/event-artifact-runtime-redesign.md | Historical | Redesign exploration; conclusions in redesign-evaluation.md |
| docs/notes/2026-04-01-subagent-event-runtime-ideas.md | Historical | Three alternative runtime models explored |
| docs/plans/*.md | Historical | Implementation plans for completed ADRs |
| docs/reviews/*.md | Historical | Architecture reviews and test reports |
| docs/planner-spawn-eval-smoke-gap.md | Historical | Early smoke test observations |
| docs/planner-task-granularity-observation.md | Historical | Task granularity analysis |

### Other AI-generated documentation

| Document | Status | Notes |
|----------|--------|-------|
| docs/codex/2026-04-02-merged-architecture.md | Draft | Codex's architecture merge attempt |
| docs/codex/2026-04-02-adr-reduction-plan.md | Draft | Codex's ADR consolidation plan |

## Roadmap Alignment

Current five-step roadmap (from TODO.md) is unaffected by artifact store:

1. GitHub client -- no artifact dependency
2. External task inflow -- no artifact dependency
3. Reviewer role -- no artifact dependency
4. Pasloe query capability -- no artifact dependency
5. Self-optimization loop -- may benefit from artifact-based signal storage

ADR-0013 implementation can proceed in parallel with roadmap phases 1-3.
The artifact store becomes load-bearing when non-git task sources (Factorio,
monitoring) need to record their outputs.
