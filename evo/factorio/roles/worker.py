"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks.

Per ADR-0021:
- needs=["factorio_runtime", "factorio_mount"]: control-plane mount + job-side runtime
- factorio_mount (control_plane): prepares volume mount + RCON env vars before launch
- factorio_runtime (job_side): syncs scripts + handles RCON lifecycle
- No target workspace (live-runtime side effects only)
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="worker",
    description="Factorio in-game worker with RCON",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=2.0,
    needs=["factorio_runtime", "factorio_mount"],  # ADR-0021: control-plane + job-side
    output_authority="live_runtime",  # ADR-0019: retained but not read by runner
)
def worker(**params) -> JobSpec:
    """Factorio worker role definition.

    Per ADR-0021:
    - factorio_mount (control_plane): Trenni runs in subprocess before launch
      - Creates RW volume mount for mod scripts
      - Sets FACTORIO_MOD_SCRIPTS_DIR, FACTORIO_RCON_HOST/PORT env vars
    - factorio_runtime (job_side): runs in container after launch
      - Syncs bundle scripts to live mod dir
      - Connects RCON and stores in ctx.resources["rcon"]
    - No git publication (in-game actions are the output)
    """
    return JobSpec(
        context_fn=context_spec(
            system="prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        tools=["factorio_call_script"],
    )
