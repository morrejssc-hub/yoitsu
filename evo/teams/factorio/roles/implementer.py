"""Implementer role: writes Lua scripts in factorio-agent repo.

Per Factorio Tool Evolution MVP: The implementer role is spawned by the
optimizer when a tool_repetition pattern is detected. It writes new Lua
scripts to teams/factorio/scripts/ with path allowlist enforcement.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

from palimpsest.config import WorkspaceConfig
from palimpsest.runtime.roles import JobSpec, context_spec, role, workspace_config, git_publication


def implementer_publication(
    *,
    workspace_path: str,
    **kwargs,
) -> tuple[str | None, list]:
    """Path allowlist: only allow writes to teams/factorio/scripts/ and mod/scripts/.
    
    Checks ALL changes (staged + unstaged + untracked) before git_publication's
    `git add -A` runs. This prevents bypassing the allowlist by leaving files
    unstaged.
    
    Raises:
        ValueError: If changes are detected outside the allowed paths.
    """
    # Check ALL changes (staged, unstaged, untracked) using git status --porcelain
    # This catches files that git_publication would later add via `git add -A`
    result = subprocess.run(
        ["git", "-C", workspace_path, "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    
    # Parse porcelain output: "XY PATH" or "XY OLD -> NEW" for renames
    # Note: XY are exactly 2 chars at positions 0-1, space at position 2
    changed = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        # Check for rename (contains " -> ")
        if " -> " in line:
            # Rename: extract the NEW_PATH (destination)
            # Format: "XY OLD_PATH -> NEW_PATH"
            parts = line.split(" -> ")
            path = parts[-1].strip()
        else:
            # Normal change: path starts at position 3 (after XY + space)
            # XY are exactly 2 chars (e.g., " M", "M ", "??", "MM")
            path = line[3:].strip()
        if path:
            changed.append(path)
    
    # Check path allowlist
    forbidden = [
        p for p in changed
        if not p.startswith("teams/factorio/scripts/") and not p.startswith("mod/scripts/")
    ]
    
    if forbidden:
        raise ValueError(f"Implementer wrote outside allowlist: {forbidden}")
    
    # Call git_publication with branch strategy
    pub_fn = git_publication(strategy="branch")
    return pub_fn(workspace_path=workspace_path, **kwargs)


@role(
    name="implementer",
    description="Factorio Lua script implementer",
    role_type="worker",
    min_cost=0.1,
    recommended_cost=0.5,
    max_cost=1.5,
)
def implementer(**params) -> JobSpec:
    """Factorio Lua script implementer role definition.
    
    Per Factorio Tool Evolution MVP:
    - Writes Lua scripts to teams/factorio/scripts/
    - Uses bash tool for file operations
    - Path allowlist enforced in publication (checks all changes before git add -A)
    - Publication creates a new branch for review
    """
    return JobSpec(
        preparation_fn=workspace_config(
            repo=os.environ.get(
                "FACTORIO_AGENT_REPO",
                "https://github.com/org/factorio-agent"
            ),
            init_branch="master",
            new_branch=True,
        ),
        context_fn=context_spec(
            system="teams/factorio/prompts/implementer.md",
            sections=[{"type": "factorio_scripts"}],
        ),
        publication_fn=implementer_publication,
        tools=["bash"],  # Only bash for file operations
    )