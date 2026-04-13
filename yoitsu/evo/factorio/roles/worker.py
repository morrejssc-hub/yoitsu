"""Factorio worker role: connects RCON, loads scripts, executes in-game tasks.

Per Factorio Optimization Loop Closure MVP: The worker role is the primary executor
for Factorio-related tasks. It syncs bundle scripts to the live mod, establishes
an RCON connection during preparation, uses factorio_call_script for tool execution,
and does not produce git commits (publication strategy = skip).
"""
from __future__ import annotations

import sys
from pathlib import Path

from palimpsest.runtime.roles import JobSpec, context_spec, role

# Role modules are loaded before evo_root is injected into sys.path.
# Add the bundle root (evo/factorio) so sibling imports work during resolution.
_BUNDLE_ROOT = Path(__file__).resolve().parents[1]
if str(_BUNDLE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BUNDLE_ROOT))

from lib.preparation import prepare_factorio_runtime


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