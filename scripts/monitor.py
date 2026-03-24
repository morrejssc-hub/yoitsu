#!/usr/bin/env python3
"""Monitor script for Yoitsu test runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PASLOE_URL = os.environ.get("YOITSU_PASLOE_URL", "http://localhost:8000")
DEFAULT_TRENNI_URL = os.environ.get("YOITSU_TRENNI_URL", "http://localhost:8100")
DEFAULT_API_KEY = os.environ.get("PASLOE_API_KEY", "yoitsu-test-key-2026")
DEFAULT_STATE_FILE = _ROOT / "monitor-state.json"
DEFAULT_REPORT_DIR = _ROOT

IGNORED_EVENT_TYPES = {
    "agent.llm.request",
    "agent.llm.response",
    "agent.tool.exec",
    "agent.tool.result",
    "job.stage.transition",
}


@dataclass
class JobRecord:
    status: str = "unknown"
    source_event_id: str = ""
    runtime_kind: str = ""
    container_id: str = ""
    container_name: str = ""
    evo_sha: str = ""
    summary: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


@dataclass
class PodmanSummary:
    available: bool
    running: int = 0
    exited: int = 0
    total: int = 0
    names: list[str] = field(default_factory=list)
    warning: str = ""


class Monitor:
    def __init__(
        self,
        *,
        duration_hours: float = 5.0,
        pasloe_url: str = DEFAULT_PASLOE_URL,
        trenni_url: str = DEFAULT_TRENNI_URL,
        api_key: str = DEFAULT_API_KEY,
        state_file: Path = DEFAULT_STATE_FILE,
        report_dir: Path = DEFAULT_REPORT_DIR,
    ) -> None:
        self.start_time = datetime.now()
        self.end_time: datetime | None = None
        self.duration_hours = duration_hours
        self.pasloe_url = pasloe_url.rstrip("/")
        self.trenni_url = trenni_url.rstrip("/")
        self.api_key = api_key
        self.state_file = state_file
        self.report_file = report_dir / f"test-report-{self.start_time.strftime('%Y-%m-%d')}.md"

        self.event_cursor: str | None = None
        self.jobs: dict[str, JobRecord] = {}
        self.tasks_submitted: int = 0
        self.errors: list[str] = []
        self.podman_summary = PodmanSummary(available=False)
        self.last_trenni_status: dict[str, Any] | None = None

        self._load_state()

    async def run(self) -> None:
        self.end_time = self.start_time + timedelta(hours=self.duration_hours)
        print(f"[Monitor] Started at {self.start_time.isoformat()}")
        print(f"[Monitor] Will run until {self.end_time.isoformat()}")
        print(f"[Monitor] Pasloe: {self.pasloe_url}")
        print(f"[Monitor] Trenni: {self.trenni_url}")

        while datetime.now() < self.end_time:
            try:
                await self._poll_events()
                await self._check_health()
                self._print_status()
                self._save_state()
            except Exception as exc:
                msg = f"[{datetime.now().isoformat()}] Error: {exc}"
                print(msg, file=sys.stderr)
                self.errors.append(msg)

            await asyncio.sleep(30)

        self._write_report()
        print(f"[Monitor] Done. Report: {self.report_file}")

    async def _poll_events(self) -> None:
        params: dict[str, str] = {"limit": "100", "order": "asc"}
        if self.event_cursor:
            params["cursor"] = self.event_cursor

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.pasloe_url}/events",
                params=params,
                headers={"X-API-Key": self.api_key},
                timeout=15.0,
            )
            resp.raise_for_status()
            events = resp.json()
            next_cursor = resp.headers.get("X-Next-Cursor")

        if not events:
            return

        for event in events:
            self._process_event(event)

        if next_cursor:
            self.event_cursor = next_cursor
        else:
            last = events[-1]
            ts = last.get("ts")
            event_id = last.get("id")
            if ts and event_id:
                self.event_cursor = f"{ts}|{event_id}"

    def _process_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type", "")
        data = event.get("data", {})
        job_id = data.get("job_id", "")
        timestamp = event.get("ts", "")

        if event_type in ("trigger.external", "task.created"):
            self.tasks_submitted += 1
            if event_type not in IGNORED_EVENT_TYPES:
                print(f"  [{event_type}] {data.get('goal', '')[:100]}")
            return

        if not job_id:
            if event_type not in IGNORED_EVENT_TYPES:
                print(f"  [{event_type}] {data}")
            return

        record = self.jobs.setdefault(job_id, JobRecord())

        if event_type == "supervisor.job.launched":
            record.status = "launched"
            record.source_event_id = data.get("source_event_id", record.source_event_id)
            record.runtime_kind = data.get("runtime_kind", record.runtime_kind)
            record.container_id = data.get("container_id", record.container_id)
            record.container_name = data.get("container_name", record.container_name)
        elif event_type == "job.started":
            record.status = "started"
            record.started_at = timestamp or record.started_at
            record.evo_sha = data.get("evo_sha", record.evo_sha)
        elif event_type == "job.completed":
            record.status = "completed"
            record.summary = data.get("summary", "")
            record.finished_at = timestamp or record.finished_at
        elif event_type == "job.failed":
            record.status = "failed"
            record.error = data.get("error", "")
            record.summary = data.get("summary", record.summary)
            record.finished_at = timestamp or record.finished_at

        if event_type in IGNORED_EVENT_TYPES:
            return

        if event_type == "supervisor.job.launched":
            container_short = record.container_id[:12] if record.container_id else "?"
            print(
                f"  [supervisor.job.launched] {job_id} "
                f"runtime={record.runtime_kind or '?'} container={container_short}"
            )
        elif event_type == "job.completed":
            print(f"  [job.completed] {job_id} summary={record.summary[:100]}")
        elif event_type == "job.failed":
            print(f"  [job.failed] {job_id} error={record.error[:100]}")
        else:
            print(f"  [{event_type}] {job_id}")

    async def _check_health(self) -> None:
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.get(
                    f"{self.pasloe_url}/events/stats",
                    headers={"X-API-Key": self.api_key},
                )
            except Exception as exc:
                print(f"[Monitor] WARNING: Pasloe unreachable: {exc}", file=sys.stderr)

            try:
                resp = await client.get(f"{self.trenni_url}/control/status")
                resp.raise_for_status()
                self.last_trenni_status = resp.json()
                print(
                    "[Monitor] Trenni: "
                    f"jobs={self.last_trenni_status.get('running_jobs')}/"
                    f"{self.last_trenni_status.get('max_workers')} "
                    f"pending={self.last_trenni_status.get('pending_jobs')} "
                    f"ready={self.last_trenni_status.get('ready_queue_size')} "
                    f"paused={self.last_trenni_status.get('paused')} "
                    f"runtime={self.last_trenni_status.get('runtime_kind', '?')}"
                )
            except Exception as exc:
                self.last_trenni_status = None
                print(f"[Monitor] WARNING: Trenni unreachable: {exc}", file=sys.stderr)

        self.podman_summary = self._inspect_podman()
        if self.podman_summary.available:
            print(
                "[Monitor] Podman jobs: "
                f"running={self.podman_summary.running} "
                f"exited={self.podman_summary.exited} "
                f"total={self.podman_summary.total}"
            )
        elif self.podman_summary.warning:
            print(f"[Monitor] WARNING: {self.podman_summary.warning}", file=sys.stderr)

    def _print_status(self) -> None:
        completed = sum(1 for rec in self.jobs.values() if rec.status == "completed")
        failed = sum(1 for rec in self.jobs.values() if rec.status == "failed")
        in_progress = sum(1 for rec in self.jobs.values() if rec.status in {"launched", "started"})
        elapsed = (datetime.now() - self.start_time).total_seconds()
        remaining = (self.end_time - datetime.now()).total_seconds() if self.end_time else 0.0
        success_rate = (
            f"{completed / (completed + failed) * 100:.0f}%"
            if (completed + failed) > 0
            else "n/a"
        )

        print(
            f"[Monitor] {elapsed / 60:.0f}min elapsed | {remaining / 60:.0f}min left | "
            f"submitted={self.tasks_submitted} total={len(self.jobs)} "
            f"in_progress={in_progress} completed={completed} failed={failed} "
            f"rate={success_rate}"
        )

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return

        try:
            state = json.loads(self.state_file.read_text())
            saved_start = state.get("start_time")
            if saved_start:
                age = datetime.now() - datetime.fromisoformat(saved_start)
                if age >= timedelta(hours=24):
                    return
            self.event_cursor = state.get("event_cursor")
            self.tasks_submitted = int(state.get("tasks_submitted", 0))
            raw_jobs = state.get("jobs", {})
            if isinstance(raw_jobs, dict):
                for job_id, payload in raw_jobs.items():
                    if isinstance(payload, dict):
                        self.jobs[job_id] = JobRecord(**{
                            "status": payload.get("status", "unknown"),
                            "source_event_id": payload.get("source_event_id", ""),
                            "runtime_kind": payload.get("runtime_kind", ""),
                            "container_id": payload.get("container_id", ""),
                            "container_name": payload.get("container_name", ""),
                            "evo_sha": payload.get("evo_sha", ""),
                            "summary": payload.get("summary", ""),
                            "error": payload.get("error", ""),
                            "started_at": payload.get("started_at", ""),
                            "finished_at": payload.get("finished_at", ""),
                        })
            self.errors = list(state.get("errors", []))
        except Exception:
            pass

    def _save_state(self) -> None:
        jobs_payload = {
            job_id: {
                "status": rec.status,
                "source_event_id": rec.source_event_id,
                "runtime_kind": rec.runtime_kind,
                "container_id": rec.container_id,
                "container_name": rec.container_name,
                "evo_sha": rec.evo_sha,
                "summary": rec.summary,
                "error": rec.error,
                "started_at": rec.started_at,
                "finished_at": rec.finished_at,
            }
            for job_id, rec in self.jobs.items()
        }
        self.state_file.write_text(json.dumps({
            "start_time": self.start_time.isoformat(),
            "event_cursor": self.event_cursor,
            "tasks_submitted": self.tasks_submitted,
            "jobs": jobs_payload,
            "errors": self.errors[-20:],
        }, indent=2))

    def _write_report(self) -> None:
        completed = [job_id for job_id, rec in self.jobs.items() if rec.status == "completed"]
        failed = [(job_id, rec) for job_id, rec in self.jobs.items() if rec.status == "failed"]
        in_progress = [(job_id, rec) for job_id, rec in self.jobs.items() if rec.status in {"launched", "started"}]
        duration = (datetime.now() - self.start_time).total_seconds()
        success_rate = (
            f"{len(completed) / (len(completed) + len(failed)) * 100:.1f}%"
            if (len(completed) + len(failed)) > 0
            else "n/a"
        )

        lines = [
            "# Yoitsu 测试报告",
            "",
            "## 概览",
            f"- **开始**: {self.start_time.isoformat()}",
            f"- **结束**: {datetime.now().isoformat()}",
            f"- **时长**: {duration / 60:.1f} 分钟",
            f"- **Pasloe**: `{self.pasloe_url}`",
            f"- **Trenni**: `{self.trenni_url}`",
            "",
            "## 统计",
            f"- 任务提交: {self.tasks_submitted}",
            f"- Jobs 总数: {len(self.jobs)}",
            f"- 完成: {len(completed)}",
            f"- 失败: {len(failed)}",
            f"- 进行中: {len(in_progress)}",
            f"- 成功率: {success_rate}",
        ]

        if self.last_trenni_status:
            lines.extend([
                "",
                "## Trenni 状态",
                f"- 运行中 jobs: {self.last_trenni_status.get('running_jobs')}",
                f"- 最大并发: {self.last_trenni_status.get('max_workers')}",
                f"- 队列等待: {self.last_trenni_status.get('pending_jobs')}",
                f"- ready queue: {self.last_trenni_status.get('ready_queue_size')}",
                f"- paused: {self.last_trenni_status.get('paused')}",
                f"- runtime: {self.last_trenni_status.get('runtime_kind', '?')}",
            ])

        if self.podman_summary.available:
            lines.extend([
                "",
                "## Podman 运行时",
                f"- 容器总数: {self.podman_summary.total}",
                f"- 运行中: {self.podman_summary.running}",
                f"- 已退出: {self.podman_summary.exited}",
            ])

        lines.extend([
            "",
            "## 失败 Jobs",
        ])
        if failed:
            for job_id, rec in failed:
                lines.append(
                    f"- `{job_id}` container=`{rec.container_name or rec.container_id or '?'}` "
                    f"error={rec.error or '(none)'}"
                )
        else:
            lines.append("- 无")

        lines.extend([
            "",
            "## 进行中 Jobs",
        ])
        if in_progress:
            for job_id, rec in in_progress:
                lines.append(
                    f"- `{job_id}` status={rec.status} "
                    f"container=`{rec.container_name or rec.container_id or '?'}` "
                    f"runtime={rec.runtime_kind or '?'}"
                )
        else:
            lines.append("- 无")

        lines.extend([
            "",
            "## 错误",
        ])
        if self.errors:
            lines.extend(f"- {item}" for item in self.errors[-20:])
        else:
            lines.append("- 无")

        self.report_file.write_text("\n".join(lines))

    def _inspect_podman(self) -> PodmanSummary:
        if shutil.which("podman") is None:
            return PodmanSummary(available=False, warning="podman not found on PATH")

        try:
            proc = subprocess.run(
                [
                    "podman",
                    "ps",
                    "-a",
                    "--filter",
                    "label=io.yoitsu.managed-by=trenni",
                    "--format",
                    "json",
                ],
                capture_output=True,
                check=True,
                text=True,
            )
        except Exception as exc:
            return PodmanSummary(available=False, warning=f"podman ps failed: {exc}")

        return _podman_summary_from_json(proc.stdout)


def _podman_summary_from_json(raw: str) -> PodmanSummary:
    try:
        rows = json.loads(raw or "[]")
    except Exception as exc:
        return PodmanSummary(available=False, warning=f"invalid podman json: {exc}")

    running = 0
    exited = 0
    names: list[str] = []
    for row in rows:
        status = str(row.get("State") or row.get("Status") or "").lower()
        names.append(str(row.get("Names") or row.get("Names", "")))
        if "running" in status or status == "up":
            running += 1
        elif status:
            exited += 1

    return PodmanSummary(
        available=True,
        running=running,
        exited=exited,
        total=len(rows),
        names=names,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=5.0)
    parser.add_argument("--pasloe-url", default=DEFAULT_PASLOE_URL)
    parser.add_argument("--trenni-url", default=DEFAULT_TRENNI_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()

    asyncio.run(
        Monitor(
            duration_hours=args.hours,
            pasloe_url=args.pasloe_url,
            trenni_url=args.trenni_url,
            api_key=args.api_key,
            state_file=args.state_file,
            report_dir=args.report_dir,
        ).run()
    )


if __name__ == "__main__":
    main()
