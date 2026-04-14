"""Factorio runtime capability.

Handles Factorio-specific runtime lifecycle per ADR-0018/ADR-0019:
- setup: sync bundle scripts to live mod dir + connect RCON
- finalize: close RCON connection

Used by the worker role (output_authority="live_runtime", needs=["factorio_runtime"]).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from loguru import logger
from yoitsu_contracts import FinalizeResult, EventData


class FactorioRuntimeCapability:
    """Factorio runtime service capability.

    Manages the Factorio-specific runtime environment for the worker role:
    - Syncs bundle scripts to live Factorio mod directory
    - Establishes and stores RCON connection in ctx.resources["rcon"]
    - Reloads mod scripts after sync
    - Closes RCON on finalize
    """

    name = "factorio_runtime"

    def setup(self, ctx) -> list[EventData]:
        """Setup Factorio runtime environment.

        Effects:
        - Syncs bundle_workspace/factorio/scripts/ to $FACTORIO_MOD_SCRIPTS_DIR
        - Reloads mod scripts via RCON
        - Stores RCONClient in ctx.resources["rcon"]

        Returns:
            List of EventData for runtime to emit.
        """
        from factorio.lib.rcon import RCONClient

        events: list[EventData] = []
        events.append(EventData(type="factorio_runtime.setup_started", data={
            "bundle": ctx.bundle,
            "job_id": ctx.job_id,
        }))

        # Sync bundle scripts to live mod directory
        src = Path(ctx.bundle_workspace) / "factorio" / "scripts"
        dst_env = os.environ.get("FACTORIO_MOD_SCRIPTS_DIR")
        if not dst_env:
            raise RuntimeError(
                "FACTORIO_MOD_SCRIPTS_DIR must point to the live Factorio mod scripts directory"
            )
        dst = Path(dst_env)

        if not src.exists():
            raise RuntimeError(f"Bundle scripts dir missing: {src}")

        # Safety checks before destructive sync
        if dst.exists():
            if dst == src:
                raise RuntimeError(f"dst == src, refusing to delete: {dst}")
            if str(dst) in ("/", "/usr", "/home", "/opt", "/var"):
                raise RuntimeError(f"dst is a system root directory, refusing: {dst}")
            if dst.name != "scripts":
                raise RuntimeError(f"dst does not end in 'scripts', suspicious: {dst}")
            file_count = sum(1 for _ in dst.rglob("*") if _.is_file())
            if file_count > 100:
                raise RuntimeError(
                    f"dst has {file_count} files (>100), refusing to delete: {dst}"
                )
            logger.info(f"Clearing mod scripts directory: {dst}")
            for child in dst.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        else:
            dst.mkdir(parents=True, exist_ok=True)

        logger.info(f"Syncing bundle scripts {src} -> {dst}")
        for child in src.iterdir():
            target = dst / child.name
            if child.is_dir():
                shutil.copytree(child, target)
            else:
                shutil.copy2(child, target)

        events.append(EventData(type="factorio_runtime.scripts_synced", data={
            "src": str(src),
            "dst": str(dst),
        }))

        # Connect RCON
        rcon = RCONClient(
            host=os.environ.get("FACTORIO_RCON_HOST", "localhost"),
            port=int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
            password=os.environ.get("FACTORIO_RCON_PASSWORD", "changeme"),
        )
        rcon.connect()
        ctx.resources["rcon"] = rcon
        logger.info("RCON connected")

        # Reload mod scripts so freshly synced files take effect
        reload_result = rcon.send_command(
            "/silent-command pcall(function() game.reload_script() end)"
        )
        logger.info(f"Mod scripts reload: {reload_result}")

        events.append(EventData(type="factorio_runtime.rcon_connected", data={
            "host": os.environ.get("FACTORIO_RCON_HOST", "localhost"),
            "port": int(os.environ.get("FACTORIO_RCON_PORT", "27015")),
        }))

        return events

    def finalize(self, ctx) -> FinalizeResult:
        """Close RCON connection.

        Returns:
            FinalizeResult with events and success=True (RCON close is non-critical).
        """
        events: list[EventData] = []

        rcon = ctx.resources.pop("rcon", None)
        if rcon is not None:
            try:
                rcon.close()
                logger.info("RCON connection closed")
                events.append(EventData(type="factorio_runtime.rcon_closed", data={
                    "job_id": ctx.job_id,
                }))
            except Exception as e:
                logger.warning(f"RCON close failed (non-critical): {e}")
                events.append(EventData(type="factorio_runtime.rcon_close_failed", data={
                    "job_id": ctx.job_id,
                    "error": str(e),
                }))

        events.append(EventData(type="factorio_runtime.finalize_completed", data={
            "bundle": ctx.bundle,
            "job_id": ctx.job_id,
        }))

        return FinalizeResult(events=events, success=True)
