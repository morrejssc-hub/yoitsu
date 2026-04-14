"""Per-bundle cleanup capability (ADR-0021 A.7).

Per ADR-0021: BUILTIN_CAPABILITIES deleted. Each bundle must provide
its own cleanup capability. This is a copy of the palimpsest builtin
with surface="job_side" added.

Handles cleanup of workspaces and resources. Failure does not affect
job state (cleanup is non-critical for artifact persistence).
"""

from __future__ import annotations

import shutil

from loguru import logger
from yoitsu_contracts import FinalizeResult, EventData


class CleanupCapability:
    """Cleanup capability for factorio bundle.

    Per ADR-0021: surface="job_side" — runs in Palimpsest job container.
    """

    name = "cleanup"
    surface = "job_side"  # ADR-0021

    def setup(self, ctx) -> list[EventData]:
        """No setup needed."""
        return []

    def finalize(self, ctx) -> FinalizeResult:
        """Cleanup workspace and resources.

        Cleanup failure does not affect success (artifact already persisted).

        Args:
            ctx: JobContext with target_workspace and resources

        Returns:
            FinalizeResult with cleanup events and success=True.
        """
        events = []

        # Cleanup target workspace
        if ctx.target_workspace:
            try:
                shutil.rmtree(ctx.target_workspace)
                events.append(EventData(type="cleanup.completed", data={
                    "workspace": ctx.target_workspace
                }))
            except Exception as e:
                events.append(EventData(type="cleanup.failed", data={
                    "workspace": ctx.target_workspace,
                    "error": str(e)
                }))

        # Cleanup resources
        for name, resource in ctx.resources.items():
            if hasattr(resource, "close"):
                try:
                    resource.close()
                    events.append(EventData(type="resource.closed", data={
                        "name": name
                    }))
                except Exception as e:
                    events.append(EventData(type="cleanup.failed", data={
                        "resource": name,
                        "error": str(e)
                    }))

        # Cleanup always returns success=True (non-critical)
        return FinalizeResult(events=events, success=True)