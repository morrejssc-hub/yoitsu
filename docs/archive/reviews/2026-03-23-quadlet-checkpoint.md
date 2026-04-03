# Quadlet Checkpoint

> Historical note: this checkpoint describes the compatibility phase before the
> Podman-per-job runtime replaced the inner `subprocess` path.

Date: 2026-03-23

## What Was Verified

This checkpoint focused on the Podman Quadlet development deployment:

- one pod
- two long-lived containers
- `pasloe` isolated in its own container
- `trenni` plus short-lived `palimpsest` job subprocesses in the second container

End-to-end behavior was verified against a real remote repository:

- remote clone
- task execution
- git commit
- git push to a remote branch
- Pasloe/Trenni event completion

Validated target repository:

- `guan-spicy-wolf/palimpsest-test`

Successful end-to-end output:

- branch: `palimpsest/job/019d196e-22fd-7e70-8564-6583b12f2408`
- commit: `7e29ee52cd1eb858746f2e4d90b6e69eecbca0d4`
- file: `e2e/quadlet-e2e-20260323-144221.md`

## Quick Optimizations Applied

### 1. Deployment fast path for unchanged source

The Quadlet bootstrap scripts now cache the last installed git revision for:

- `pasloe`
- `trenni`
- `palimpsest`

If the mounted source repo HEAD has not changed, restart no longer recopies the
source tree and no longer reruns `pip install`.

This directly improves the common case:

- service restart after systemd reload
- service restart after health-check failure
- repeated local validation loops without code changes

### 2. Persistent pip cache

Both bootstrap scripts now use a pip cache rooted in the persistent state
volume. This reduces repeat download cost when reinstall is actually needed.

### 3. Keep the deployment goal narrow

Per ADR-0003, the Quadlet deployment keeps:

- outer boundary: Podman container
- inner job launch: `subprocess`

This avoids mixing deployment validation with nested sandbox-policy debugging.

## Fixes Proven During This Checkpoint

### Yoitsu

- `yoitsu up` event-loop/client shutdown issue fixed
- `yoitsu submit` now normalizes `repo_url -> repo`
- monitor script updated for `/control/status`

### Palimpsest

- config compatibility with `publication.strategy`
- HTTPS push path now supports authenticated publication
- duplicate auth header handling fixed for push
- local config file ignored via `.gitignore`

### Trenni

- job subprocess environment now forwards the configured git token env var

## Remaining Slow Point

The current `trenni` container still installs `git` on each fresh container
start because the base Python image does not include it.

This is now the main remaining startup cost after the fast-path work above.

The next practical optimization would be:

1. switch to a runtime image that already includes `git`, or
2. introduce a tiny prebuilt base image for the Quadlet deployment only

That would remove the repeating `apt-get install` path entirely.

## Checkpoint Decision

This checkpoint is good enough to treat the Quadlet deployment as:

- operationally usable for development validation
- able to verify remote git clone and push behavior
- still intentionally optimized for iteration speed over maximal hardening
