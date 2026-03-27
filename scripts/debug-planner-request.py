#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
PREFERRED_PYTHON = ROOT / "palimpsest" / ".venv" / "bin" / "python"

if (
    os.environ.get("YOITSU_PLANNER_DEBUG_REEXEC") != "1"
    and PREFERRED_PYTHON.is_file()
    and Path(sys.executable).resolve() != PREFERRED_PYTHON.resolve()
):
    env = dict(os.environ)
    env["YOITSU_PLANNER_DEBUG_REEXEC"] = "1"
    raise SystemExit(
        subprocess.call([str(PREFERRED_PYTHON), __file__, *sys.argv[1:]], env=env)
    )

for venv_root in (ROOT / "palimpsest" / ".venv", ROOT / ".venv", ROOT / "trenni" / ".venv"):
    lib_dir = venv_root / "lib"
    if not lib_dir.is_dir():
        continue
    for site_packages in sorted(lib_dir.glob("python*/site-packages")):
        if site_packages.is_dir():
            sys.path.insert(0, str(site_packages))
for rel in ("palimpsest", "trenni", "yoitsu-contracts"):
    sys.path.insert(0, str(ROOT / rel))

from palimpsest.config import EventStoreConfig, JobContextConfig, JobConfig, LLMConfig, PublicationConfig, ToolsConfig, WorkspaceConfig
from palimpsest.runtime.event_gateway import EventGateway
from palimpsest.runtime.llm import UnifiedLLMGateway
from palimpsest.runtime.roles import RoleManager, TeamManager
from palimpsest.runtime.tools import UnifiedToolGateway
from palimpsest.stages.context import build_context
from palimpsest.stages.workspace import setup_workspace
from trenni.config import TrenniConfig


class _NullEmitter:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)

    def close(self) -> None:
        return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Short-circuit planner debug harness: assemble planner context and optionally call the model once."
    )
    parser.add_argument(
        "--config",
        default=str(ROOT / "deploy/quadlet/trenni.dev.yaml"),
        help="Path to trenni YAML config",
    )
    parser.add_argument(
        "--task-file",
        default=str(ROOT / "examples/smoke-planner-version-bump.yaml"),
        help="Task YAML to read the first root task from",
    )
    parser.add_argument("--task-index", type=int, default=0, help="Index into task-file tasks[]")
    parser.add_argument("--goal", default="", help="Override task goal text")
    parser.add_argument("--team", default="", help="Override team")
    parser.add_argument("--role", default="", help="Force a specific role instead of team planner")
    parser.add_argument("--mode", default="initial", choices=["initial", "join"], help="Planner invocation mode")
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra role param override. VALUE is parsed as YAML when possible.",
    )
    parser.add_argument("--job-id", default="", help="Synthetic job id to use")
    parser.add_argument("--task-id", default="", help="Synthetic task id to use")
    parser.add_argument("--dump-dir", default="", help="Optional directory to write assembled prompt and response files")
    parser.add_argument("--no-call", action="store_true", help="Only print assembled prompt/tools without calling the model")
    parser.add_argument("--keep-workspace", action="store_true", help="Do not delete the temporary workspace")
    return parser.parse_args()


def _load_task_payload(path: Path, index: int) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tasks = data.get("tasks") or []
    if not isinstance(tasks, list) or index >= len(tasks):
        raise IndexError(f"No task at index {index} in {path}")
    task = tasks[index]
    if not isinstance(task, dict):
        raise TypeError(f"Task at index {index} in {path} is not an object")
    return task


def _parse_value(raw: str) -> Any:
    try:
        return yaml.safe_load(raw)
    except Exception:
        return raw


def _apply_param_overrides(target: dict[str, Any], items: list[str]) -> None:
    for item in items:
        if "=" not in item:
            raise ValueError(f"Invalid --param {item!r}; expected KEY=VALUE")
        key, value = item.split("=", 1)
        target[key] = _parse_value(value)


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _choose_role(team_name: str, forced_role: str, evo_root: Path) -> str:
    if forced_role:
        return forced_role
    team_manager = TeamManager(evo_root)
    return team_manager.resolve(team_name or "default").planner_role


