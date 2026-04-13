# ADR-0012: Factorio Bundle — Stateful Task Worked Example

- Status: Accepted (Revised 2026-04-10)
- Date: 2026-04-01
- Revised: 2026-04-10
- Related: ADR-0015, ADR-0016, ADR-0017

> **修订说明**：本 ADR 已完整重写，从 Team 模型迁移到 Bundle + Capability 模型。旧版本保留在 `docs/archive/adr/0012-factorio-task-source.md` 作为历史参考。

## Context

Factorio 是一个长期运行的无头游戏进程，可通过 RCON 远程控制。它是一个有状态的、非 Git-native 的任务源，为 Yoitsu 提供了一个"硬场景"——必须同时处理：

- 持久世界状态（save 文件）
- 实时脚本执行（RCON bridge）
- 代码演化（bundle repo 中的 Lua 脚本）
- 并发控制（单实例世界）

本 ADR 是 Bundle + Capability 架构的 **worked example**，展示新模型如何处理最复杂的有状态场景。

## Decisions

### D1. Factorio is a Yoitsu Bundle

Factorio 作为一个名为 `"factorio"` 的 bundle 注册在 Trenni：

```yaml
bundles:
  factorio:
    source:
      url: "https://github.com/guan-spicy-wolf/factorio-bundle.git"
      selector: evolve
    runtime:
      image: "localhost/yoitsu-factorio-job:dev"
      pod_name: null
      extra_networks: ["factorio-net"]
      env_allowlist:
        - "RCON_HOST"
        - "RCON_PORT"
        - "RCON_PASSWORD"
        - "OPENAI_API_KEY"
    scheduling:
      max_concurrent_jobs: 1
    observation:
      accumulate: 20
      cooldown_minutes: 30
```

Bundle 的 `scheduling.max_concurrent_jobs: 1` 实现独占式并发控制（见 D8）。

### D2. Factorio Bundle Repo 结构

Factorio bundle 是一个独立 git 仓库：

```
factorio-bundle/
├── bundle.yaml              # 元数据 + artifacts 声明
├── capabilities/
│   ├── rcon_bridge.py       # RCON 连接管理
│   ├── git_workspace.py     # workspace clone + publish
│   └── factorio_save.py     # world save checkpoint
├── roles/
│   ├── planner.py           # factorio planner
│   ├── worker.py            # factorio worker
│   └── evaluator.py         # factorio evaluator
├── tools/
│   └── call_script.py       # RCON 脚本执行工具
├── contexts/
│   ├── factorio_scripts.py  # 脚本目录上下文
│   └── task_history.py      # Pasloe 事件历史
├── prompts/
│   ├── planner.md
│   ├── worker.md
│   └── evaluator.md
├── observations/
│   ├── rcon_timeout.py      # RCON 超时分析
│   └── script_error.py      # 脚本错误分析
├── scripts/                 # Lua 脚本目录
│   ├── queries/
│   ├── actions/
│   └── utils/
├── lib/
│   └── factorio_utils.py
└── examples/
```

### D3. Target Source 与 Bundle Source 分离

Job 有两个独立的 workspace 来源：

| 来源 | 内容 | 用途 |
|---|---|---|
| **Bundle Source** | factorio-bundle repo | runtime 加载 roles/capabilities/tools |
| **Target Source** | factorio-agent repo（或其他目标仓库） | agent 执行任务、读写脚本 |

**ctx.workspace 归属**：

- `ctx.bundle_workspace` = BundleSource.workspace（加载 bundle 代码）
- `ctx.target_workspace` = TargetSource.workspace（agent 执行任务）

**准备阶段**：

- `git_workspace` capability clone 目标仓库到 `ctx.target_workspace`
- bundle 代码已由 Trenni 提前物化在 `ctx.bundle_workspace`

**发布阶段**：

