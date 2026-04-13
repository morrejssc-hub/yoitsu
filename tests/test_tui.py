"""Tests for TUI helper functions."""
from __future__ import annotations


def test_build_task_tree_flat():
    """Root tasks with no children produce tree with empty child lists."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "t1", "state": "running", "bundle": "factorio", "goal": "Do A"},
        {"task_id": "t2", "state": "pending", "bundle": "factorio", "goal": "Do B"},
    ]
    tree, roots = _build_task_tree(tasks)
    assert roots == ["t1", "t2"]
    assert tree["t1"] == []
    assert tree["t2"] == []


def test_build_task_tree_nested():
    """Child task IDs (containing /) nest under their parent."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "root", "state": "completed", "bundle": "f", "goal": "Root"},
        {"task_id": "root/abc", "state": "running", "bundle": "f", "goal": "Child A"},
        {"task_id": "root/def", "state": "pending", "bundle": "f", "goal": "Child B"},
        {"task_id": "root/abc/ghi", "state": "pending", "bundle": "f", "goal": "Grandchild"},
    ]
    tree, roots = _build_task_tree(tasks)
    assert roots == ["root"]
    assert sorted(tree["root"]) == ["root/abc", "root/def"]
    assert tree["root/abc"] == ["root/abc/ghi"]
    assert tree["root/def"] == []
    assert tree["root/abc/ghi"] == []


def test_build_task_tree_orphan_children():
    """Children whose parent is missing still appear in the tree."""
    from yoitsu.tui import _build_task_tree

    tasks = [
        {"task_id": "root/abc", "state": "running", "bundle": "f", "goal": "Orphan"},
    ]
    tree, roots = _build_task_tree(tasks)
    # root/abc's parent "root" is not in the task list, so root/abc becomes a root
    assert roots == ["root/abc"]
    assert tree["root/abc"] == []


def test_render_dag_simple_tree():
    """DAG renderer shows parent, siblings, and marks current task."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "completed"},
        "root/a": {"task_id": "root/a", "state": "completed"},
        "root/b": {"task_id": "root/b", "state": "running"},
        "root/c": {"task_id": "root/c", "state": "pending"},
    }
    tree = {"root": ["root/a", "root/b", "root/c"], "root/a": [], "root/b": [], "root/c": []}
    result = _render_dag(tree, tasks_by_id, "root/b")
    assert "root" in result
    assert "root/a" in result
    assert "root/b" in result
    assert "root/c" in result
    # Current task should be marked
    assert "<<<" in result or "<<" in result or "←" in result


def test_render_dag_with_children():
    """DAG renderer shows direct children of the current task."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "completed"},
        "root/a": {"task_id": "root/a", "state": "running"},
        "root/a/x": {"task_id": "root/a/x", "state": "pending"},
    }
    tree = {"root": ["root/a"], "root/a": ["root/a/x"], "root/a/x": []}
    result = _render_dag(tree, tasks_by_id, "root/a")
    assert "root/a/x" in result


def test_render_dag_root_task():
    """When current task is root, show it and its children."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root": {"task_id": "root", "state": "running"},
        "root/a": {"task_id": "root/a", "state": "pending"},
    }
    tree = {"root": ["root/a"], "root/a": []}
    result = _render_dag(tree, tasks_by_id, "root")
    assert "root" in result
    assert "root/a" in result


def test_render_dag_multiple_root_siblings():
    """When current task is a root, show all root siblings."""
    from yoitsu.tui import _render_dag

    tasks_by_id = {
        "root1": {"task_id": "root1", "state": "completed"},
        "root2": {"task_id": "root2", "state": "running"},
        "root3": {"task_id": "root3", "state": "pending"},
    }
    tree = {"root1": [], "root2": [], "root3": []}
    roots = ["root1", "root2", "root3"]
    result = _render_dag(tree, tasks_by_id, "root2", roots)
    assert "root1" in result
    assert "root2" in result
    assert "root3" in result
    assert " ←" in result  # Current task should be marked


def test_format_summary_all_available():
    """Summary line shows trenni + podman + llm when all available."""
    from yoitsu.tui import _format_summary

    trenni = {"running_jobs": 2, "max_workers": 4, "pending_jobs": 3, "ready_queue_size": 1}
    podman = {"available": True, "running": 5, "exited": 2, "total": 7}
    llm = {"by_model": [{"model": "claude", "total_input_tokens": 120000, "total_output_tokens": 45000, "total_cost": 1.234}]}
    result = _format_summary(trenni, podman, llm)
    assert "2" in result and "4" in result  # running/max
    assert "3" in result  # pending
    assert "5" in result  # podman running
    assert "$1.23" in result or "1.234" in result  # cost


def test_format_summary_services_down():
    """Summary shows unreachable when services are down."""
    from yoitsu.tui import _format_summary

    result = _format_summary(None, {"available": False}, None)
    assert "unreachable" in result.lower() or "?" in result


# ── filter helper tests ───────────────────────────────────────────────────────


def test_matches_filter_case_insensitive():
    """Filter matches any cell case-insensitively."""
    from yoitsu.tui import _matches_filter

    row = ("12:00:00", "agent.job.completed", "palimpsest", "job:abc", "done")
    assert _matches_filter(row, "completed")
    assert _matches_filter(row, "COMPLETED")
    assert _matches_filter(row, "pali")
    assert not _matches_filter(row, "nonexistent")


def test_matches_filter_empty_passes_all():
    """Empty filter passes all rows."""
    from yoitsu.tui import _matches_filter

    row = ("a", "b", "c")
    assert _matches_filter(row, "")
