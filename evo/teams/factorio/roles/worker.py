"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks.

Per Factorio Tool Evolution MVP: The worker role is the primary executor
for Factorio-related tasks. It establishes an RCON connection during
preparation, uses factorio_call_script for tool execution, and does not
produce git commits (publication strategy = skip).
"""
from __future__ import annotations

import os
from typing import Any

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def factorio_worker_preparation(
    *,
    runtime_context: Any,
    evo_root: str,
    **params,
) -> WorkspaceConfig:
    """Connect RCON and register dynamic scripts.
    
    Per MVP design:
    - Existing scripts (using require) are pre-loaded by mod at startup
    - Only new dynamic scripts (with -- DYNAMIC marker) need RCON register
    - MVP phase: auto-registration deferred, rely on manual or context_fn
    
    Args:
        runtime_context: RuntimeContext to store RCON connection
        evo_root: Path to evo repository (for script discovery)
        
    Returns:
        WorkspaceConfig with empty repo (no git workspace needed)
    """
    from teams.factorio.lib.rcon import RCONClient
    
    # Connect RCON
    rcon = RCONClient(
        host=os.environ.get("FACTORIO_RCON_HOST", "localhost"),
        port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        password=os.environ.get("FACTORIO_RCON_PASSWORD", "changeme"),
    )
    rcon.connect()
    runtime_context.resources["rcon"] = rcon
    runtime_context.register_cleanup(rcon.close)
    
    # Worker doesn't need a git workspace
    return WorkspaceConfig(repo="", new_branch=False)


def factorio_worker_publication(**kwargs) -> tuple[None, list]:
    """Worker doesn't produce git commits.
    
    Returns:
        (None, []) - no git ref, no artifact bindings
    """
    return None, []


factorio_worker_publication.__publication_strategy__ = "skip"


@role(
    name="worker",
    description="Factorio in-game worker with RCON",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=2.0,
)
def worker(**params) -> JobSpec:
    """Factorio worker role definition.
    
    Per Factorio Tool Evolution MVP:
    - Uses RCON for in-game communication
    - Has access to factorio_call_script tool
    - Publication strategy is 'skip' (no git commits)
    - Context includes factorio_scripts section for script catalog
    """
    return JobSpec(
        preparation_fn=factorio_worker_preparation,
        context_fn=context_spec(
            system="teams/factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=factorio_worker_publication,
        tools=["factorio_call_script"],
    )