- `git_workspace` capability finalize 在 `ctx.target_workspace` 执行 git commit + push
- **Artifact URI 指向远端仓库**：`git+https://github.com/org/factorio-agent@sha`
- **不能指向 ephemeral workspace 路径**（如 `git+file:///tmp/workspace@sha`）

### D4. RCON Bridge 是 Capability

`rcon_bridge` capability 管理 RCON 连接生命周期：

```python
class RconBridgeCapability:
    name = "rcon_bridge"
    
    def setup(self, ctx: JobContext) -> list[EventData]:
        host = os.environ.get("RCON_HOST", "factorio-server")
        port = int(os.environ.get("RCON_PORT", 27015))
        password = os.environ.get("RCON_PASSWORD", "")
        
        self.bridge = RconBridge(host, port, password)
        ctx.resources["rcon_bridge"] = self.bridge
        
        return [EventData(type="rcon.connected", data={
            "host": host, "port": port
        })]
    
    def finalize(self, ctx: JobContext) -> FinalizeResult:
        events = []
        try:
            self.bridge.close()
            events.append(EventData(type="rcon.disconnected", data={}))
            return FinalizeResult(events=events, success=True)
        except Exception as e:
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "disconnect",
                "error": str(e)
            }))
            # RCON 断开失败不影响 artifact 持久化
            return FinalizeResult(events=events, success=True)
```

Role 声明 `needs=["rcon_bridge"]`，runtime 在 preparation 阶段调用 `setup()`，finalization 阶段调用 `finalize()`。

**注意**：`rcon_bridge` 的 finalize 返回 `success=True` 即使断开失败，因为 artifact 持久化已在其他 capability 完成。

### D5. call_script Tool 依赖 RCON Bridge

`call_script` 工具通过 `ctx.resources` 获取 RCON bridge：

```python
@tool
def call_script(name: str, args: dict, ctx: ToolContext) -> ToolResult:
    bridge = ctx.resources.get("rcon_bridge")
    if not bridge:
        return ToolResult(success=False, output="RCON bridge not available")
    
    # 同步脚本（如果 target workspace 版本更新）
    script_path = ctx.target_workspace / "scripts" / name  # 使用 target_workspace
    if script_path.exists():
        sync_result = bridge.sync_script(name, script_path)
        if not sync_result.success:
            return sync_result
    
    # 执行脚本
    return bridge.execute(name, args)
```

工具不管理连接生命周期——那是 capability 的职责。工具只负责"调用"。

### D6. Server 独立部署

Factorio server 作为独立的 Quadlet 容器运行：

```
                ┌─── Pod: yoitsu-dev ───┐
                │ postgres  pasloe      │
                │ trenni                 │
                └───────────────────────┘

yoitsu-factorio-job ──RCON──▶ factorio-server
                              (factorio-net)
```

- `factorio-server` 运行在 `factorio-net` 网络
- Factorio job 容器通过 bundle 的 `extra_networks` 加入该网络
- Job 容器不加入 `yoitsu-dev` pod（`pod_name: null`）
- Save 文件持久化在 `factorio-saves` volume

Server 可挂载稳定的 host checkout 提供基准脚本，但 **不依赖该 mount 作为同步路径**——per-job 脚本同步由 `call_script` 工具动态完成。

### D7. Publication = Git + World Save

Factorio publication 涉及两个 capability finalize：

**git_workspace capability finalize**（目标仓库）：

