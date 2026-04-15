"""Implementer role: writes Lua scripts into the bundle.

Per ADR-0021: bundle-authoring role.
- target_source.uri == bundle_source.uri, ref="evolve" (same-source dual worktree)
- needs=["git_workspace"]: uses per-bundle git_workspace for commit+push to evolve
- Runner routes cwd via capability.workspace_ready event (ADR-0021 A.6)
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="implementer",
    description="Factorio bundle implementer (writes lua and pushes to evolve)",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
    needs=["git_workspace"],  # ADR-0021: per-bundle git_workspace
    output_authority="live_runtime",  # ADR-0019: retained but not read by runner
)
def implementer(**params) -> JobSpec:
    """Factorio Lua script implementer role definition.

    Per ADR-0021:
    - Bundle-authoring role: target is same bundle repo at evolve ref
    - needs=["git_workspace"]: per-bundle capability returns cwd + handles push
    - Same-source dual worktree from Trenni (RO@sha + RW@evolve)
    - git_workspace provides cwd via capability.workspace_ready
    - Serialization enforced by bundle scheduling (max_concurrent_jobs=1)
    """
    return JobSpec(
        context_fn=context_spec(
            system="prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        tools=["bash"],
    )
