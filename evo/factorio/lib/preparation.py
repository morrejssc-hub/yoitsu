"""Reusable preparation building blocks for Factorio bundle.

Each function returns a WorkspaceConfig (or operates on runtime_context as a side effect).
Roles compose these in their own preparation_fn. Future plan: replace per-role
preparation_fn with a list of these building blocks.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from palimpsest.config import WorkspaceConfig

logger = logging.getLogger(__name__)


def prepare_evo_workspace_override(*, evo_root: str, **kwargs) -> WorkspaceConfig:
    """Make the live evo_root the agent's workspace.
    
    Used by implementer-style roles that should write directly into the bundle.
    Caller is responsible for ensuring serialization (factorio bundle has a serial lock).
    
    Args:
        evo_root: Path to the evo root directory.
        
    Returns:
        WorkspaceConfig with workspace_override set to evo_root.
    """
    return WorkspaceConfig(repo="", new_branch=False, workspace_override=evo_root)


def prepare_factorio_runtime(
    *,
    runtime_context,
    evo_root: str,
    **kwargs,
) -> WorkspaceConfig:
    """Sync bundle scripts into the live Factorio mod, reload, then connect RCON.
    
    Per plan Task 4: worker preparation rebuilds Factorio runtime environment.
    
    Effects:
    - Copies/syncs evo_root/factorio/scripts/ -> $FACTORIO_MOD_SCRIPTS_DIR
    - Issues a reload command via RCON
    - Stores RCONClient in runtime_context.resources["rcon"]
    - Registers cleanup to close RCON
    
    Args:
        runtime_context: RuntimeContext to store resources and register cleanup.
        evo_root: Path to evo repository root.
        
    Returns:
        Empty WorkspaceConfig (worker doesn't need a workspace).
    
    Raises:
        RuntimeError: If FACTORIO_MOD_SCRIPTS_DIR not set or safety checks fail.
    """
    from factorio.lib.rcon import RCONClient
    
    src = Path(evo_root) / "factorio" / "scripts"
    dst_env = os.environ.get("FACTORIO_MOD_SCRIPTS_DIR")
    
    if not dst_env:
        raise RuntimeError(
            "FACTORIO_MOD_SCRIPTS_DIR must point to the live Factorio mod scripts directory"
        )
    dst = Path(dst_env)
    
    if not src.exists():
        raise RuntimeError(f"Bundle scripts dir missing: {src}")
    
    # Safety checks before destructive rmtree (per plan review)
    if dst.exists():
        # Prevent accidental deletion from misconfigured dst
        if dst == src:
            raise RuntimeError(f"dst == src, refusing to delete: {dst}")
        if str(dst) in ("/", "/usr", "/home", "/opt", "/var"):
            raise RuntimeError(f"dst is a system root directory, refusing to delete: {dst}")
        # Verify dst looks like a Factorio mod scripts directory
        if dst.name != "scripts":
            raise RuntimeError(
                f"dst path does not end in 'scripts', suspicious configuration: {dst}"
            )
        # Additional safety: refuse if dst has more than 100 files
        file_count = sum(1 for _ in dst.rglob("*") if _.is_file())
        if file_count > 100:
            raise RuntimeError(
                f"dst has {file_count} files (>100), refusing to delete (suspicious): {dst}"
            )
        logger.info(f"Removing existing mod scripts directory: {dst}")
        shutil.rmtree(dst)
    
    logger.info(f"Copying bundle scripts from {src} to {dst}")
    shutil.copytree(src, dst)
    
    # Connect RCON
    rcon = RCONClient(
        host=os.environ.get("FACTORIO_RCON_HOST", "localhost"),
        port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        password=os.environ.get("FACTORIO_RCON_PASSWORD", "changeme"),
    )
    rcon.connect()
    runtime_context.resources["rcon"] = rcon
    runtime_context.register_cleanup(rcon.close)
    logger.info("RCON connected")
    
    # Reload mod scripts so freshly synced files take effect
    # Note: RCONClient exposes send_command(), uses /silent-command for quiet execution
    reload_result = rcon.send_command(
        "/silent-command pcall(function() game.reload_script() end)"
    )
    logger.info(f"Mod scripts reload result: {reload_result}")
    
    # Worker doesn't need a git workspace
    return WorkspaceConfig(repo="", new_branch=False)