```python
def finalize(self, ctx: JobContext) -> FinalizeResult:
    events = []
    success = True
    
    # Hallucination gate
    subprocess.run(["git", "add", "-A"], cwd=ctx.target_workspace)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ctx.target_workspace)
    if result.returncode == 0:
        # Worker 无变更 = hallucination = 失败
        events.append(EventData(type="publication.skipped", data={"reason": "no_changes"}))
        return FinalizeResult(events=events, success=False)  # success=False
    
    # 重试 push
    MAX_RETRIES = 3
    sha = None
    for attempt in range(MAX_RETRIES):
        try:
            subprocess.run(["git", "commit", "-m", f"job: {ctx.job_id}"], cwd=ctx.target_workspace)
            sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ctx.target_workspace)
            subprocess.run(["git", "push"], cwd=ctx.target_workspace, check=True)
            # Artifact URI 指向远端仓库
            events.append(EventData(type="artifact.published", data={
                "ref": f"{ctx.target_source.repo_uri}@{sha.strip()}",  # 远端 URI
                "relation": "workspace_output"
            }))
            return FinalizeResult(events=events, success=True)
        except subprocess.CalledProcessError as e:
            if attempt < MAX_RETRIES - 1:
                continue
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "push",
                "error": str(e),
                "local_commit_sha": sha.strip() if sha else None,
                "artifact_persisted": False
            }))
            success = False
    
    return FinalizeResult(events=events, success=success)
```

**factorio_save capability finalize**（世界状态）：

```python
def finalize(self, ctx: JobContext) -> FinalizeResult:
    events = []
    success = True
    
    bridge = ctx.resources.get("rcon_bridge")
    if not bridge or not bridge.world_mutated:
        # 未变更世界，跳过 save（不影响 success）
        events.append(EventData(type="save.skipped", data={"reason": "no_mutation"}))
        return FinalizeResult(events=events, success=True)  # 不影响 job 终态
    
    MAX_RETRIES = 2
    for attempt in range(MAX_RETRIES):
        try:
            save_result = bridge.save_world()
            if save_result.success:
                events.append(EventData(type="artifact.published", data={
                    "ref": f"file://{save_result.save_path}",
                    "relation": "world_checkpoint"
                }))
                return FinalizeResult(events=events, success=True)
            else:
                if attempt < MAX_RETRIES - 1:
                    continue
                events.append(EventData(type="finalize.failed", data={
                    "capability": self.name,
                    "stage": "save_world",
                    "error": save_result.error,
                    "artifact_persisted": False
                }))
                success = False
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                continue
            events.append(EventData(type="finalize.failed", data={
                "capability": self.name,
                "stage": "save_world",
                "error": str(e),
                "artifact_persisted": False
            }))
            success = False
    
    return FinalizeResult(events=events, success=success)
```

**关键点**：

- 两个 finalize 互不依赖，各自返回 `(events, success)`
- Runtime 检查所有 capability 的 `success`，任一 False → `job.failed`
- 如果 git_workspace 成功但 factorio_save 失败，job 终态为 `failed`
- 事件记录详细诊断信息，供后续分析

### D8. 并发控制通过 Bundle 配置

`max_concurrent_jobs: 1` 在 bundle 的 scheduling 配置中声明，Trenni 将其转化为 job launch condition：

```
running_count(bundle="factorio") < 1
```

这保证了：
- 同一时间只有一个 factorio job 运行（跨所有 roles）
- 额外的 factorio jobs 在队列等待
- Default bundle 的 jobs 不受影响
- Scheduler 不感知 "factorio" — 只评估 condition

**初始策略**：并发限制应用于**所有 factorio jobs**，包括 planner 和 evaluator。世界是共享可变状态，即使"只读"操作在 worker 变期间也可能观察到不一致的中间状态。

### D9. Role 定义示例

```python
# factorio-bundle/roles/worker.py
metadata = RoleMetadata(
    name="worker",
    needs=["rcon_bridge", "git_workspace", "factorio_save"],
    contexts=["factorio_scripts", "task_history"],
    tools=["bash", "spawn", "call_script"],
)

@role(metadata)
def factorio_worker(**params) -> JobSpec:
    return JobSpec(
        provider=default_provider(),
        budget=params.get("budget", 0.50),
    )
```

```python
# factorio-bundle/roles/planner.py
metadata = RoleMetadata(
    name="planner",
    needs=["rcon_bridge"],  # planner 也需要 RCON（只读查询）
    contexts=["factorio_scripts", "task_history"],
    tools=["bash", "spawn"],
)
```

