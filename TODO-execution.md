# ADR-0004/0008/0009/0010 Implementation Tasks

## Completed ✅

- [x] Task 1: Add max_cost to RoleMetadata (ADR-0004 D1a) ✅
- [x] Task 2: Add observation event types (ADR-0010 D1) ✅
- [x] Task 3: Rename WorkspaceConfig to PreparationConfig (ADR-0009 D1) ✅
- [x] Task 4: Update role decorator to include max_cost (ADR-0004 D1a) ✅
- [x] Task 5: Validate max_cost at spawn time in Trenni (ADR-0004 D1a) ✅
- [x] Task 6: Remove cost-based termination in Palimpsest (ADR-0004 D1, D7) ✅
- [x] Task 7: Emit budget_variance observation in Trenni (ADR-0010 D5) ✅
- [x] Task 8: Allow spawn without role, default to planner (ADR-0008 D1) ✅
- [ ] Task 9: Rename workspace_fn to preparation_fn (ADR-0009 D1, D2) - Deferred to follow-up PR
- [x] Task 10: Add trigger evaluator scaffold (ADR-0008 D2, D3) ✅
- [x] Task 11: Run all tests and verify integration ✅

## Summary

**Tests: 185 passed**
- yoitsu-contracts: 16 passed
- palimpsest: 82 passed
- trenni: 87 passed

**Commits:**

```
yoitsu-contracts:
├── feat: add max_cost to RoleMetadata (ADR-0004 D1a)
├── feat: add observation event types (ADR-0010 D1)
├── feat: add PreparationConfig as canonical name (ADR-0009 D1)
└── feat: add cost field to JobCompletedData (ADR-0010 D5)

palimpsest:
├── feat: export PreparationConfig (ADR-0009 D1)
├── feat: add max_cost parameter to role decorator (ADR-0004 D1a)
├── feat: remove cost-based termination (ADR-0004 D1, D7)
└── feat: emit actual cost in JobCompletedData (ADR-0010 D5)

palimpsest/evo:
└── feat: add max_cost to all role definitions (ADR-0004 D1a)

trenni:
├── feat: validate spawn budget against role max_cost (ADR-0004 D1a)
├── feat: default spawn role to planner (ADR-0008 D1)
├── feat: add trigger evaluator scaffold (ADR-0008 D2, D3)
└── feat: emit budget_variance observation (ADR-0010 D5)
```

**Deferred to follow-up PR:**
- Task 9: workspace_fn → preparation_fn rename (large refactor)