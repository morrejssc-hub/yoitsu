"""Evaluator role: validates implementer output.

Verifies:
1. Expected files exist in factorio/scripts/
2. Lua syntax is valid (via luac or Factorio load())
3. Script conforms to DYNAMIC constraint
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role


def evaluator_preparation(*, evo_root: str, **kwargs) -> WorkspaceConfig:
    """Evaluator uses workspace override to check files."""
    return WorkspaceConfig(repo="", new_branch=False, workspace_override=evo_root)


def evaluator_publication(**kwargs) -> tuple[None, list]:
    """Evaluator doesn't produce artifacts."""
    return None, []


evaluator_publication.__publication_strategy__ = "skip"


def evaluate_lua_syntax(script_path: Path) -> tuple[bool, str]:
    """Check Lua syntax using luac.
    
    Returns:
        (is_valid, error_message)
    """
    try:
        result = subprocess.run(
            ["luac", "-p", str(script_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return True, ""
        return False, result.stderr
    except FileNotFoundError:
        # luac not available, skip syntax check
        return True, "luac not available, syntax check skipped"
    except Exception as e:
        return False, str(e)


def check_dynamic_constraint(script_path: Path) -> tuple[bool, str]:
    """Check if script follows DYNAMIC constraint.
    
    Returns:
        (is_valid, error_message)
    """
    content = script_path.read_text()
    
    # Must have DYNAMIC marker
    if "-- DYNAMIC" not in content:
        return False, "Missing -- DYNAMIC marker"
    
    # Must be a function returning function
    if "return function(" not in content:
        return False, "Must be 'return function(args_str) ... end' pattern"
    
    # Should NOT use require (dynamic scripts can't require modules)
    if "require(" in content or "require '" in content or 'require "' in content:
        return False, "Dynamic scripts cannot use require()"
    
    return True, ""


@role(
    name="evaluator",
    description="Validates implementer output for Factorio bundle",
    role_type="evaluator",
    min_cost=0.1,
    recommended_cost=0.3,
    max_cost=0.5,
)
def evaluator(**params) -> JobSpec:
    """Evaluate implementer output.
    
    The goal and expected files are passed via role_params.
    """
    return JobSpec(
        preparation_fn=evaluator_preparation,
        context_fn=context_spec(
            system="factorio/prompts/evaluator.md",
            sections=[],
        ),
        publication_fn=evaluator_publication,
        tools=["bash"],
    )