```python
# factorio-bundle/roles/evaluator.py
metadata = RoleMetadata(
    name="evaluator",
    needs=["rcon_bridge"],  # evaluator 查询世界状态
    contexts=["factorio_scripts", "evaluation_criteria"],
    tools=["bash", "call_script"],
)
```

### D10. Observation Analyzer 示例

```python
# factorio-bundle/observations/rcon_timeout.py
class RconTimeoutAnalyzer:
    name = "rcon_timeout"
    
    def analyze(self, job_events: list[Event]) -> list[ObservationData]:
        timeouts = [e for e in job_events 
                    if e.type == "tool.result" 
                    and e.data.get("tool") == "call_script"
                    and e.data.get("error_type") == "rcon_timeout"]
        
        if len(timeouts) >= 3:
            return [ObservationData(
                type="observation.rcon_timeout",
                data={
                    "count": len(timeouts),
                    "scripts": [t.data.get("script_name") for t in timeouts],
                    "pattern": "repeated_timeout"
                }
            )]
        return []
```

Analyzer 在 bundle repo 中定义，随 bundle 演化。版本定格规则见 ADR-0017 §2g。

## Verification

新架构的验证点：

1. ✅ Trenni 注册 factorio bundle，`resolved_ref` 从 selector 解析
2. ✅ Factorio job 容器能通过 `factorio-net` 访问 server
3. ✅ `call_script("ping", {})` 从 worker job 成功执行
4. ✅ Target workspace 中编辑的脚本能通过 `call_script` 同步到 server
5. ✅ `RoleManager.resolve("worker", bundle="factorio")` 返回 factorio worker role
6. ✅ 两个 factorio jobs 不能并发运行 — 第二个在队列等待
7. ✅ Worker job 变更世界后，finalize 成功返回 `success=True`，emit `artifact.published` (git + save)
8. ✅ Git push 失败时返回 `success=False`，emit `finalize.failed`，job 终态 `failed`
9. ✅ Hallucination（无变更）时返回 `success=False`，job 终态 `failed`
10. ✅ Artifact URI 指向远端仓库（如 `git+https://github.com/org/repo@sha`），不是 ephemeral workspace
11. ✅ Observation analyzer 用 job 的 resolved_ref 版本执行分析
12. ✅ Review task 携带 `triggered_by` 因果链
13. ✅ `analyzer_version` 包含三方 SHA（bundle_sha + trenni_sha + palimpsest_sha）

## 对旧 ADR-0012 的修正

| 旧概念 | 新模型 | 说明 |
|---|---|---|
| Team `factorio` | Bundle `factorio` | Team 概念被 Bundle 取代 |
| `evo/teams/factorio/` | `factorio-bundle.git` | 独立仓库，不再是 palimpsest 子目录 |
| `preparation_fn` | Capability `setup()` | 生命周期管理标准化 |
| `publication_fn` | Capability `finalize()` | Git + Save 分别为独立 capability |
| `runtime_context.resources` | Capability 注入 | 资源管理由 capability 负责 |
| `TeamRuntimeConfig` | Bundle `runtime` 配置 | 配置归属迁移 |
| `teams.factorio.max_concurrent_jobs` | `bundles.factorio.scheduling.max_concurrent_jobs` | 并发控制归属迁移 |

## Implementation Sequence

```
ADR-0015 Phase 1: Bundle resolver + registry + ephemeral workspace
    ↓
ADR-0016 Phase 1: Capability Protocol + runtime 调用框架
    ↓
ADR-0012 Phase 1: Factorio bundle repo 初始化 + capabilities 实现
    ↓
ADR-0012 Phase 2: RCON bridge + call_script + roles
    ↓
ADR-0012 Phase 3: Observation analyzer + 累积触发验证
    ↓
Factorio 闭环 smoke test
```
