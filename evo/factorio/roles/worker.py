"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks.

Per Factorio Optimization Loop Closure MVP: The worker role is the primary executor
for Factorio-related tasks. It syncs bundle scripts to the live mod, establishes
an RCON connection during preparation, uses factorio_call_script for tool execution,
and does not produce git commits (publication strategy = skip).
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role

# Import from bundle lib - works when evo_root is on sys.path (runner.py ensures this)
from factorio.lib.preparation import prepare_factorio_runtime


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
    
    Per Factorio Optimization Loop Closure MVP:
    - Syncs bundle scripts to live mod during preparation
    - Reloads mod scripts for newly written scripts to take effect
    - Uses RCON for in-game communication
    - Has access to factorio_call_script tool
    - Publication strategy is 'skip' (no git commits)
    - Context includes factorio_scripts section for script catalog
    """
    return JobSpec(
        preparation_fn=prepare_factorio_runtime,
        context_fn=context_spec(
            system="factorio/prompts/worker.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=factorio_worker_publication,
        tools=["factorio_call_script"],
    )