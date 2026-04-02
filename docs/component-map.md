# Component Map

Date: 2026-04-02
Purpose: Quick reference for where things live in the current codebase.
Planned items are marked explicitly.

## Repository Structure

```
yoitsu/                          # Root monorepo
  pasloe/                        # Event store (git submodule)
  trenni/                        # Scheduler (git submodule)
  palimpsest/                    # Job executor (git submodule)
  yoitsu-contracts/              # Shared types
  config/                        # Deployment config (trenni.yaml)
  deploy/                        # Quadlet manifests
  scripts/                       # Build and deploy scripts
  examples/                      # Example task submissions
  tests/                         # Integration tests
  docs/                          # All documentation
```

## Pasloe (Event Store)

```
pasloe/src/pasloe/
  app.py                         # FastAPI entry point
  api.py                         # HTTP endpoints (POST/GET /events)
  store.py                       # Event persistence
  pipeline.py                    # Ingest -> committed pipeline
  webhook_delivery.py            # Async webhook fan-out
  database.py                    # SQLAlchemy models and sessions
  models.py                      # ORM models
  config.py                      # Configuration
  domains/                       # Domain-specific projections
    jobs.py                      # Job event queries + stats
    tasks.py                     # Task event queries + stats
    llm.py                       # LLM call queries + token/cost
    tools.py                     # Tool execution queries
```

Key tables: ingress_events, events, jobs, tasks, llm_events, tool_events

## Trenni (Scheduler)

```
trenni/trenni/
  supervisor.py                  # Entry point: intake + execution phases
  state.py                       # In-memory TaskRecord, JobRecord, ready queue
  scheduler.py                   # Condition evaluation, queue admission
  spawn_handler.py               # Spawn expansion: parent -> children + join
  replay.py                      # State reconstruction from events
  checkpoint.py                  # Durable progress markers
  isolation.py                   # Abstract isolation backend
  podman_backend.py              # Podman/Quadlet container management
  runtime_builder.py             # JobRuntimeSpec assembly
  runtime_types.py               # Runtime dataclasses
  trigger_evaluator.py           # External event -> task translation
  control_api.py                 # REST API (/control/tasks, /control/jobs)
  pasloe_client.py               # Event polling and submission
  config.py                      # YAML config, TeamConfig, LLM defaults
  cli.py                         # CLI interface
```

Key state: TaskRecord, JobRecord, ready queue, running_jobs_by_team

## Palimpsest (Job Executor)

```
palimpsest/palimpsest/
  runner.py                      # Four-stage pipeline orchestrator
  emitter.py                     # Event emission to Pasloe
  events.py                      # Event type definitions
  cli.py                         # Container entry point
  config.py                      # JobConfig, PublicationConfig

  stages/
    preparation.py               # Workspace setup (git clone, deps)
    workspace.py                 # Backward-compat alias for preparation setup
    context.py                   # Agent prompt and context assembly
    interaction.py               # LLM loop + tool execution
    publication.py               # Result delivery (git push)
    finalization.py              # Cleanup

  runtime/
    context.py                   # RuntimeContext (job-scoped resources)
    contexts.py                  # @context_provider decorator + loader resolution
    roles.py                     # RoleManager, TeamManager (evo resolution)
    tools.py                     # UnifiedToolGateway, tool resolution
    llm.py                       # LLM provider integration
    event_gateway.py             # Tool result -> event bridge
    retry_utils.py               # Retry logic
    mock_llm.py                  # Mock for testing
```

## Evolvable Layer (evo/)

```
palimpsest/evo/
  roles/
    default.py                   # Fallback worker
    planner.py                   # Goal decomposition via spawn
    implementer.py               # Code implementation
    reviewer.py                  # Code review
    evaluator.py                 # Quality assessment
  tools/
    file_tools.py                # read_file, write_file, list_files
  prompts/
    default.md                   # Default system prompt
    planner.md                   # Planner system prompt
    planner-join.md              # Join phase prompt
    evaluator.md                 # Evaluator system prompt
  contexts/
    loaders.py                   # Context providers:
                                 #   available_roles, eval_context,
                                 #   join_context, job_trace,
                                 #   file_tree_provider,
                                 #   task_description_provider,
                                 #   version_history_provider
  teams/
    <team>/                      # Team-specific overrides (supported by runtime;
                                 # currently not populated in this repo)
      roles/
      tools/
      prompts/
      contexts/
```

