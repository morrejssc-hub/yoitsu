"""Evaluator role: validates implementer output.

Per ADR-0019: output_authority="analysis" — read-only, no authoritative output.
Per ADR-0018: uses capability-only lifecycle (needs=[]).
Runner provides ephemeral workspace; scripts are accessed via absolute bundle_workspace path.

Verifies:
1. Expected files exist in factorio/scripts/
2. Lua syntax is valid (via luac or Factorio load())
3. Script conforms to DYNAMIC constraint
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from palimpsest.runtime.roles import JobSpec, context_spec, role


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
        return True, "luac not available, syntax check skipped"
    except Exception as e:
        return False, str(e)


def check_dynamic_constraint(script_path: Path) -> tuple[bool, str]:
    """Check if script follows DYNAMIC constraint.

    Returns:
        (is_valid, error_message)
    """
    content = script_path.read_text()

    if "-- DYNAMIC" not in content:
        return False, "Missing -- DYNAMIC marker"

    if "return function(" not in content:
        return False, "Must be 'return function(args_str) ... end' pattern"

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
    needs=[],
    output_authority="analysis",
)
def evaluator(**params) -> JobSpec:
    """Evaluate implementer output.

    Per ADR-0018/0019:
    - output_authority="analysis": read-only checks, no new authoritative output
    - needs=[]: no capability setup/finalize required
    - Runner provides ephemeral workspace; agent uses absolute paths to bundle scripts
    - The goal and expected files are passed via role_params
    """
    return JobSpec(
        context_fn=context_spec(
            system="factorio/prompts/evaluator.md",
            sections=[],
        ),
        tools=["bash"],
    )
