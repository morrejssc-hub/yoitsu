#!/usr/bin/env python3
"""Submit tasks for a Yoitsu test run."""

import asyncio
import sys

import httpx

PASLOE_URL = "http://localhost:8000"
TRENNI_URL = "http://localhost:8100"
API_KEY = "yoitsu-test-key-2026"
SOURCE_ID = "test-coordinator"

TASKS = [
    # Palimpsest improvements
    {
        "task": "Review and improve palimpsest error handling in runner.py. Add better exception catching, logging, and recovery mechanisms. Focus on Stage 1-4 error handling.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Add comprehensive type hints to palimpsest/config.py and palimpsest/events.py. Ensure all dataclasses have proper type annotations.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Review palimpsest tool system. Add new file operation tools: move_file, copy_file, delete_file. Follow existing patterns in evo/tools/.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Improve palimpsest context assembly performance. Review context.py and optimize file tree building and provider loading.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Add unit tests for palimpsest resolver.py and emitter.py. Create test cases following existing patterns in tests/.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    # Pasloe improvements
    {
        "task": "Add metrics export endpoint to Pasloe. Create /metrics endpoint that returns job counts, event rates, and webhook status in JSON format.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    {
        "task": "Improve Pasloe WebUI. Add event filtering by type and source to the /ui dashboard.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    {
        "task": "Add batch event query endpoint to Pasloe. Allow querying multiple event types in a single request.",
        "role": "default",
        "repo": "/home/holo/yoitsu/pasloe",
        "branch": "master",
    },
    # Trenni improvements
    {
        "task": "Review and improve Trenni fork-join logic in supervisor.py. Add better error handling for child task failures and parent resume logic.",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    {
        "task": "Add dynamic capacity adjustment to Trenni. Implement logic to adjust max_workers based on system load (CPU/memory).",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    {
        "task": "Improve Trenni error recovery. Add retry logic for failed job launches and better cleanup on supervisor shutdown.",
        "role": "default",
        "repo": "/home/holo/yoitsu/trenni",
        "branch": "master",
    },
    # Evo improvements
    {
        "task": "Review evo repository structure. Add documentation to roles/, contexts/, tools/, and prompts/ explaining the purpose of each file.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
    {
        "task": "Create a new coding-focused role in evo/roles/. This role should be optimized for code review and refactoring tasks.",
        "role": "default",
        "repo": "/home/holo/yoitsu/palimpsest",
        "branch": "master",
    },
]


async def preflight():
    async with httpx.AsyncClient(timeout=5.0) as client:
        # Must have Pasloe
        try:
            resp = await client.get(
                f"{PASLOE_URL}/events?limit=1",
                headers={"X-API-Key": API_KEY},
            )
            resp.raise_for_status()
            print("[Preflight] Pasloe OK")
        except Exception as e:
            print(f"[Preflight] ERROR: Pasloe unreachable: {e}", file=sys.stderr)
            sys.exit(1)

        # Trenni is optional (tasks will replay on next start) but warn if down
        try:
            resp = await client.get(f"{TRENNI_URL}/status")
            d = resp.json()
            print(f"[Preflight] Trenni OK: jobs={d.get('running_jobs')}/{d.get('max_workers')}")
        except Exception as e:
            print(f"[Preflight] WARNING: Trenni unreachable ({e}). "
                  f"Tasks will be replayed when Trenni starts.", file=sys.stderr)


async def submit_task(client: httpx.AsyncClient, task_def: dict, index: int) -> None:
    # Convert legacy dict into TriggerData payload
    goal = task_def.pop("task", "")
    context = dict(task_def)
    
    payload = {
        "goal": goal,
        "context": context,
    }

    resp = await client.post(
        f"{PASLOE_URL}/events",
        json={"source_id": SOURCE_ID, "type": "trigger.external", "data": payload},
        headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
    )
    resp.raise_for_status()
    event_id = resp.json().get("id", "?")
    print(f"[Submit] {index}/{len(TASKS)} submitted event_id={event_id}: "
          f"{goal[:60]}...")


async def main():
    await preflight()

    print(f"[Submit] Submitting {len(TASKS)} tasks...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        for i, task in enumerate(TASKS, 1):
            try:
                await submit_task(client, task, i)
            except Exception as e:
                print(f"[Submit] Failed task {i}: {e}", file=sys.stderr)
            await asyncio.sleep(0.1)

    print("[Submit] Done.")


if __name__ == "__main__":
    asyncio.run(main())
