"""Implementer role: writes Lua scripts directly into the live bundle.

Per ADR-0019: output_authority="live_runtime" — modifies bundle files in-place.
Per ADR-0018: uses capability-only lifecycle (needs=[]).
Runner routes workspace to bundle_workspace for live_runtime roles.
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="implementer",
    description="Factorio bundle implementer (writes lua directly into the live bundle)",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
    needs=[],
    output_authority="live_runtime",
)
def implementer(**params) -> JobSpec:
    """Factorio Lua script implementer role definition.

    Per ADR-0018/0019:
    - output_authority="live_runtime": writes directly into bundle_workspace
    - needs=[]: no capability setup/finalize required
    - Runner provides bundle_workspace as cwd for live_runtime roles
    - No git publication (writes are immediate and live)
    - Serialization enforced by bundle scheduling (max_concurrent_jobs=1)
    """
    return JobSpec(
        context_fn=context_spec(
            system="factorio/prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        tools=["bash"],
    )
