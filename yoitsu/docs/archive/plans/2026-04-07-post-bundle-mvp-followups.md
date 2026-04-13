# Post-Bundle-MVP Followups

**Status:** Completed
**Date:** 2026-04-07
**Depends on:** `docs/superpowers/specs/2026-04-06-bundle-mvp-design.md`

## Completed

Bundle MVP is implemented and validated:

- bundle-only evo layout (`evo/<bundle>/...`) is live
- trenni control-plane `team` semantics were removed in favor of `bundle`
- end-to-end Bundle MVP smoke test passed in production path
- success criteria in the Bundle MVP spec were verified

The implementation plan for Bundle MVP has been archived to:
`docs/archive/plans/2026-04-07-bundle-mvp-implementation.md`

### Additional Fixes (2026-04-07)

1. **Fixed `env_allowlist` inheritance**
   - Bundle's `env_allowlist` replaces (not merges with) global config
   - Added `OPENAI_API_KEY` to factorio bundle's `env_allowlist`
   - Root cause: MockLLMGateway was being used because API key wasn't injected

2. **Fixed goal injection in `build_context`**
   - Previously: goal was skipped when sections (like factorio_scripts) were present
   - Now: goal is always inserted as first part of task message
   - This fix enables LLM to understand the actual task, not just context

3. **Added evo directory to palimpsest-job image**
   - Worker role requires `evo/factorio/lib/rcon.py` for RCON connection
   - Updated Containerfile to COPY evo directory into image

4. **Iron-chest task verified working**
   - Successfully placed iron-chest at (0,0) in Factorio
   - Full tool chain working: spawn agent → add inventory → move → place

## Remaining Work

1. ~~**Migrate `github_context` into bundle contexts**~~ ✅ DONE
   Move the remaining global/provider assumptions to `evo/<bundle>/contexts/`
   so the skipped tests can be re-enabled.

   *Result: Created evo/factorio/contexts/github_context.py. Updated tests to use
   resolve_context_functions. All 177 tests passing.*

2. ~~**Re-adapt autonomous review loop**~~ ✅ DONE
   Update `docs/plans/2026-04-04-autonomous-review-loop-output-closure.md`
   and its implementation path to the new `(bundle, role, goal, params)`
   submission contract.

   *Result: Updated observation events to include bundle field. _handle_optimizer_output
   now inherits bundle from parent job. Tests updated to use bundle instead of team.*

3. ~~**Run real Factorio verification**~~ ✅ DONE
   Re-run the iron-chest task and confirm whether the historical
   `factorio_call_script` zero-call behavior is gone under the bundle model.

   *Result: Iron-chest placed successfully at (0,0). Full tool chain verified.*

4. ~~**Decide whether role topology needs further changes**~~ ✅ DONE
   Only revisit planner/worker/implementer topology if the real task run
   still exposes routing or execution problems.

   *Result: Not needed - iron-chest task worked correctly*

5. **Choose publication path for local commits**
   Decide how to publish the accumulated local work across `yoitsu`,
   `palimpsest`, and `yoitsu-contracts`.

   *Status: Pending user decision - 28+5+7+10 = 50 commits ready to push*

## Test Results

```
trenni:     206 passed, 1 skipped
palimpsest: 177 passed, 1 warning
contracts:  120 passed
Total:      503 tests passing
```

## Not Needed For Bundle MVP Completion

- multi-repo bundle distribution
- bundle manifests
- backwards compatibility shims
- further topology expansion inside factorio bundle
