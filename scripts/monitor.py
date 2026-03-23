#!/usr/bin/env python3
"""Monitor script for Yoitsu test runs."""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

PASLOE_URL = "http://localhost:8000"
TRENNI_URL = "http://localhost:8100"
API_KEY = "yoitsu-test-key-2026"

_ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = _ROOT / "monitor-state.json"

IGNORED_EVENT_TYPES = {
    "agent.llm.request",
    "agent.llm.response",
    "agent.tool.exec",
    "agent.tool.result",
    "job.stage.transition",
}


class Monitor:
    def __init__(self, duration_hours: float = 5.0):
        self.start_time = datetime.now()
        self.report_file = _ROOT / f"test-report-{self.start_time.strftime('%Y-%m-%d')}.md"
        self.end_time = None  # set in run()
        self.duration_hours = duration_hours

        # Load persisted cursor (discard if state file is older than 24 hours)
        self.event_cursor: str | None = None
        if STATE_FILE.exists():
            try:
                state = json.loads(STATE_FILE.read_text())
                saved_start = state.get("start_time")
                if saved_start:
                    from datetime import timedelta
                    age = datetime.now() - datetime.fromisoformat(saved_start)
                    if age < timedelta(hours=24):
                        self.event_cursor = state.get("event_cursor")
            except Exception:
                pass

        # Job state tracking: job_id -> "launched"|"started"|"completed"|"failed"
        self.jobs: dict[str, str] = {}
        self.tasks_submitted: int = 0
        self.errors: list[str] = []

    async def run(self):
        from datetime import timedelta
        self.end_time = self.start_time + timedelta(hours=self.duration_hours)
        print(f"[Monitor] Started at {self.start_time.isoformat()}")
        print(f"[Monitor] Will run until {self.end_time.isoformat()}")

        while datetime.now() < self.end_time:
            try:
                await self._poll_events()
                await self._check_health()
                self._print_status()
                self._save_state()
            except Exception as e:
                msg = f"[{datetime.now().isoformat()}] Error: {e}"
                print(msg, file=sys.stderr)
                self.errors.append(msg)

            await asyncio.sleep(30)

        self._write_report()
        print(f"[Monitor] Done. Report: {self.report_file}")

    async def _poll_events(self):
        params: dict = {"limit": "100", "order": "asc"}
        if self.event_cursor:
            params["cursor"] = self.event_cursor

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{PASLOE_URL}/events",
                params=params,
                headers={"X-API-Key": API_KEY},
                timeout=15.0,
            )
            resp.raise_for_status()
            events = resp.json()  # bare list[Event]
            next_cursor = resp.headers.get("X-Next-Cursor")

        if not events:
            return

        for event in events:
            self._process_event(event)

        # Advance cursor
        if next_cursor:
            self.event_cursor = next_cursor
        else:
            last = events[-1]
            ts = last.get("ts")
            eid = last.get("id")
            if ts and eid:
                self.event_cursor = f"{ts}|{eid}"

    def _process_event(self, event: dict):
        etype = event.get("type", "")
        data = event.get("data", {})
        job_id = data.get("job_id", "")

        if etype == "task.submit":
            self.tasks_submitted += 1
        elif etype == "supervisor.job.launched" and job_id:
            self.jobs[job_id] = "launched"
        elif etype == "job.started" and job_id:
            self.jobs[job_id] = "started"
        elif etype == "job.completed" and job_id:
            self.jobs[job_id] = "completed"
        elif etype == "job.failed" and job_id:
            self.jobs[job_id] = "failed"

        if etype not in IGNORED_EVENT_TYPES:
            print(f"  [{etype}] {job_id or data}")

    async def _check_health(self):
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Pasloe health
            try:
                await client.get(f"{PASLOE_URL}/events/stats",
                                 headers={"X-API-Key": API_KEY})
            except Exception as e:
                print(f"[Monitor] WARNING: Pasloe unreachable: {e}", file=sys.stderr)

            # Trenni health
            try:
                resp = await client.get(f"{TRENNI_URL}/control/status")
                resp.raise_for_status()
                d = resp.json()
                print(
                    f"[Monitor] Trenni: jobs={d.get('running_jobs')}/{d.get('max_workers')} "
                    f"pending={d.get('pending_jobs')} ready={d.get('ready_queue_size')} "
                    f"paused={d.get('paused')}"
                )
            except Exception as e:
                print(f"[Monitor] WARNING: Trenni unreachable: {e}", file=sys.stderr)

    def _print_status(self):
        completed = sum(1 for s in self.jobs.values() if s == "completed")
        failed = sum(1 for s in self.jobs.values() if s == "failed")
        in_progress = sum(1 for s in self.jobs.values() if s in ("launched", "started"))
        elapsed = (datetime.now() - self.start_time).total_seconds()
        remaining = (self.end_time - datetime.now()).total_seconds()
        rate = f"{completed/(completed+failed)*100:.0f}%" if (completed + failed) > 0 else "n/a"

        print(
            f"[Monitor] {elapsed/60:.0f}min elapsed | {remaining/60:.0f}min left | "
            f"submitted={self.tasks_submitted} total={len(self.jobs)} "
            f"in_progress={in_progress} completed={completed} failed={failed} rate={rate}"
        )

    def _save_state(self):
        STATE_FILE.write_text(json.dumps({
            "start_time": self.start_time.isoformat(),
            "event_cursor": self.event_cursor,
            "tasks_submitted": self.tasks_submitted,
            "jobs": self.jobs,
        }, indent=2))

    def _write_report(self):
        completed = sum(1 for s in self.jobs.values() if s == "completed")
        failed = sum(1 for s in self.jobs.values() if s == "failed")
        duration = (datetime.now() - self.start_time).total_seconds()
        rate = f"{completed/(completed+failed)*100:.1f}%" if (completed + failed) > 0 else "n/a"

        lines = [
            f"# Yoitsu 测试报告",
            f"",
            f"## 概览",
            f"- **开始**: {self.start_time.isoformat()}",
            f"- **结束**: {datetime.now().isoformat()}",
            f"- **时长**: {duration/60:.1f} 分钟",
            f"",
            f"## 统计",
            f"- 任务提交: {self.tasks_submitted}",
            f"- Jobs 总数: {len(self.jobs)}",
            f"- 完成: {completed}",
            f"- 失败: {failed}",
            f"- 成功率: {rate}",
            f"",
            f"## 错误",
        ]
        if self.errors:
            lines += [f"- {e}" for e in self.errors]
        else:
            lines.append("无")

        self.report_file.write_text("\n".join(lines))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=5.0)
    args = parser.parse_args()
    asyncio.run(Monitor(duration_hours=args.hours).run())
