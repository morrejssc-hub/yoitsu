# Post-Bundle-MVP Followups

**Status:** Open follow-up work after Bundle MVP completion
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

## Remaining Work

1. **Migrate `github_context` into bundle contexts**
   Move the remaining global/provider assumptions to `evo/<bundle>/contexts/`
   so the skipped tests can be re-enabled.

2. **Re-adapt autonomous review loop**
   Update `docs/plans/2026-04-04-autonomous-review-loop-output-closure.md`
   and its implementation path to the new `(bundle, role, goal, params)`
   submission contract.

3. **Run real Factorio verification**
   Re-run the iron-chest task and confirm whether the historical
   `factorio_call_script` zero-call behavior is gone under the bundle model.

4. **Decide whether role topology needs further changes**
   Only revisit planner/worker/implementer topology if the real task run
   still exposes routing or execution problems.

5. **Choose publication path for local commits**
   Decide how to publish the accumulated local work across `yoitsu`,
   `palimpsest`, and `yoitsu-contracts`.

## Not Needed For Bundle MVP Completion

- multi-repo bundle distribution
- bundle manifests
- backwards compatibility shims
- further topology expansion inside factorio bundle
