"""GitHub context provider for rendering PR/Issue context.

Per Bundle MVP: This context provider renders GitHub context from
role_params into a markdown section for the task message.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palimpsest.config import JobConfig


def github_context(*, job_config: JobConfig, **_) -> str:
    """Render GitHub context from job_config.role_params.

    Expects role_params["github_context"] to contain either:
    - {"pr": {...}} for pull request context
    - {"issue": {...}} for issue context

    Args:
        job_config: JobConfig with role_params containing github_context

    Returns:
        Markdown-formatted GitHub context section.
    """
    github_data = (job_config.role_params or {}).get("github_context", {})
    if not github_data:
        return ""

    parts = ["## GitHub Context\n"]

    if "pr" in github_data:
        pr = github_data["pr"]
        parts.append("### Pull Request")
        parts.append(f"- **#{pr.get('number', '?')}**: {pr.get('title', 'Untitled')}")
        parts.append(f"- **Repository**: {pr.get('owner', '')}/{pr.get('repo', '')}")
        parts.append(f"- **Author**: {pr.get('author', 'unknown')}")
        parts.append(f"- **Branch**: {pr.get('head_branch', '?')} → {pr.get('base_branch', 'main')}")
        parts.append(f"- **State**: {pr.get('state', 'open')}")
        parts.append(f"- **URL**: {pr.get('url', '')}")

        if pr.get("body"):
            body_preview = pr["body"][:500]
            if len(pr["body"]) > 500:
                body_preview += "..."
            parts.append(f"\n**Description:**\n{body_preview}")

        if pr.get("files"):
            parts.append(f"\n**Changed files:** {', '.join(pr['files'][:10])}")

    elif "issue" in github_data:
        issue = github_data["issue"]
        parts.append("### Issue")
        parts.append(f"- **#{issue.get('number', '?')}**: {issue.get('title', 'Untitled')}")
        parts.append(f"- **Repository**: {issue.get('owner', '')}/{issue.get('repo', '')}")
        parts.append(f"- **Author**: {issue.get('author', 'unknown')}")
        parts.append(f"- **State**: {issue.get('state', 'open')}")
        parts.append(f"- **URL**: {issue.get('url', '')}")

        if issue.get("labels"):
            parts.append(f"- **Labels**: {', '.join(issue['labels'])}")

        if issue.get("body"):
            body_preview = issue["body"][:500]
            if len(issue["body"]) > 500:
                body_preview += "..."
            parts.append(f"\n**Description:**\n{body_preview}")

    return "\n".join(parts)


# Mark as context provider for discovery
github_context.__is_context__ = True
github_context.__section_type__ = "github_context"