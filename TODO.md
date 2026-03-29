# ADR-0007 Implementation TODO

## Batch 1 (Tasks 1-3) ✅ COMPLETE
- [x] Task 1: RoleMetadataReader in yoitsu-contracts
- [x] Task 2: Update SpawnTaskData schema
- [x] Task 3: Remove overrides from SpawnedJob/SpawnDefaults

## Batch 2 (Tasks 4-6) ✅ COMPLETE
- [x] Task 4: Update spawn_handler.py
- [x] Task 5: Update runtime_builder.py
- [x] Task 6: Add role catalog cache invalidation

## Batch 3 (Tasks 7-9) ✅ COMPLETE
- [x] Task 7: Update RoleManager to extend RoleMetadataReader
- [x] Task 8: Update runner.py for explicit goal parameter
- [x] Task 9: Update evo roles context_fn signatures (no changes needed)

## Batch 4 (Tasks 10-12) ✅ COMPLETE
- [x] Task 10: Update JobConfig schema documentation
- [x] Task 11: Full test suite verification (163 tests passed)
- [x] Task 12: Update ADR-0007 status to Accepted

---

## Implementation Summary

All 12 tasks completed successfully. ADR-0007 is now **Accepted**.

### Commits

```
yoitsu-contracts:
  a8641db feat: add RoleMetadataReader for AST-based role metadata extraction
  3c08286 feat: SpawnTaskData now has goal/budget/repo as first-class fields
  aa05ab8 docs: JobConfig field category documentation per ADR-0007

trenni:
  3ac77ac refactor: remove execution config overrides from SpawnedJob/SpawnDefaults
  05487d1 refactor: spawn_handler and runtime_builder per ADR-0007
  517d305 feat: role catalog cache invalidation on evo SHA change

palimpsest:
  a6d3db6 refactor: RoleManager extends RoleMetadataReader from yoitsu-contracts
  900fbfe refactor: runner passes goal explicitly, not via role_params

yoitsu (main):
  181b287 docs: ADR-0007 status changed to Accepted after implementation
```

### Test Results

| Package | Tests | Status |
|---------|-------|--------|
| yoitsu-contracts | 8 | ✅ Passed |
| trenni | 79 | ✅ Passed |
| palimpsest | 76 | ✅ Passed |
| **Total** | **163** | **✅ All Passed** |

## Batch 4 (Tasks 10-12)
- [ ] Task 10: Update JobConfig schema documentation
- [ ] Task 11: Full test suite verification
- [ ] Task 12: Update ADR-0007 status