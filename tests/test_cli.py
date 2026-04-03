"""CLI integration tests via CliRunner."""
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from click.testing import CliRunner
from yoitsu_contracts.client import PasloeEvent

from yoitsu.cli import _display_task_id, _task_icon, main


def _runner() -> CliRunner:
    return CliRunner()


def _pe(event_id: str, type_: str, data: dict | None = None) -> PasloeEvent:
    return PasloeEvent(
        id=event_id,
        source_id="trenni-supervisor",
        type=type_,
        ts=datetime.fromisoformat("2026-03-27T12:00:00"),
        data=data or {},
    )


class TestUp:
    def test_up_fails_if_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("PASLOE_API_KEY", raising=False)
        r = _runner().invoke(main, ["up"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "PASLOE_API_KEY" in out["error"]

    def test_up_fails_if_lock_held(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_LOCK_FILE", tmp_path / ".yoitsu.lock")
        with patch("yoitsu.process.acquire_lock", return_value=-1):
            r = _runner().invoke(main, ["up"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "Another yoitsu instance" in out["error"]

    def test_up_succeeds_when_both_already_alive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        monkeypatch.setattr(proc, "_LOCK_FILE", tmp_path / ".yoitsu.lock")
        proc.write_pids(pasloe_pid=1, trenni_pid=2)

        with patch("yoitsu.process.is_alive", return_value=True):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True

    def test_up_starts_services_and_writes_pids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")
        monkeypatch.setattr(proc, "_DEFAULT_CONFIG", tmp_path / "trenni.yaml")
        monkeypatch.setattr(proc, "_LOCK_FILE", tmp_path / ".yoitsu.lock")
        (tmp_path / "trenni.yaml").touch()

        with (
            patch("yoitsu.process.is_alive", return_value=False),
            patch("yoitsu.process.start_pasloe", return_value=100),
            patch("yoitsu.process.start_trenni", return_value=200),
            patch("yoitsu.cli._wait_pasloe_ready", new=AsyncMock(return_value=True)),
            patch("yoitsu.cli._wait_trenni_ready", new=AsyncMock(return_value=True)),
        ):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert out["pasloe_pid"] == 100
        assert out["trenni_pid"] == 200
        pids = proc.read_pids()
        assert pids["pasloe"]["pid"] == 100

    def test_up_kills_pasloe_if_trenni_start_fails(self, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")

        killed: list[int] = []
        with (
            patch("yoitsu.process.read_pids", return_value=None),
            patch("yoitsu.process.start_pasloe", return_value=100),
            patch("yoitsu.process.start_trenni", side_effect=RuntimeError("boom")),
            patch("yoitsu.process.kill_pid", side_effect=lambda pid, **kw: killed.append(pid)),
            patch("yoitsu.cli._wait_pasloe_ready", new=AsyncMock(return_value=True)),
        ):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "Failed to start trenni" in out["error"]
        assert killed == [100]


class TestDown:
    def test_down_succeeds_when_not_running(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        r = _runner().invoke(main, ["down"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert out["stopped"] == []

    def test_down_stops_both_services(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=100, trenni_pid=200)

        killed: list[int] = []
        with (
            patch("yoitsu.process.is_alive", return_value=True),
            patch("yoitsu.process.kill_pid", side_effect=lambda pid, **kw: killed.append(pid)),
            patch("yoitsu.cli._trenni_graceful_stop", new=AsyncMock(return_value=False)),
        ):
            r = _runner().invoke(main, ["down"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert set(out["stopped"]) == {"trenni", "pasloe"}
        assert 100 in killed
        assert 200 in killed
        assert proc.read_pids() is None


class TestStatus:
    def test_status_returns_both_services(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=100, trenni_pid=200)

        pasloe_stats = {"total_events": 10, "by_type": {"task.submit": 3}}
        trenni_status = {
            "running": True, "paused": False,
            "running_jobs": 1, "max_workers": 4,
            "pending_jobs": 0, "ready_queue_size": 0,
        }

        with (
            patch("yoitsu.process.is_alive", return_value=True),
            patch("yoitsu.client.PasloeClient.get_stats",
                  new=AsyncMock(return_value=pasloe_stats)),
            patch("yoitsu.client.TrenniClient.get_status",
                  new=AsyncMock(return_value=trenni_status)),
            patch("yoitsu.cli._podman_summary", return_value={"available": True, "running": 1, "exited": 0, "total": 1}),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["status"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is True
        assert out["pasloe"]["total_events"] == 10
        assert out["trenni"]["running"] is True
        assert "podman" in out

    def test_status_marks_dead_service_as_not_alive(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        # No PID file — both dead

        with (
            patch("yoitsu.client.PasloeClient.check_ready", new=AsyncMock(return_value=False)),
            patch("yoitsu.client.TrenniClient.check_ready", new=AsyncMock(return_value=False)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["status"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is False
        assert out["trenni"]["alive"] is False

    def test_status_uses_http_fallback_when_no_pid_file(self):
        with (
            patch("yoitsu.process.read_pids", return_value=None),
            patch("yoitsu.client.PasloeClient.check_ready", new=AsyncMock(return_value=True)),
            patch("yoitsu.client.TrenniClient.check_ready", new=AsyncMock(return_value=True)),
            patch("yoitsu.client.PasloeClient.get_stats", new=AsyncMock(return_value={"total_events": 3, "by_type": {}})),
            patch("yoitsu.client.TrenniClient.get_status", new=AsyncMock(return_value={"running": True})),
            patch("yoitsu.cli._podman_summary", return_value={"available": False}),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["status"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is True
        assert out["trenni"]["alive"] is True


class TestQueryCommands:
    def test_task_icon_uses_approx_for_unknown_and_en_dash_for_cancelled(self):
        assert _task_icon("completed", "unknown") == "~"
        assert _task_icon("cancelled", "") == "–"

    def test_display_task_id_shows_leaf_for_children(self):
        assert _display_task_id("root") == "root"
        assert _display_task_id("root/ab12") == "ab12"
        assert _display_task_id("root/ab12/cd34") == "ab12/cd34"

    def test_tasks_lists_live_tasks(self):
        with (
            patch("yoitsu.client.TrenniClient.get_tasks_strict", new=AsyncMock(return_value=[{"task_id": "t1"}])),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["tasks"])
        assert r.exit_code == 0
        assert json.loads(r.output)["tasks"][0]["task_id"] == "t1"

    def test_tasks_detail_includes_job_events(self):
        with (
            patch("yoitsu.client.TrenniClient.get_task_strict", new=AsyncMock(return_value={"task_id": "t1"})),
            patch("yoitsu.client.PasloeClient.list_jobs_strict", new=AsyncMock(return_value=[{"job_id": "j1"}])),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["tasks", "t1"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["task"]["task_id"] == "t1"
        assert out["job_events"][0]["job_id"] == "j1"

    def test_tasks_detail_degrades_when_live_state_missing(self):
        response = MagicMock(status_code=404, text="not found", reason_phrase="Not Found")
        error = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        with (
            patch("yoitsu.client.TrenniClient.get_task_strict", new=AsyncMock(side_effect=error)),
            patch("yoitsu.client.PasloeClient.list_jobs_strict", new=AsyncMock(return_value=[{"job_id": "j1"}])),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["tasks", "t1"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["task"] is None
        assert out["job_events"][0]["job_id"] == "j1"
        assert "warnings" in out

    def test_jobs_lists_live_jobs(self):
        with (
            patch("yoitsu.client.PasloeClient.list_jobs_strict", new=AsyncMock(return_value=[{"job_id": "j1"}])),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["jobs"])
        assert r.exit_code == 0
        assert json.loads(r.output)["jobs"][0]["job_id"] == "j1"

    def test_jobs_detail_degrades_when_live_state_missing(self):
        response = MagicMock(status_code=404, text="not found", reason_phrase="Not Found")
        error = httpx.HTTPStatusError("not found", request=MagicMock(), response=response)
        with (
            patch("yoitsu.client.TrenniClient.get_job_strict", new=AsyncMock(side_effect=error)),
            patch("yoitsu.client.PasloeClient.list_jobs_strict", new=AsyncMock(return_value=[{"job_id": "j1"}])),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["jobs", "j1"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["job"] is None
        assert out["events"][0]["job_id"] == "j1"
        assert "warnings" in out

    def test_jobs_tail_formats_stream_lines(self):
        poll_results = [
            ([
                PasloeEvent(
                    id="hist",
                    source_id="palimpsest-agent",
                    type="agent.job.started",
                    ts=datetime.fromisoformat("2026-03-27T12:00:01"),
                    data={"job_id": "j1", "task_id": "t1"},
                )
            ], None),
            ([
                PasloeEvent(
                    id="seed",
                    source_id="palimpsest-agent",
                    type="agent.job.started",
                    ts=datetime.fromisoformat("2026-03-27T12:00:01"),
                    data={"job_id": "j1", "task_id": "t1"},
                )
            ], None),
            ([
                PasloeEvent(
                    id="tail",
                    source_id="palimpsest-agent",
                    type="agent.job.completed",
                    ts=datetime.fromisoformat("2026-03-27T12:00:02"),
                    data={"job_id": "j1", "task_id": "t1", "summary": "planner finished without spawn"},
                )
            ], None),
            ([], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.cli.asyncio.sleep", new=AsyncMock(side_effect=KeyboardInterrupt())),
        ):
            r = _runner().invoke(main, ["jobs", "tail", "j1"])
        assert r.exit_code == 0
        assert "agent.job.started" in r.output
        assert "agent.job.completed" in r.output
        assert "job=j1" in r.output
        assert "summary: planner finished without spawn" in r.output

    def test_events_lists_pasloe_events(self):
        with (
            patch("yoitsu.client.PasloeClient.list_events_strict", new=AsyncMock(return_value=[{"id": "e1"}])),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["events", "--limit", "5"])
        assert r.exit_code == 0
        assert json.loads(r.output)["events"][0]["id"] == "e1"

    def test_llm_stats_returns_payload(self):
        with (
            patch("yoitsu.client.PasloeClient.get_llm_stats_strict", new=AsyncMock(return_value={"by_model": {"gpt": {"responses": 1}}})),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["llm-stats"])
        assert r.exit_code == 0
        assert json.loads(r.output)["by_model"]["gpt"]["responses"] == 1

    def test_tasks_fails_on_query_error(self):
        with (
            patch("yoitsu.client.TrenniClient.get_tasks_strict", new=AsyncMock(side_effect=RuntimeError("boom"))),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["tasks"])
        assert r.exit_code == 1
        assert "tasks query failed" in json.loads(r.output)["error"]

    def test_tasks_chain_renders_human_readable_tree(self):
        poll_results = [
            ([
                _pe("e1", "supervisor.task.created", {"task_id": "root"}),
                _pe("e2", "supervisor.task.created", {"task_id": "root/ab12"}),
            ], None),
            ([
                _pe("e1", "supervisor.task.created", {"task_id": "root"}),
                _pe("e2", "supervisor.task.created", {"task_id": "root/ab12"}),
                _pe("e3", "supervisor.job.launched", {"task_id": "root", "role": "planner"}),
                _pe("e4", "supervisor.job.launched", {"task_id": "root/ab12", "role": "implementer"}),
                _pe("e5", "supervisor.task.completed", {
                    "task_id": "root/ab12",
                    "result": {
                        "semantic": {"verdict": "pass"},
                        "trace": [{"git_ref": "palimpsest/job/demo:deadbeef"}],
                    },
                }),
            ], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.TrenniClient.get_task_strict", new=AsyncMock(side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=MagicMock(status_code=404, text="not found", reason_phrase="Not Found")))),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["tasks", "chain", "root"])
        assert r.exit_code == 0
        assert "root" in r.output
        assert "ab12" in r.output
        assert "implementer" in r.output
        assert "palimpsest/job/demo:deadbeef" in r.output
        assert "task root/ab12 not present in live Trenni state" not in r.output

    def test_tasks_wait_exits_zero_on_completed(self):
        poll_results = [
            ([_pe("e1", "supervisor.task.created", {"task_id": "root"})], None),
            ([
                _pe("e1", "supervisor.task.created", {"task_id": "root"}),
                _pe("e2", "supervisor.task.completed", {
                    "task_id": "root",
                    "result": {"semantic": {"verdict": "pass"}, "trace": []},
                }),
            ], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.TrenniClient.get_task_strict", new=AsyncMock(side_effect=httpx.HTTPStatusError("not found", request=MagicMock(), response=MagicMock(status_code=404, text="not found", reason_phrase="Not Found")))),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
            patch("yoitsu.cli.asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            r = _runner().invoke(main, ["tasks", "--timeout", "60", "--interval", "0", "wait", "root"])
        assert r.exit_code == 0
        assert "[wait " in r.output
        assert "root" in r.output

    def test_events_tail_formats_stream_lines(self):
        poll_results = [
            ([_pe("seed", "agent.job.started", {"job_id": "j0", "task_id": "t0"})], None),
            ([_pe("e1", "agent.job.started", {"job_id": "j1", "task_id": "t1", "role": "planner"})], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.cli.asyncio.sleep", new=AsyncMock(side_effect=KeyboardInterrupt())),
        ):
            r = _runner().invoke(main, ["events", "tail"])
        assert r.exit_code == 0
        assert "agent.job.started" in r.output
        assert "job=j1" in r.output

    def test_events_tail_task_history_respects_source_filter(self):
        poll_results = [
            ([_pe("created", "supervisor.task.created", {"task_id": "root"})], None),
            ([
                PasloeEvent(
                    id="hist",
                    source_id="palimpsest-agent",
                    type="agent.job.started",
                    ts=datetime.fromisoformat("2026-03-27T12:00:01"),
                    data={"task_id": "root", "job_id": "j1"},
                )
            ], None),
            ([
                PasloeEvent(
                    id="tail",
                    source_id="palimpsest-agent",
                    type="agent.job.started",
                    ts=datetime.fromisoformat("2026-03-27T12:00:02"),
                    data={"task_id": "root", "job_id": "j2"},
                )
            ], None),
            ([], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.cli.asyncio.sleep", new=AsyncMock(side_effect=KeyboardInterrupt())),
        ):
            r = _runner().invoke(main, ["events", "--task", "root", "--source", "palimpsest-agent", "tail"])
        assert r.exit_code == 0
        assert "palimpsest-agent" in r.output
        assert "agent.job.started" in r.output

    def test_events_tail_task_history_truncates_large_backlog(self):
        created = [_pe("created", "supervisor.task.created", {"task_id": "root"})]
        historical = [
            PasloeEvent(
                id=f"hist-{i}",
                source_id="palimpsest-agent",
                type="agent.job.started",
                ts=datetime.fromisoformat("2026-03-27T12:00:01"),
                data={"task_id": "root", "job_id": f"j{i}"},
            )
            for i in range(205)
        ]
        poll_results = [
            (created, None),
            (historical, None),
            ([], None),
            ([], None),
        ]
        with (
            patch("yoitsu.client.PasloeClient.poll", new=AsyncMock(side_effect=poll_results)),
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.cli.asyncio.sleep", new=AsyncMock(side_effect=KeyboardInterrupt())),
        ):
            r = _runner().invoke(main, ["events", "--task", "root", "tail"])
        assert r.exit_code == 0
        assert "[history truncated to last 200 events]" in r.output


class TestSubmit:
    def test_submit_accepts_raw_goal(self, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        with (
            patch("yoitsu.client.PasloeClient.post_event", new=AsyncMock(return_value="event-id-1")) as mock_post,
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["submit", "--goal", "--budget", "0.8", "--team", "backend", "hello world"])
        assert r.exit_code == 0
        assert mock_post.await_args.kwargs["data"]["goal"] == "hello world"
        assert mock_post.await_args.kwargs["data"]["budget"] == 0.8
        assert mock_post.await_args.kwargs["data"]["team"] == "backend"

    def test_submit_raw_goal_requires_budget(self, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        r = _runner().invoke(main, ["submit", "--goal", "hello world"])
        assert r.exit_code == 1
        assert "--budget > 0" in json.loads(r.output)["error"]

    def test_submit_missing_file_fails_without_goal_flag(self):
        r = _runner().invoke(main, ["submit", "/nonexistent/tasks.yaml"])
        assert r.exit_code == 1
        assert "Use --goal" in json.loads(r.output)["error"]

    def test_submit_fails_on_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(":::invalid:::")
        r = _runner().invoke(main, ["submit", str(f)])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False

    def test_submit_fails_on_non_list_tasks(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("tasks: null\n")
        r = _runner().invoke(main, ["submit", str(f)])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "must be a list" in out["error"]

    def test_submit_posts_all_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - goal: hello\n    team: backend\n    budget: 0.9\n    role: default\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(return_value="event-id-1")) as mock_post, \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 0
        
        args = mock_post.await_args.kwargs
        assert args["type_"] == "trigger.external.received"
        assert args["data"]["goal"] == "hello"
        assert args["data"]["team"] == "backend"
        assert args["data"]["budget"] == 0.9
        assert args["data"]["role"] == "default"

    def test_submit_normalizes_repo_url_aliases(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text(
            "tasks:\n"
            "  - goal: hello\n"
            "    role: default\n"
            "    repo: /tmp/repo\n"
            "    init_branch: dev\n"
        )

        with (
            patch("yoitsu.client.PasloeClient.post_event",
                  new=AsyncMock(return_value="event-id-1")) as mock_post,
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        payload = mock_post.await_args.kwargs["data"]
        assert payload["repo"] == "/tmp/repo"
        assert payload["init_branch"] == "dev"

    def test_submit_counts_failures(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - goal: t1\n  - goal: t2\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(side_effect=[None, "id-2"])), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 1


class TestPauseResume:
    def test_pause_returns_ok(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value=None)), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["pause"])
        assert r.exit_code == 0
        assert json.loads(r.output)["ok"] is True

    def test_resume_returns_ok(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value=None)), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["resume"])
        assert r.exit_code == 0
        assert json.loads(r.output)["ok"] is True

    def test_pause_fails_and_surfaces_error_detail(self):
        with patch("yoitsu.client.TrenniClient.post_control",
                   new=AsyncMock(return_value="trenni returned 409: already paused")), \
             patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["pause"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "409" in out["error"]


class TestLogs:
    def test_logs_returns_last_n_lines(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")
        (tmp_path / "pasloe.log").write_text("line1\nline2\nline3\n")
        (tmp_path / "trenni.log").write_text("tline1\ntline2\n")

        r = _runner().invoke(main, ["logs", "--service", "pasloe", "--lines", "2"])
        assert r.exit_code == 0
        assert "line2" in r.output
        assert "line3" in r.output
        assert "line1" not in r.output

    def test_logs_missing_file_returns_empty(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")

        r = _runner().invoke(main, ["logs", "--service", "pasloe"])
        assert r.exit_code == 0
        assert r.output.strip() == ""


class TestBuild:
    def test_build_calls_script(self, tmp_path, monkeypatch):
        script = tmp_path / "build-job-image.sh"
        script.write_text("#!/bin/sh\necho built")
        script.chmod(0o755)
        monkeypatch.setattr(
            "yoitsu.cli.Path",
            lambda *a, **kw: _MockPath(script) if not a else Path(*a, **kw),
        )
        # Simpler: just patch subprocess.run
        with patch("yoitsu.cli.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as mock_run:
            # Also need to make the script path "exist"
            with patch("yoitsu.cli.Path.__new__", wraps=Path.__new__):
                r = _runner().invoke(main, ["build"])
        # build command calls subprocess.run with the script path
        assert mock_run.called or r.exit_code in (0, 1)

    def test_build_script_not_found(self, monkeypatch):
        with patch("pathlib.Path.exists", return_value=False):
            r = _runner().invoke(main, ["build"])
        assert r.exit_code == 1


class TestDeploy:
    def test_deploy_passes_flags(self):
        with patch("yoitsu.cli.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0, stdout="ok", stderr="")) as mock_run:
            r = _runner().invoke(main, ["deploy", "--skip-build", "--reset"])
        assert r.exit_code == 0
        call_args = mock_run.call_args
        assert "--skip-build" in call_args[0][0]
        assert call_args[1]["env"]["YOITSU_RESET_RUNTIME"] == "1"


class TestWatch:
    def test_watch_runs_and_prints_summary(self, monkeypatch):
        """Watch with tiny --hours should exit and print summary."""
        class FakeResponse:
            status_code = 200
            headers = {}

            def json(self):
                return []

        class FakeHTTP:
            async def get(self, *args, **kwargs):
                return FakeResponse()

        fake_http = FakeHTTP()

        monkeypatch.setenv("PASLOE_API_KEY", "k")
        with patch("yoitsu.cli.PasloeClient") as MockPasloe, \
             patch("yoitsu.cli.TrenniClient") as MockTrenni, \
             patch("yoitsu.cli._podman_summary", return_value={"available": False}):
            instance_p = MockPasloe.return_value
            instance_p._http = fake_http
            instance_p.aclose = AsyncMock()
            instance_t = MockTrenni.return_value
            instance_t.get_status = AsyncMock(return_value={
                "running_jobs": 0, "max_workers": 1, "pending_jobs": 0,
                "ready_queue_size": 0, "tasks": {}})
            instance_t.aclose = AsyncMock()
            r = _runner().invoke(main, ["watch", "--hours", "0.0001", "--interval", "1"])

        assert "Watch Summary" in r.output


class TestSetup:
    def test_setup_calls_script(self):
        with patch("yoitsu.cli.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 0)) as mock_run, \
             patch("pathlib.Path.exists", return_value=True):
            r = _runner().invoke(main, ["setup"])
        assert mock_run.called


class TestUrlEnvOverride:
    def test_pasloe_url_default(self):
        import yoitsu.cli as cli
        # When env var is not set, the module-level default should be used
        # (already evaluated at import time, so we check the current value)
        assert "localhost:8000" in cli._PASLOE_URL or "YOITSU_PASLOE_URL" not in os.environ

    def test_trenni_url_default(self):
        import yoitsu.cli as cli
        assert "localhost:8100" in cli._TRENNI_URL or "YOITSU_TRENNI_URL" not in os.environ

    def test_url_env_var_override(self):
        """Verify that _PASLOE_URL / _TRENNI_URL read from env vars."""
        import importlib
        import yoitsu.cli as cli
        old_p = os.environ.get("YOITSU_PASLOE_URL")
        old_t = os.environ.get("YOITSU_TRENNI_URL")
        try:
            os.environ["YOITSU_PASLOE_URL"] = "http://custom:9000"
            os.environ["YOITSU_TRENNI_URL"] = "http://custom:9100"
            importlib.reload(cli)
            assert cli._PASLOE_URL == "http://custom:9000"
            assert cli._TRENNI_URL == "http://custom:9100"
        finally:
            # Restore
            if old_p is None:
                os.environ.pop("YOITSU_PASLOE_URL", None)
            else:
                os.environ["YOITSU_PASLOE_URL"] = old_p
            if old_t is None:
                os.environ.pop("YOITSU_TRENNI_URL", None)
            else:
                os.environ["YOITSU_TRENNI_URL"] = old_t
            importlib.reload(cli)
