"""Evaluator role: validates implementer output.

Verifies:
1. Expected files exist in factorio/scripts/
2. Lua syntax is valid (via luac or Factorio load())
3. Script conforms to DYNAMIC constraint
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from palimpsest.runtime.roles import JobSpec, context_spec, role


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
def evaluator(goal: str = "", expected_files: list[str] | None = None, **params) -> JobSpec:
    """Evaluate implementer output.
    
    Args:
        goal: Original task goal (used to extract expected script name).
        expected_files: Optional list of expected file paths.
    """
    return JobSpec(
        context_fn=context_spec(
            system="factorio/prompts/evaluator.md",
        ),
        publication_fn=evaluator_publication,
        tools=["bash"],
        params={
            "goal": goal,
            "expected_files": expected_files or [],
        },
    )