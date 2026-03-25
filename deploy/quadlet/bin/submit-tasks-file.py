#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
import yaml


def _load_tasks(path: Path) -> list[dict]:
    doc = yaml.safe_load(path.read_text())
    tasks = doc.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError(f"'tasks' must be a list, got {type(tasks).__name__}")
    return tasks


def _normalize_task(task: dict) -> dict:
    raw = dict(task)
    goal = raw.pop("goal", raw.pop("task", ""))
    context = raw.pop("context", raw)
    if not isinstance(context, dict):
        context = {"value": context}

    if not context.get("repo") and context.get("repo_url"):
        context["repo"] = context.pop("repo_url")
    if not context.get("init_branch") and context.get("branch"):
        context["init_branch"] = context.pop("branch")

    return {
        "goal": goal,
        "context": context,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit Yoitsu task YAML inside the Quadlet pod.")
    parser.add_argument("tasks_file", type=Path)
    args = parser.parse_args()

    api_key = os.environ.get("PASLOE_API_KEY", "")
    if not api_key:
        print("PASLOE_API_KEY is required", file=sys.stderr)
        return 1

    pasloe_url = os.environ.get("YOITSU_PASLOE_URL", "http://127.0.0.1:8000").rstrip("/")
    source_id = os.environ.get("YOITSU_SUBMIT_SOURCE", "yoitsu-quadlet-submit")
    stamp_dir = Path(os.environ.get("YOITSU_SUBMIT_STAMP_DIR", "/var/lib/yoitsu/submission-stamps"))
    stamp_file = stamp_dir / f"{args.tasks_file.name}.done"

    if stamp_file.exists():
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": True,
                    "reason": "already_submitted",
                    "stamp_file": str(stamp_file),
                },
                ensure_ascii=True,
            ),
            flush=True,
        )
        return 0

    try:
        tasks = _load_tasks(args.tasks_file)
    except Exception as exc:
        print(f"Failed to load tasks file: {exc}", file=sys.stderr)
        return 1

    submitted = 0
    failed = 0

    with httpx.Client(timeout=15.0) as client:
        for index, task in enumerate(tasks, 1):
            payload = _normalize_task(task)
            event_source_id = f"{source_id}-{index:02d}"
            try:
                resp = client.post(
                    f"{pasloe_url}/events",
                    json={
                        "source_id": event_source_id,
                        "type": "trigger.external",
                        "data": payload,
                    },
                    headers={
                        "X-API-Key": api_key,
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
            except Exception as exc:
                failed += 1
                print(
                    json.dumps(
                        {
                            "index": index,
                            "ok": False,
                            "goal": payload["goal"],
                            "error": str(exc),
                        },
                        ensure_ascii=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                continue

            submitted += 1
            body = resp.json()
            print(
                json.dumps(
                    {
                        "index": index,
                        "ok": True,
                        "event_id": body.get("id"),
                        "goal": payload["goal"],
                    },
                    ensure_ascii=True,
                ),
                flush=True,
            )

    if failed == 0:
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file.write_text(json.dumps({"submitted": submitted, "failed": failed}, ensure_ascii=True) + "\n")
    print(json.dumps({"submitted": submitted, "failed": failed}, ensure_ascii=True), flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
