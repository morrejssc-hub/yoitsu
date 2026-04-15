"""Factorio-specific optimizer role.

Reads observation evidence (tool_name, arg_pattern, call_count, similarity, bundle)
and produces a ReviewProposal targeting factorio/scripts/ for tool evolution.
For dispatcher tools, the dispatched script name is encoded as `arg_pattern`.

Per ADR-0018 Capability-Only Role Lifecycle:
- needs=[] means no extra capability requirements
- No preparation_fn or publication_fn (unified lifecycle)
- Output goes via summary field in interaction result
"""
from __future__ import annotations

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="optimizer",
    description="Factorio tool-evolution optimizer (analyzes tool_repetition evidence)",
    role_type="optimizer",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.0,
    needs=[],  # ADR-0018: Explicit empty capability (analysis-only)
)
def optimizer(**params) -> JobSpec:
    """Factorio-specific optimizer role definition.
    
    Per Factorio Tool Evolution MVP:
    - Receives observation evidence via role_params
    - Extracts script name from arg_pattern field
    - Outputs ReviewProposal targeting factorio/scripts/
    - No capability needed (analysis-only role)
    
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
        context_fn=context_spec(
            system="prompts/optimizer.md",
            sections=[],  # Evidence goes via role_params, not context sections
        ),
        tools=[],  # No special tools needed, just LLM analysis
    )