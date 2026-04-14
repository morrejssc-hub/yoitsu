"""Per-bundle git workspace capability (ADR-0021 A.7).

Per ADR-0021: BUILTIN_CAPABILITIES deleted. Each bundle must provide
its own git_workspace capability. This is a copy of the palimpsest builtin
with surface="job_side" added.

Handles:
- Clone target repo (setup) — handled by Trenni workspace_manager
- Commit + push (finalize)
- Hallucination gate (no changes = success=True, artifact skipped)
- Returns workspace via capability.workspace_ready event (ADR-0021 A.6)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger
from yoitsu_contracts import FinalizeResult, EventData


class GitWorkspaceCapability:
    """Git workspace management capability for factorio bundle.

    Per ADR-0021: surface="job_side" — runs in Palimpsest job container.
    """

    name = "git_workspace"
    surface = "job_side"  # ADR-0021

    MAX_RETRIES = 3

    def setup(self, ctx) -> list[EventData]:
        """Setup is handled by Trenni (workspace materialization).

        Returns workspace via capability.workspace_ready event so
        runner can use it as cwd (ADR-0021 A.6).

        Args:
            ctx: JobContext with target_workspace

        Returns:
            List of EventData including workspace_ready.
        """
        workspace = ctx.target_workspace
        return [
            EventData(type="git_workspace.ready", data={
                "workspace": workspace
            }),
            EventData(type="capability.workspace_ready", data={
                "cwd": workspace,
            }),
        ]

    def finalize(self, ctx) -> FinalizeResult:
        """Commit and push changes to target repo.

        Implements ADR-0015 push strategy:
        - Hallucination gate: no changes = success=True (artifact skipped)
        - Sync push with retry
        - Artifact URI points to remote repo

        Args:
            ctx: JobContext with target_workspace and target_source

        Returns:
            FinalizeResult with events and success flag.
        """
        events = []
        success = True

        if not ctx.target_workspace:
            # Repoless task: skip
            events.append(EventData(type="publication.skipped", data={
                "reason": "no_target_workspace"
            }))
            return FinalizeResult(events=events, success=True)

        workspace = Path(ctx.target_workspace)

        # Hallucination gate
        subprocess.run(["git", "add", "-A"], cwd=workspace, check=False)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=workspace,
            capture_output=True
        )

        if result.returncode == 0:
            # No changes — publication skipped.
            logger.info("No changes detected, publication skipped")
            events.append(EventData(type="publication.skipped", data={
                "reason": "no_changes",
                "workspace": str(workspace),
            }))
            return FinalizeResult(events=events, success=True)

        # Commit - configure git identity
        subprocess.run(
            ["git", "config", "user.email", "yoitsu@example.com"],
            cwd=workspace,
            check=False,
        )
        subprocess.run(
            ["git", "config", "user.name", "Yoitsu Bot"],
            cwd=workspace,
            check=False,
        )

        sha_before = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace
        ).decode().strip()

        try:
            subprocess.run(
                ["git", "commit", "-m", f"job: {ctx.job_id}"],
                cwd=workspace,
                check=True,
                capture_output=True
            )
        except subprocess.CalledProcessError as e:
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "commit",
                "error": e.stderr.decode() if e.stderr else str(e),
                "artifact_persisted": False
            }))
            return FinalizeResult(events=events, success=False)

        sha_after = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=workspace
        ).decode().strip()

        # Push with retry
        for attempt in range(self.MAX_RETRIES):
            try:
                subprocess.run(
                    ["git", "push"],
                    cwd=workspace,
                    check=True,
                    capture_output=True
                )
                # Success: construct artifact URI
                if not ctx.target_source or not ctx.target_source.repo_uri:
                    logger.error(
                        f"Cannot construct artifact URI: target_source.repo_uri missing. "
                        f"job_id={ctx.job_id}"
                    )
                    events.append(EventData(type="finalize.failed", data={
                        "capability": self.name,
                        "stage": "artifact_uri",
                        "error": "target_source.repo_uri required",
                        "local_commit_sha": sha_after,
                        "artifact_persisted": True,
                    }))
                    return FinalizeResult(events=events, success=False)

                artifact_ref = f"git+{ctx.target_source.repo_uri}@{sha_after}"
                events.append(EventData(type="artifact.published", data={
                    "ref": artifact_ref,
                    "relation": "workspace_output",
                    "workspace": str(workspace)
                }))
                return FinalizeResult(events=events, success=True)
            except subprocess.CalledProcessError as e:
                if attempt < self.MAX_RETRIES - 1:
                    logger.warning(f"Push failed (attempt {attempt + 1}), retrying...")
                    continue
                events.append(EventData(type="finalize.failed", data={
                    "capability": self.name,
                    "stage": "push",
                    "error": e.stderr.decode() if e.stderr else str(e),
                    "local_commit_sha": sha_after,
                    "artifact_persisted": False,
                    "retry_possible": True
                }))
                success = False

        return FinalizeResult(events=events, success=success)