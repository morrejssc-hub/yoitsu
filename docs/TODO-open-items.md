# Open Items (2026-03-26)

## From ADR Implementation

1. **ADR-0005**: Extract intake/execution into separate supervisor loop components
   - Current: cursor timing fixed, but intake and execution still share the same loop
   - Priority: P2 (structural cleanup, no correctness impact)

2. **ADR-0006**: Evaluator-specific default role/prompt tuning
   - Current: eval job falls back to `default` role when `eval_spec.role` is omitted
   - Priority: P1 (directly affects eval output quality)

3. **ADR-0007**: Context window and cost budget hard stops
   - Current: only `max_iterations` implemented as hard budget
   - Priority: P1 (cost and context exhaustion need the same `budget_exhausted` path)

## From Original Issue List

4. **Issue 5**: Verify `publication.py:56` `result.get("status") == "failed"` branch
   - ADR-0006 implemented status propagation; confirm this guard now triggers correctly
   - File: `palimpsest/palimpsest/stages/publication.py:56`
   - Priority: P2 (verify, likely already working)
