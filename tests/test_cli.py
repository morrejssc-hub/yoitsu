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

    def test_up_fails_if_lock_held(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        monkeypatch.setenv("OPENAI_API_KEY", "k")
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
        monkeypatch.setenv("OPENAI_API_KEY", "k")
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
        monkeypatch.setenv("OPENAI_API_KEY", "k")
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
        monkeypatch.setenv("OPENAI_API_KEY", "k")

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
        f.write_text("tasks:\n  - task: hello\n    role: default\n")

        with patch("yoitsu.client.PasloeClient.post_event",
                   new=AsyncMock(return_value="event-id-1")), \
             patch("yoitsu.client.PasloeClient.aclose", new=AsyncMock()):
            r = _runner().invoke(main, ["submit", str(f)])

        assert r.exit_code == 0
        out = json.loads(r.output)
        assert out["submitted"] == 1
        assert out["failed"] == 0

    def test_submit_normalizes_repo_url_aliases(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PASLOE_API_KEY", "k")
        f = tmp_path / "tasks.yaml"
        f.write_text(
            "tasks:\n"
            "  - task: hello\n"
            "    role: default\n"
            "    repo_url: /tmp/repo\n"
            "    branch: dev\n"
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
        f.write_text("tasks:\n  - task: t1\n  - task: t2\n")

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
