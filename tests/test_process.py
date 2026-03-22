"""Tests for PID file management and liveness checks."""
from __future__ import annotations
import json
import os
import signal
from pathlib import Path
from unittest.mock import patch

import pytest

import yoitsu.process as proc


class TestIsAlive:
    def test_alive_process_returns_true(self):
        assert proc.is_alive(os.getpid()) is True

    def test_dead_process_returns_false(self):
        with patch("os.kill", side_effect=ProcessLookupError):
            assert proc.is_alive(99999999) is False

    def test_permission_error_treated_as_alive(self):
        with patch("os.kill", side_effect=PermissionError):
            assert proc.is_alive(1) is True


class TestPidFile:
    def test_write_and_read_pids(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=100, trenni_pid=200)
        data = proc.read_pids()
        assert data["pasloe"]["pid"] == 100
        assert data["trenni"]["pid"] == 200

    def test_read_pids_returns_none_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        assert proc.read_pids() is None

    def test_clear_pids_removes_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.write_pids(pasloe_pid=1, trenni_pid=2)
        proc.clear_pids()
        assert proc.read_pids() is None

    def test_clear_pids_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "ROOT", tmp_path)
        proc.clear_pids()  # file doesn't exist — should not raise


class TestStartStop:
    def test_start_pasloe_launches_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "_PASLOE_DIR", tmp_path)
        monkeypatch.setattr(proc, "_PASLOE_LOG", tmp_path / "pasloe.log")

        fake_proc = type("P", (), {"pid": 42})()
        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            pid = proc.start_pasloe()
        assert pid == 42
        mock_popen.assert_called_once()
        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[0] == "uv"
        assert "uvicorn" in cmd

    def test_start_trenni_passes_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr(proc, "_TRENNI_DIR", tmp_path)
        monkeypatch.setattr(proc, "_TRENNI_LOG", tmp_path / "trenni.log")

        fake_proc = type("P", (), {"pid": 99})()
        config = tmp_path / "my.yaml"
        config.touch()
        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            pid = proc.start_trenni(config_path=config)
        assert pid == 99
        cmd = mock_popen.call_args[0][0]
        assert str(config) in cmd

    def test_kill_pid_sends_sigterm_then_sigkill(self):
        kill_calls: list[tuple] = []

        def fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))
            if sig == signal.SIGKILL:
                raise ProcessLookupError

        with patch("os.kill", side_effect=fake_kill):
            proc.kill_pid(123, wait_s=0.05)

        sigs = [sig for _, sig in kill_calls]
        assert signal.SIGTERM in sigs
        assert signal.SIGKILL in sigs
