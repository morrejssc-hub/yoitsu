# Factorio Optimization Loop Closure - Smoke Test Runbook

**Date:** 2026-04-08
**Plan:** docs/plans/2026-04-07-factorio-optimization-loop-closure.md
**Status:** Collision fix live-verified. Implementer live write and worker mod-script sync are both fixed. Smoke resumed successfully, but step-reduction evidence is still inconclusive because the second-round worker immediately found 50 iron ore already in inventory.

## Implementation Summary

### Commits

**Main repo:**
- `7e98419` config: serialize factorio bundle (max_concurrent_jobs=1) ahead of workspace_override rollout
- `37cde0e` feat(factorio): add bundle-specific optimizer role with evidence-aware prompt
- `670969e` feat(factorio): implementer writes to live bundle
- `ca0bb64` fix(factorio): simplify import path in implementer role
- `3e9c205` feat(factorio): worker preparation reloads bundle scripts into live mod

**Trenni:**
- `0d356fb` feat(trenni): route optimizer spawn by observation bundle and pass evidence

**Palimpsest:**
- `94a5141` feat(palimpsest): honor workspace_override in preparation/finalization

**Contracts:**
- `e456dda` feat(contracts): add WorkspaceConfig.workspace_override

### Key Changes

1. **Task 1:** Observation aggregator extracts evidence (latest 5 events), supervisor routes optimizer by bundle
2. **Task 2:** Factorio-specific optimizer role with evidence-aware prompt
3. **Task 3:** workspace_override mechanism for implementer to write directly to live bundle
4. **Task 4:** Worker preparation syncs bundle scripts to mod and triggers reload

## Optimizer Proposal ID Collision Fix Verification

### Root Cause

`trenni.supervisor._handle_optimizer_output()` used to synthesize proposal trigger IDs from `job_id`:

```python
id=f"{job_id}-proposal"
```

For optimizer jobs, `job_id` starts with the parent task's 16-hex prefix, so `_root_task_id()` collapsed the proposal-trigger task back onto the optimizer task ID. That reused and overwrote the optimizer task/job record instead of creating a distinct implementer task.

### Fix

The synthetic proposal event now derives from the optimizer completion event ID instead:

```python
proposal_source_event_id = f"{event.id}-proposal"
```

This preserves stable replay/idempotency while ensuring the derived proposal task ID cannot collide with the optimizer task ID.

### Live Verification Evidence

- Targeted regression tests passed before live verification:
  - `cd /home/holo/yoitsu && .venv/bin/pytest -q trenni/tests/test_optimizer_output.py -k 'distinct_task_and_job_ids or source_event_id_uses_completion_event_id'`
- Live Trenni was restarted and site-packages was refreshed from the working tree.
- Verified installed live code now contains:

```python
proposal_source_event_id = f"{event.id}-proposal"
```

- Observed a real factorio optimizer completion followed by a distinct implementer task:
  - Optimizer task/job: `ea81cdc120cf1496` / `ea81cdc120cf1496-root`
  - Implementer task/job: `069d65f1b5ad760e` / `069d65f1b5ad760e-root`
- These IDs are distinct, confirming the collision is no longer overwriting the optimizer record.

## Smoke Test (Task 5)

**Prerequisites:**
- [ ] Factorio headless server running and accessible
- [ ] `FACTORIO_MOD_SCRIPTS_DIR` environment variable configured
- [ ] `FACTORIO_RCON_HOST`, `FACTORIO_RCON_PORT`, `FACTORIO_RCON_PASSWORD` set
- [ ] Trenni supervisor running
- [ ] Pasloe event store running

### Step 5.1: Prepare Task Input

```json
{
  "goal": "用挖矿机挖 50 个铁矿",
  "bundle": "factorio",
  "role": "worker"
}
```

### Step 5.2: First Round Execution

**Expected behavior:**
- Worker explores repeatedly using `find_ore_basic` or similar script
- Total steps: ~10-15
- `observation.tool_repetition` event emitted
- Aggregator triggers optimizer spawn with `bundle="factorio"`
- Optimizer outputs `improve_tool` proposal
- Implementer creates new script in `factorio/scripts/`

