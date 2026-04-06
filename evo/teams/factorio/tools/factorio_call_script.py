"""Dispatcher tool for calling Factorio mod scripts via RCON.

Per Factorio Tool Evolution MVP: This is the primary tool for the worker role
to execute in-game scripts. The tool dispatches to registered Lua scripts
via the RCON connection established in preparation_fn.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palimpsest.runtime.context import RuntimeContext
    from palimpsest.runtime.tools import ToolResult


def factorio_call_script(
    name: str,
    args: str = "",
    runtime_context: RuntimeContext | None = None,
) -> ToolResult:
    """Call a Factorio mod script via RCON.

    Args:
        name: script name (e.g. 'actions.place', 'atomic.teleport')
        args: argument string (typically JSON)

    Returns:
        ToolResult with success status and script output.
    """
    from palimpsest.runtime.tools import ToolResult
    
    if runtime_context is None or "rcon" not in runtime_context.resources:
        return ToolResult(success=False, output="No RCON connection available")

    rcon = runtime_context.resources["rcon"]
    command = f"/agent {name} {args}".strip()
    
    try:
        raw = rcon.send_command(command)
    except Exception as e:
        return ToolResult(success=False, output=f"RCON error: {e}")

    # RCON single packet ~4KB limit, truncate with prefix marker
    if len(raw.encode("utf-8")) >= 4000:
        raw = "[TRUNCATED 4KB]\n" + raw[:3900]

    return ToolResult(success=True, output=raw)


# Tool schema for LLM function calling
factorio_call_script.__tool_schema__ = {
    "type": "function",
    "function": {
        "name": "factorio_call_script",
        "description": "Call a Factorio mod script via RCON. The script must be registered in the mod.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Script name (e.g. 'actions.place', 'atomic.teleport')",
                },
                "args": {
                    "type": "string",
                    "description": "Argument string (typically JSON) passed to the script",
                    "default": "",
                },
            },
            "required": ["name"],
        },
    },
}

# Mark as tool for tool discovery
factorio_call_script.__is_tool__ = True