# Yoitsu

Yoitsu is the umbrella repo for a four-repo agent stack:

- `pasloe` stores the append-only event stream.
- `trenni` schedules jobs, evaluates spawn conditions, and owns isolation.
- `palimpsest` runs one job at a time inside the chosen isolation backend.
- `yoitsu-contracts` defines the shared event, config, condition, and client contracts.

The current architecture is documented in [docs/architecture.md](docs/architecture.md). The merged architecture decision record lives in [docs/adr/0001-architecture-redesign.md](docs/adr/0001-architecture-redesign.md).

## Repositories

| Repository | Path | Role |
|---|---|---|
| [yoitsu-contracts](https://github.com/guan-spicy-wolf/yoitsu-contracts) | `yoitsu-contracts/` | Shared contracts and Pasloe clients |
| [palimpsest](https://github.com/guan-spicy-wolf/palimpsest) | `palimpsest/` | Runtime for a single job execution |
| [trenni](https://github.com/guan-spicy-wolf/trenni) | `trenni/` | Scheduler, spawn expansion, replay, checkpointing |
| [pasloe](https://github.com/guan-spicy-wolf/pasloe) | `pasloe/` | Schema-agnostic event store |

## Architecture Summary

- `Job` and `Task` are separate. A job only succeeds or fails. A task is implicitly active until Trenni emits a terminal event: `task.completed`, `task.failed`, or `task.cancelled`.
- `spawn()` is the only orchestration primitive. Trenni expands it into child jobs plus a conditional join job.
- Trenni is split into `state`, `scheduler`, `spawn_handler`, `replay`, `checkpoint`, and `isolation` modules.
- Isolation is a protocol. `PodmanBackend` is the current implementation.
- Shared wire contracts live in `yoitsu-contracts`, not as duplicated ad hoc dict parsing in each repo.

## Quick Start

Prerequisites:

- Python 3.11+
- `uv`
- Podman if you want to run real isolated jobs
- `PASLOE_API_KEY`
- an LLM API key such as `OPENAI_API_KEY`

Setup:

```bash
./scripts/setup.sh
uv sync

export PASLOE_API_KEY=yoitsu-test-key-2026
export OPENAI_API_KEY=<your-api-key>
```

Start the stack:

```bash
uv run yoitsu up
```

Submit tasks:

```bash
uv run yoitsu submit examples/tasks.yaml
```

Inspect status and logs:

```bash
uv run yoitsu status
uv run yoitsu logs --service trenni --lines 50
uv run yoitsu logs --service pasloe --lines 50
python3 scripts/monitor.py --hours 5
```

Pause or resume scheduling:

```bash
uv run yoitsu pause
uv run yoitsu resume
```

Stop the stack:

```bash
uv run yoitsu down
```

## Task Submission

Yoitsu CLI still accepts a simple YAML task list. Trenni assigns a `task_id` when one is not provided.

```yaml
tasks:
  - task: "Add unit tests for the user authentication module"
    role: "default"
    repo_url: "https://github.com/your-org/your-repo.git"

  - task: "Investigate flaky publication guardrails"
    role: "default"
    repo_url: "https://github.com/your-org/your-repo.git"
```

## Configuration

`config/trenni.yaml` configures scheduling, isolation, and default job settings.

```yaml
pasloe_url: "http://localhost:8000"
pasloe_api_key_env: "PASLOE_API_KEY"
source_id: "trenni-supervisor"

runtime:
  kind: "podman"
  podman:
    socket_uri: "unix:///run/podman/podman.sock"
    pod_name: "yoitsu-dev"
    image: "localhost/yoitsu-palimpsest-job:dev"
    pull_policy: "never"
    git_token_env: "GITHUB_TOKEN"
    env_allowlist:
      - "OPENAI_API_KEY"

max_workers: 4
poll_interval: 2.0

default_llm:
  model: "kimi-k2.5"
  api_base: "https://coding.dashscope.aliyuncs.com/v1"
  api_key_env: "OPENAI_API_KEY"
  max_iterations: 30
  temperature: 0.2
```

## Quadlet Deployment

For the current rootless Podman + Quadlet development deployment:

```bash
./scripts/build-job-image.sh
./scripts/deploy-quadlet.sh
./scripts/quadlet-status.sh
```

The deployment model is documented in [deploy/quadlet/README.md](deploy/quadlet/README.md).
