"""Implementer role: writes Lua scripts directly into live bundle.

Per Factorio Optimization Loop Closure MVP:
- Uses workspace_override to write directly into evo_root
- No git repo, no publication
- Path safety enforced by bundle container isolation + max_concurrent_jobs=1
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role

# Import from bundle lib - works when evo_root is on sys.path (runner.py ensures this)
from factorio.lib.preparation import prepare_evo_workspace_override


def implementer_publication(**kwargs) -> tuple[None, list]:
    """Implementer doesn't produce git commits.

    Output is written directly into the live bundle.
    
    Returns:
        (None, []) - no git ref, no artifact bindings
    """
    return None, []


implementer_publication.__publication_strategy__ = "skip"


@role(
    name="implementer",
    description="Factorio bundle implementer (writes lua directly into the live bundle)",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
)
def implementer(**params) -> JobSpec:
    """Factorio Lua script implementer role definition.
    
    Per Factorio Optimization Loop Closure MVP:
    - Uses workspace_override to write directly into evo_root
    - Bash tool's cwd naturally lands in the bundle directory
    - No git publication (writes are immediate and live)
    - Serialization enforced by bundle scheduling (max_concurrent_jobs=1)
    """
    return JobSpec(
        preparation_fn=prepare_evo_workspace_override,
        context_fn=context_spec(
            system="factorio/prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=implementer_publication,
        tools=["bash"],  # Only bash for file operations
    )