"""Optimizer role: analyzes observation events and proposes improvements.

Per ADR-0010: The optimizer receives observation events from the aggregation
layer and outputs structured ReviewProposal JSON for spawning improvement tasks.
"""
from __future__ import annotations

from typing import Any

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def optimizer_preparation(*, goal: str = "", **params) -> WorkspaceConfig:
    """Optimizer doesn't need a git workspace."""
    return WorkspaceConfig(repo="", new_branch=False)


def optimizer_publication(*, result: dict[str, Any], **_) -> tuple[None, list]:
    """Optimizer output is the ReviewProposal JSON in summary.
    
    The supervisor parses this and spawns the appropriate task.
    """
    return None, []


optimizer_publication.__publication_strategy__ = "skip"


@role(
    name="optimizer",
    description="Analyzes observation events and proposes improvements",
    role_type="planner",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
)
def optimizer(**params) -> JobSpec:
    """Optimizer role definition.
    
    Per ADR-0010:
    - Analyzes observation events
    - Outputs ReviewProposal JSON in summary
    - No git workspace needed
    - Publication strategy is 'skip'
    """
    return JobSpec(
        preparation_fn=optimizer_preparation,
        context_fn=context_spec(
            system="prompts/optimizer.md",
            sections=[],
        ),
        publication_fn=optimizer_publication,
        tools=[],  # No tools needed for analysis
    )