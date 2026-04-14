"""Factorio mount capability (control-plane) per ADR-0021.

Control-plane capability that prepares the Factorio mount topology:
- Mounts mod scripts directory RW so worker can sync scripts
- Sets env vars for RCON connection info

Per ADR-0021: surface="control_plane" — runs in Trenni subprocess before job launch.
Returns launch-modifying events (control_plane.volume_mount, control_plane.env_set).
"""

from __future__ import annotations

import logging
import os

from loguru import logger
from yoitsu_contracts import FinalizeResult, EventData
from yoitsu_contracts.control_plane import ControlPlaneContext


class FactorioMountCapability:
    """Control-plane capability for Factorio mount topology.

    Per ADR-0021: runs in Trenni subprocess at master@switched_sha.
    Returns launch-modifying events that Trenni applies to RuntimeSpecBuilder
    and emits to event store.

    Setup:
    - Returns volume_mount for mod scripts directory
    - Returns env_set for RCON connection info

    Finalize: no-op (cleanup handled by worker finalize)
    """

    name = "factorio_mount"
    surface = "control_plane"  # ADR-0021

    def setup(self, ctx: ControlPlaneContext) -> list[EventData]:
        """Prepare Factorio mount topology.

        Args:
            ctx: ControlPlaneContext with host_paths and container_paths

        Returns:
            List of launch-modifying events (volume_mount, env_set) + audit events.
        """
        events: list[EventData] = []

        # Get bundle config from job_config
        bundle_config = ctx.job_config.get("bundle_config", {})
        mod_scripts_dir = bundle_config.get(
            "mod_scripts_dir",
            os.environ.get("FACTORIO_MOD_SCRIPTS_DIR", "/opt/factorio/mods/scripts")
        )
        rcon_host = bundle_config.get(
            "rcon_host",
            os.environ.get("FACTORIO_RCON_HOST", "localhost")
        )
        rcon_port = bundle_config.get(
            "rcon_port",
            os.environ.get("FACTORIO_RCON_PORT", "27015")
        )

        # Launch-modifying: volume mount for mod scripts (RW)
        events.append(EventData(type="control_plane.volume_mount", data={
            "host_path": mod_scripts_dir,
            "container_path": mod_scripts_dir,
            "rw": True,
        }))

        # Launch-modifying: env vars for RCON
        events.append(EventData(type="control_plane.env_set", data={
            "key": "FACTORIO_MOD_SCRIPTS_DIR",
            "value": mod_scripts_dir,
        }))
        events.append(EventData(type="control_plane.env_set", data={
            "key": "FACTORIO_RCON_HOST",
            "value": rcon_host,
        }))
        events.append(EventData(type="control_plane.env_set", data={
            "key": "FACTORIO_RCON_PORT",
            "value": str(rcon_port),
        }))

        # Audit event
        events.append(EventData(type="factorio.mount.prepared", data={
            "mod_scripts_dir": mod_scripts_dir,
            "rcon_host": rcon_host,
            "rcon_port": rcon_port,
        }))

        logger.info(
            f"Factorio mount prepared: scripts={mod_scripts_dir}, "
            f"rcon={rcon_host}:{rcon_port}"
        )

        return events

    def finalize(self, ctx: ControlPlaneContext) -> FinalizeResult:
        """Finalize Factorio mount (no-op).

        Cleanup is handled by the worker's factorio_runtime finalize.
        """
        return FinalizeResult(events=[], success=True)