def _write_dump(dump_dir: Path, *, system_prompt: str, user_task: str, tools_schema: list[dict], response: dict | None) -> None:
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / "system.txt").write_text(system_prompt, encoding="utf-8")
    (dump_dir / "user.txt").write_text(user_task, encoding="utf-8")
    (dump_dir / "tools.json").write_text(json.dumps(tools_schema, ensure_ascii=False, indent=2), encoding="utf-8")
    if response is not None:
        (dump_dir / "response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = _parse_args()
    task_payload = _load_task_payload(Path(args.task_file), args.task_index)
    trenni_cfg = TrenniConfig.from_yaml(args.config)
    _load_env_file(Path.home() / ".config/containers/systemd/yoitsu/trenni.env")

    evo_root = ROOT / "palimpsest" / "evo"
    role_params = dict(task_payload.get("context") or {})
    _apply_param_overrides(role_params, args.param)
    goal = str(args.goal or task_payload.get("goal") or "").strip()
    if not goal:
        raise ValueError("No goal text provided")

    team = str(args.team or task_payload.get("team") or "default")
    budget = float(task_payload.get("budget") or 0.0)
    role_name = _choose_role(team, args.role, evo_root)

    role_params.setdefault("mode", args.mode)
    role_params.setdefault("goal", goal)
    if budget > 0 and "budget" not in role_params:
        role_params["budget"] = budget

    job_id = args.job_id or f"debug-{uuid.uuid4().hex[:12]}"
    task_id = args.task_id or f"debug-{uuid.uuid4().hex[:12]}"

    llm_payload = dict(trenni_cfg.default_llm or {})
    if budget > 0 and not llm_payload.get("max_total_cost"):
        llm_payload["max_total_cost"] = budget

    job_config = JobConfig(
        job_id=job_id,
        task_id=task_id,
        task=goal,
        role=role_name,
        role_params=role_params,
        team=team,
        workspace=WorkspaceConfig(**dict(trenni_cfg.default_workspace or {})),
        llm=LLMConfig(**llm_payload),
        tools=ToolsConfig(),
        publication=PublicationConfig(strategy="skip"),
        eventstore=EventStoreConfig(
            url=trenni_cfg.eventstore_url,
            api_key_env=trenni_cfg.pasloe_api_key_env,
            source_id=trenni_cfg.default_eventstore_source,
        ),
        context=JobContextConfig(),
    )

    emitter = _NullEmitter()
    gateway = EventGateway(emitter, job_id=job_id, task_id=task_id)

    resolver = RoleManager(evo_root)
    spec = resolver.resolve(role_name, **dict(role_params))
    llm = UnifiedLLMGateway(job_config.llm, gateway)

    workspace_path: str | None = None
    response_payload: dict[str, Any] | None = None
    try:
        workspace_cfg = spec.workspace_fn(**role_params)
        branch_prefix = str(
            role_params.get("branch_prefix")
            or getattr(spec.publication_fn, "__publication_branch_prefix__", "palimpsest/job")
        )
        workspace_path = setup_workspace(
            job_id,
            workspace_cfg,
            branch_prefix,
            task_id=task_id,
            goal=goal,
            gateway=gateway,
            cost_tracking_degraded=llm.cost_tracking_degraded(),
        )

        context_spec = spec.context_fn(
            workspace=workspace_path,
            job_id=job_id,
            task=goal,
            job_config=job_config,
            evo_root=str(evo_root),
            **role_params,
        )
        context = build_context(
            job_id,
            workspace_path,
            goal,
            context_spec,
            job_config,
            gateway,
            evo_root=evo_root,
        )
        tools = UnifiedToolGateway(
            job_config.tools,
            evo_root,
            spec.tools,
            gateway,
            tool_timeout_seconds=job_config.llm.tool_timeout_seconds,
        )

        print(f"role={role_name} mode={args.mode} team={team}")
        print(f"model={job_config.llm.model} api_base={job_config.llm.api_base or '(default)'}")
        print(f"workspace={workspace_path}")
        print(f"tools={spec.tools}")
        print("\n===== SYSTEM PROMPT =====\n")
        print(context["system"])
        print("\n===== USER TASK =====\n")
        print(context["task"])
        print("\n===== TOOLS =====\n")
        print(json.dumps(tools.schema(), ensure_ascii=False, indent=2))

        if args.no_call:
            if args.dump_dir:
                _write_dump(
                    Path(args.dump_dir),
                    system_prompt=context["system"],
                    user_task=context["task"],
                    tools_schema=tools.schema(),
                    response=None,
                )
            return 0

        response = llm.call(
            [
                {"role": "system", "content": context["system"]},
                {"role": "user", "content": context["task"]},
            ],
            tools.schema(),
        )

        response_payload = {
            "finish_reason": response.finish_reason,
            "text": response.text,
            "tool_calls": [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                }
                for tc in response.tool_calls
            ],
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "raw_message": response.raw_message,
        }

        print("\n===== RESPONSE =====\n")
        print(json.dumps(response_payload, ensure_ascii=False, indent=2))

        if args.dump_dir:
            _write_dump(
                Path(args.dump_dir),
                system_prompt=context["system"],
                user_task=context["task"],
                tools_schema=tools.schema(),
                response=response_payload,
            )
        return 0
    finally:
        gateway.close()
        if workspace_path and not args.keep_workspace:
            shutil.rmtree(workspace_path, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - explicit operator-oriented CLI path
        print(f"[error] {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
