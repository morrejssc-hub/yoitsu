"""Default optimizer role: analyzes observation patterns and outputs ReviewProposal.

Per ADR-0010 Autonomous Review Loop:
- Analyzes observation events (budget_variance, tool_retry, etc.)
- Outputs structured ReviewProposal JSON for optimization tasks
- No git workspace needed (analysis-only role)
"""
from __future__ import annotations

from typing import Any

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def optimizer_preparation(**kwargs) -> WorkspaceConfig:
    """Optimizer doesn't need a git workspace.
    
    Returns:
        WorkspaceConfig with empty repo (analysis only)
    """
    return WorkspaceConfig(repo="", new_branch=False)


def optimizer_publication(**kwargs) -> tuple[None, list]:
    """Optimizer doesn't produce git commits.

    Output is the ReviewProposal JSON in summary field.
    
    Returns:
        (None, []) - no git ref, no artifact bindings
    """
    return None, []


optimizer_publication.__publication_strategy__ = "skip"


@role(
    name="optimizer",
    description="Analyzes observation patterns and outputs optimization proposals",
    role_type="optimizer",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
)
def optimizer(**params) -> JobSpec:
    """Default optimizer role definition.
    
    Per ADR-0010:
    - Receives observation context via role_params
    - Analyzes patterns and thresholds
    - Outputs ReviewProposal JSON in summary field
    - Publication strategy is 'skip' (no git commits)
    
    Expected role_params:
        metric_type: The observation metric that triggered this analysis
        observation_count: Number of observations in window
        window_hours: Time window for observations
    """
    return JobSpec(
        preparation_fn=optimizer_preparation,
        context_fn=context_spec(
            system="default/prompts/optimizer.md",
            sections=[],  # No additional sections needed
        ),
        publication_fn=optimizer_publication,
        tools=[],  # No special tools needed, just LLM analysis
    )