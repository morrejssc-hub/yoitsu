"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks.

Per ADR-0019: output_authority="live_runtime" — modifies live Factorio game state.
Per ADR-0018: uses capability-only lifecycle (needs=["factorio_runtime"]).
FactorioRuntimeCapability handles script sync + RCON setup/teardown.
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
    needs=["factorio_runtime"],
    output_authority="live_runtime",
)
def worker(**params) -> JobSpec:
    """Factorio worker role definition.

    Per ADR-0018/0019:
    - output_authority="live_runtime": drives live Factorio game state via RCON
    - needs=["factorio_runtime"]: capability handles script sync + RCON lifecycle
    - Runner provides bundle_workspace as cwd for live_runtime roles
    - No git publication (in-game actions are the output)
    """
    return JobSpec(
        context_fn=context_spec(
            system="factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        tools=["factorio_call_script"],
    )