**Record results:**

| Metric | Expected | Actual |
|--------|----------|--------|
| Total steps | 10-15 | Not captured from control API |
| tool_repetition triggered | Yes | Yes (`Observation threshold exceeded: tool_repetition`) |
| arg_pattern | find_ore_basic | Yes — implementer goal references `arg_pattern: find_ore_basic` |
| optimizer spawn bundle | factorio | Yes (e.g. `ea81cdc120cf1496`, `469a4ac461581d2f`) |
| ReviewProposal action_type | improve_tool | Inferred from spawned implementer goal `scan_resources_in_radius.lua` |
| New script created | Yes | Yes — `evo/factorio/scripts/scan_resources_in_radius.lua` |
| Mod sync works | Yes | Yes — file appears under `/home/holo/factorio/mods/factorio-agent_0.1.0/scripts/scan_resources_in_radius.lua` |

### Step 5.3: Verify New Script

```bash
ls -la evo/factorio/scripts/
```

**Expected:** New `.lua` file present, content resembles radius scan or resource detection.

**Observed on 2026-04-08:**
- Initial blocker: implementer task `069d65f1b5ad760e` claimed success but the file was not present on disk.
- Root cause 1: job image `localhost/yoitsu-palimpsest-job:dev` was stale, so palimpsest runtime ignored `workspace_override` and wrote into `/tmp/palimpsest-*`.
- After rebuilding the job image, implementer writes were verified to land in live evo_root.
- Root cause 2: factorio worker jobs only received `FACTORIO_MOD_SCRIPTS_DIR` as an environment variable, not a host bind mount; after adding the RW mount, preparation then failed because it tried to `rmtree()` the bind-mounted directory itself.
- Final fix: mount the host mod scripts directory read-write into worker jobs, then clear directory contents instead of deleting the mountpoint.
- Verified outcomes:
  - `evo/factorio/scripts/scan_resources_in_radius.lua` exists
  - `/home/holo/factorio/mods/factorio-agent_0.1.0/scripts/scan_resources_in_radius.lua` exists

### Step 5.4: Second Round Execution

Trigger same task again. Worker preparation should:
1. Sync bundle scripts to mod directory
2. Issue `/silent-command pcall(function() game.reload_script() end)`
3. Connect RCON
4. New script should be available

**Record results:**

| Metric | First Round | Second Round |
|--------|-------------|--------------|
| Total steps | Not captured from control API | Not meaningful in this rerun |
| Scripts used | `find_ore_basic` repetition inferred from optimizer evidence | Worker attempted `scan_resources_in_radius`, then completed because inventory already had 50 iron ore |

**Target:** Second round steps significantly lower (1-2 vs 10-15).

**Observed limitation:** In the final rerun, the worker completed immediately because the player inventory already contained 50 iron ore. That means the environment was no longer suitable for measuring step reduction, even though the optimized script sync path was verified.

### Step 5.5: Runbook Archive

After completion, archive:
- First round trajectory
- Second round trajectory
- New script content
- Step comparison

## Environment Variables Required

```bash
export FACTORIO_MOD_SCRIPTS_DIR=/path/to/factorio/mod/scripts
export FACTORIO_RCON_HOST=localhost
export FACTORIO_RCON_PORT=27015
export FACTORIO_RCON_PASSWORD=your_password
```

## Notes

- Live refresh caveat: `~/.config/containers/systemd/yoitsu/bin/start-trenni.sh` refreshes source installs based on `git rev-parse HEAD`, so uncommitted working-tree changes do not automatically propagate on restart. For this verification, the live Trenni venv/source cache had to be cleared manually before restart.

- The `game.reload_script()` command may not fully reload scripts with `require` caching
- Fallback: restart Factorio server between rounds
- If `factorio_call_script` mod has script whitelist, ensure new scripts are allowed

## Success Criteria

- [x] Two rounds execute without manual intervention
- [ ] Step count reduction observed
- [x] New script appears in bundle
- [x] Evidence correctly routed to factorio optimizer