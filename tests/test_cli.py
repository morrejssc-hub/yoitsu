"""CLI integration tests via CliRunner."""
from __future__ import annotations
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from yoitsu.cli import main


def _runner() -> CliRunner:
    return CliRunner()


class TestUp:
    def test_up_fails_if_env_var_missing(self, monkeypatch):
        monkeypatch.delenv("PASLOE_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        r = _runner().invoke(main, ["up"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False
        assert "PASLOE_API_KEY" in out["error"]

    def test_up_succeeds_when_both_already_alive(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        proc.write_pids(pasloe_pid=1, trenni_pid=2)

        with patch("yoitsu.process.is_alive", return_value=True):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True

    def test_up_starts_services_and_writes_pids(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")
        monkeypatch.setattr(proc, "_DEFAULT_CONFIG", tmp_path / "trenni.yaml")
        (tmp_path / "trenni.yaml").touch()

        with (
            patch("yoitsu.process.is_alive", return_value=False),
            patch("yoitsu.process.start_pasloe", return_value=100),
            patch("yoitsu.process.start_trenni", return_value=200),
            patch("yoitsu.cli._wait_ready", new=AsyncMock(return_value=True)),
        ):
            r = _runner().invoke(main, ["up"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["ok"] is True
        assert out["pasloe_pid"] == 100
        assert out["trenni_pid"] == 200
        pids = proc.read_pids()
        assert pids["pasloe"]["pid"] == 100


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
            patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()),
            patch("yoitsu.client.TrenniClient.aclose", new=AsyncMock()),
        ):
            r = _runner().invoke(main, ["status"])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is True
        assert out["pasloe"]["total_events"] == 10
        assert out["trenni"]["running"] is True

    def test_status_marks_dead_service_as_not_alive(self, tmp_path, monkeypatch):
        import yoitsu.process as proc
        monkeypatch.setattr(proc, "_PIDS_FILE", tmp_path / ".pids.json")
        # No PID file — both dead

        r = _runner().invoke(main, ["status"])
        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["pasloe"]["alive"] is False
        assert out["trenni"]["alive"] is False


class TestSubmit:
    def test_submit_fails_on_missing_file(self):
        r = _runner().invoke(main, ["submit", "/nonexistent/tasks.yaml"])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False

    def test_submit_fails_on_invalid_yaml(self, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text(":::invalid:::")
        r = _runner().invoke(main, ["submit", str(f)])
        assert r.exit_code == 1
        out = json.loads(r.output)
        assert out["ok"] is False

    def test_submit_posts_all_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - task: hello\n    role: default\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(return_value="event-id-1")), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 0

    def test_submit_counts_failures(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text("tasks:\n  - task: t1\n  - task: t2\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(side_effect=[None, "id-2"])), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 1