## yoitsu-contracts (Shared Types)

```
yoitsu-contracts/src/yoitsu_contracts/
  events.py                      # All event schemas (BaseEvent, *Data models)
  config.py                      # JobConfig, TriggerData, SpawnTaskData, etc.
  conditions.py                  # Condition tree (TaskIs, All, Any, Not)
  client.py                      # Pasloe HTTP client
  role_metadata.py               # RoleMetadataReader, @role decorator
  observation.py                 # Observation event types
  artifact.py                    # ArtifactRef, ArtifactBinding (ADR-0013)
  env.py                         # Environment helpers (git token injection)
```

**Landed:** `ArtifactRef` and `ArtifactBinding` models, `artifact_bindings`
field on `JobCompletedData`.

**Pending (ADR-0013 backend/runtime):**
```
  artifact_backend.py            # ArtifactBackend protocol (pending)
  local_fs_backend.py            # LocalFSBackend implementation (pending)
```

## Event Types

| Event | Model | Emitter |
|-------|-------|---------|
| agent.job.started | job | Palimpsest |
| agent.job.completed | job | Palimpsest |
| agent.job.failed | job | Palimpsest |
| agent.job.cancelled | job | Palimpsest |
| agent.job.runtime_issue | job | Palimpsest |
| agent.job.stage_transition | job | Palimpsest |
| agent.job.spawn_request | job | Palimpsest |
| agent.llm.request | llm | Palimpsest |
| agent.llm.response | llm | Palimpsest |
| agent.tool.exec | tool | Palimpsest |
| agent.tool.result | tool | Palimpsest |
| supervisor.task.created | task | Trenni |
| supervisor.task.evaluating | task | Trenni |
| supervisor.task.completed | task | Trenni |
| supervisor.task.failed | task | Trenni |
| supervisor.task.partial | task | Trenni |
| supervisor.task.eval_failed | task | Trenni |
| supervisor.task.cancelled | task | Trenni |
| supervisor.job.launched | job | Trenni |
| supervisor.job.enqueued | job | Trenni |
| supervisor.checkpoint | -- | Trenni |
| trigger.external.received | -- | External |
| observation.* | -- | Trenni / Palimpsest |

## Configuration

### trenni.yaml

```yaml
pasloe_url: "http://localhost:8000"
pasloe_api_key_env: "PASLOE_API_KEY"
source_id: "trenni-supervisor"

runtime:
  kind: "podman"
  podman:
    socket_uri: ""
    pod_name: "yoitsu-dev"
    image: "localhost/yoitsu-palimpsest-job:dev"
    env_allowlist: ["OPENAI_API_KEY"]

max_workers: 4
poll_interval: 2.0

default_llm:
  model: "..."
  max_iterations: 30

default_workspace:
  depth: 1

default_publication:
  strategy: "branch"
  branch_prefix: "palimpsest/job"

# Optional:
teams:
  backend:
    runtime:
      image: "..."
```

## Key Data Flow

```
External trigger
  -> POST /events (Pasloe)
  -> Trenni intake: create TaskRecord (pending)
  -> Trenni execution: launch planner container
    -> Palimpsest: preparation -> context -> interaction -> publication
    -> spawn_request event
  -> Trenni intake: expand children + jobs + join
  -> Trenni execution: launch worker containers (condition-gated)
    -> Palimpsest: preparation -> context -> interaction -> publication
    -> job.completed event (with summary/status/code and optional git_ref)
  -> Trenni intake: task.evaluating -> launch eval container
    -> Palimpsest: eval context -> LLM judges -> semantic verdict
  -> Trenni intake: task.completed / task.failed
  -> Join condition met -> launch join container
    -> Palimpsest: join context -> review children -> maybe create PR
  -> Root task terminal
```
