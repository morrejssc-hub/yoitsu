from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_monitor_module():
    root = Path(__file__).resolve().parent.parent
    path = root / "scripts" / "monitor.py"
    spec = importlib.util.spec_from_file_location("yoitsu_monitor_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_process_event_tracks_container_identity(tmp_path):
    monitor_mod = _load_monitor_module()
    monitor = monitor_mod.Monitor(
        duration_hours=0.1,
        state_file=tmp_path / "monitor-state.json",
        report_dir=tmp_path,
    )

    monitor._process_event({
        "type": "supervisor.job.launched",
        "ts": "2026-03-23T12:00:00",
        "data": {
            "job_id": "job-1",
            "source_event_id": "evt-1",
            "runtime_kind": "podman",
            "container_id": "abc123def456",
            "container_name": "yoitsu-job-job-1",
        },
    })

    rec = monitor.jobs["job-1"]
    assert rec.status == "launched"
    assert rec.runtime_kind == "podman"
    assert rec.container_id == "abc123def456"
    assert rec.container_name == "yoitsu-job-job-1"


def test_podman_summary_parser_counts_running_and_exited():
    monitor_mod = _load_monitor_module()

    summary = monitor_mod._podman_summary_from_json(
        '[{"Names":"job-a","State":"running"},{"Names":"job-b","State":"exited"}]'
    )

    assert summary.available is True
    assert summary.total == 2
    assert summary.running == 1
    assert summary.exited == 1
