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
