"""Inject Factorio script catalog into task context.

Per Factorio Tool Evolution MVP: Scans teams/factorio/scripts/ directory
and generates a markdown list of available scripts for the worker prompt.
"""
from __future__ import annotations

import re
from pathlib import Path


def factorio_scripts(*, evo_root: str, **_) -> str:
    """Scan teams/factorio/scripts/ and return catalog as markdown list.
    
    This context provider is injected into the worker's task message,
    providing a dynamic list of available scripts based on the current
    state of the evo repository.
    
    Args:
        evo_root: Path to the evo repository root
        
    Returns:
        Markdown-formatted list of available scripts with descriptions.
    """
    scripts_dir = Path(evo_root) / "teams" / "factorio" / "scripts"
    if not scripts_dir.exists():
        return "No scripts found."

    catalog = []
    for lua_path in sorted(scripts_dir.rglob("*.lua")):
        rel = lua_path.relative_to(scripts_dir).with_suffix("")
        name = str(rel).replace("/", ".")
        
        # Extract first line comment as description
        desc = ""
        try:
            lines = lua_path.read_text(encoding="utf-8").splitlines()
            if lines and (m := re.match(r"--\s*(.+)", lines[0])):
                desc = m.group(1).strip()
        except Exception:
            pass
            
        if desc:
            catalog.append(f"- `{name}` — {desc}")
        else:
            catalog.append(f"- `{name}`")

    return "\n".join(catalog) if catalog else "No scripts available."


# Mark as context provider for discovery
factorio_scripts.__is_context__ = True
factorio_scripts.__section_type__ = "factorio_scripts"