"""Global evaluator role - available to all teams."""

from palimpsest.runtime.roles import JobSpec, context_spec, role


@role(
    name="evaluator",
    description="Global evaluator role for task quality assessment",
    role_type="evaluator",
    min_cost=0.1,
    recommended_cost=0.3,
    max_cost=0.5,
)
def evaluator(**params):
    """Global evaluator role definition.
    
    Evaluates task semantic quality based on criteria and deliverables.
    """
    return JobSpec(
        preparation_fn=None,  # No workspace needed
        context_fn=context_spec(
            system="You are an evaluator agent. Assess task quality based on criteria.",
            sections=[],
        ),
        publication_fn=lambda **kw: (None, []),
        tools=[],  # No tools needed for evaluation
    )
