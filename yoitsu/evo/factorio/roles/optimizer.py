"""Factorio-specific optimizer role.

Reads observation evidence (tool_name, arg_pattern, call_count, similarity, bundle)
and produces a ReviewProposal targeting factorio/scripts/ for tool evolution.
For dispatcher tools, the dispatched script name is encoded as `arg_pattern`.
"""
from __future__ import annotations

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def factorio_optimizer_preparation(**kwargs) -> WorkspaceConfig:
    """Optimizer doesn't need a git workspace.
    
    Returns:
        WorkspaceConfig with empty repo (analysis only)
    """
    return WorkspaceConfig(repo="", new_branch=False)


def factorio_optimizer_publication(**kwargs) -> tuple[None, list]:
    """Optimizer doesn't produce git commits.

    Output is the ReviewProposal JSON in summary field.
    
    Returns:
        (None, []) - no git ref, no artifact bindings
    """
    return None, []


factorio_optimizer_publication.__publication_strategy__ = "skip"


@role(
    name="optimizer",
    description="Factorio tool-evolution optimizer (analyzes tool_repetition evidence)",
    role_type="optimizer",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
)
def optimizer(**params) -> JobSpec:
    """Factorio-specific optimizer role definition.
    
    Per Factorio Tool Evolution MVP:
    - Receives observation evidence via role_params
    - Extracts script name from arg_pattern field
    - Outputs ReviewProposal targeting factorio/scripts/
    
    Expected role_params:
        metric_type: The observation metric (e.g., "tool_repetition")
        observation_count: Number of observations in window
        window_hours: Time window for observations
        evidence: List of observation event payloads with:
            - role: The role that triggered the observation
            - bundle: Bundle name (should be "factorio")
            - tool_name: Dispatcher tool name (e.g., "factorio_call_script(find_ore_basic)")
            - call_count: Number of repeated calls
            - arg_pattern: Script name for dispatcher tools
            - similarity: Argument similarity (0.0-1.0)
    """
    return JobSpec(
        preparation_fn=factorio_optimizer_preparation,
        context_fn=context_spec(
            system="factorio/prompts/optimizer.md",
            sections=[],  # Evidence goes via role_params, not context sections
        ),
        publication_fn=factorio_optimizer_publication,
        tools=[],  # No special tools needed, just LLM analysis
    )