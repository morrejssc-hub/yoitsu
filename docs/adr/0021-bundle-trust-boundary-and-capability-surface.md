# 0021: Bundle Trust Boundary and Capability Execution Surface

- Status: Proposed
- Related: ADR-0015, ADR-0016, ADR-0018
- Supersedes: ADR-0019 (Suspended)

## 1. 现状与存在的问题

ADR-0015 已经确立 bundle 是代码级可演化的任务扩展单元，ADR-0016 确立 capability 是 runtime 生命周期的标准模型，ADR-0018 进一步把 role 生命周期收敛到单一 capability 路径。但在把 factorio 一类带有 live runtime 副作用的 bundle 迁入该模型时，暴露了四个此前未被单独处理的问题：

1. **Bundle 的自由演化面 与 非隔离环境准备面 共享同一份代码**：bundle 里既有可以在隔离容器中跑的 agent-loop 侧逻辑，也有必须在 Trenni（控制面）侧跑才能完成的挂载、端口放通、外部连接 preflight。这些职责当前没有显式的边界。
2. **Bundle 的代码演化速度 与 控制面信任边界 存在张力**：evolve 分支希望快速迭代，但控制面代码天然要求人工审核与稳定性。两者绑在单一 ref 上，要么拖慢 evolve，要么放弃控制面审核。
3. **ADR-0019 的 `output_authority` 越界**：它被写成“role 的输出权威归属”，但实现上只是 runner 的工作区路由字段。这在表述上与“event store 是唯一真实来源”的原则相悖（参见 ADR-0020）。
4. **控制面挂载 topology 实际由 Trenni 决定，不由 capability 决定**：当前 bundle workspace 与 target workspace 的准备发生在 job 容器启动前，capability 的 `setup/finalize` 都跑在 job 内部。这个事实在 ADR-0016/0018/0019 中都没有被显式建模。

本 ADR 的目标是给出这四个问题的统一解：**把"在哪个进程/容器里跑"和"用哪个被审核版本"建模为两个正交的轴**，并据此重新定位 capability、bundle ref 和控制面的关系。

## 2. 做出的决策与原因

### 2a. Bundle 采用双 ref 信任模型

每个 bundle 仓库提供两个语义不同的 ref：

1. **evolve ref**：自由演化面。optimizer 与相关 agent 可以直接 push，供 Palimpsest job 容器加载。它只用于 job-side 执行。
2. **master ref**：控制面信任面。只接受通过 PR review 的变更。Trenni 只从这个 ref 加载控制面代码。

evolve 上允许存在控制面代码的候选版本（便于 bundle 作者在 evolve 上预演），但 Trenni 永远不会从 evolve 加载任何东西。

**原因**：把"自由演化"与"控制面信任"映射到已有的 git branch + PR 原语，避免引入新的信任分类或白名单机制。bundle 仍然是扩展的基本单位，但其对控制面的扩展受 PR 门控。

### 2b. Capability 通过 `surface` 装饰器声明执行面

Capability 在定义时必须显式声明 surface：

```python
@capability(surface="control_plane", name="factorio_mount")
class FactorioMount: ...

@capability(surface="job_side", name="factorio_runtime")
class FactorioRuntime: ...
```

合法取值：

1. **`control_plane`**：在 Trenni 侧以子进程形式运行，负责挂载解析、端口放通、外部连接 preflight、runtime attach/detach。
2. **`job_side`**：在 Palimpsest job 容器内运行，负责 finalize、局部同步、资源收尾等容器内工作。

surface 是 capability 的固有属性，在定义处完成分类，不在 role 声明处决定。

**原因**：让每个 capability 的运行位置在代码中显式，避免"同一个 `setup()` 跑在哪个进程"这种隐式歧义。同时保持单一 `capabilities/` 目录，bundle 作者不需要维护多份代码或多份目录布局。

### 2c. Control-plane capability 以子进程形式运行

Trenni 不直接 `import` bundle 的 Python 模块到主进程，而是：

1. 在 `master@<switched_sha>` 检出处启动一个短生命周期的子进程
2. 子进程加载 bundle 的 `capabilities/` 目录，只执行标记为 `surface="control_plane"` 的 capability
3. 子进程通过 stdin/stdout（或等价结构化通道）返回结果与事件
4. 结果事件由 Trenni 主进程落入 event store

**原因**：

1. **进程级崩溃隔离**：bundle 控制面代码的 bug 不会拖挂长驻 Trenni。
2. **资源与时长可控**：子进程天然支持 cgroup、ulimit、超时。
3. **审计边界清晰**：stdin/stdout 的 frame 就是天然的事件化点，所有控制面动作可以被完整记录。
4. **避免 long-lived import 污染**：不同 bundle / 不同版本之间不会共享 Python import cache 或全局状态。

即便 master 已经过 PR review，子进程边界作为深度防御仍然有价值。

### 2d. Master ref 的切换由显式事件驱动

Trenni 不主动 watch git ref，也不在 PR merge 时自动生效。切换路径固定为：

1. Optimizer 向 master 提交 PR
2. PR 通过 review 被合并
3. 触发 `BundleControlPlaneVersionProposed(bundle, sha)` 事件
4. Operator（或受控自动化）发出 `BundleControlPlaneSwitched(bundle, sha)` 事件
5. Trenni 消费 `BundleControlPlaneSwitched` 后，下一次 job 启动时使用新 sha 的子进程

"合并 ≠ 上线"——切换事件是独立决策，落在 event store。

**原因**：

1. 保持 event store 作为唯一真值来源：控制面版本变更也是事件，不依赖对 git 的带外观察。
2. 合并与切换解耦：允许在合并与生效之间插入人工判断、金丝雀、回滚窗口。
3. 回滚对称：回滚就是再发一条 `BundleControlPlaneSwitched` 指向旧 sha，不需要 force push 或 rebase。
4. 可审计：谁在什么时候切到哪个 sha 全部落事件。

本 ADR 不规定 `BundleControlPlaneSwitched` 事件的权限模型（谁有权发），这部分留给后续单独设计，见 §6 未决问题。

### 2e. `surface` 与 ref 是两个正交轴

两者联合决定一次 job 的总行为：

| 轴 | 决定什么 | 载体 | 节奏 |
| --- | --- | --- | --- |
| **surface** | 在哪个进程/容器里跑 | capability 装饰器 | 代码期决定 |
| **trust ref** | 用哪个被审核版本 | git ref (evolve / master) | 运行期决定 |

派发规则：

- `surface="control_plane"` → Trenni 端 subprocess，从 `master@<switched_sha>` 加载
- `surface="job_side"` → Palimpsest job 容器内，从 `evolve@<job_bundle_sha>` 加载

每次 job 由两个 sha 组合唯一确定：`(control_plane_sha, job_bundle_sha)`。smoke 与复现性都基于这两个 sha 固定。

**原因**：两个轴独立演进符合它们的风险特征——job-side 可以每次 job 换（evolve 自由），control-plane 只在显式切换时变（master 稳定）。合并成一个轴会强制两者同速，违背其原本诉求。

### 2f. Job-side capability 的默认 ref 与 job 的 bundle_ref 一致

Job 启动时 Trenni 挂入容器的 bundle workspace，其 ref 由 job 的 `bundle_ref` 字段决定（通常是 evolve 的某个 sha）。Palimpsest 在容器内只加载 `surface="job_side"` 的 capability，且仅从该 ref 加载。

Palimpsest **不会**尝试访问 master ref。控制面 capability 对 job 容器完全不可见。

**原因**：保持最小可见性——job 容器只能看到它被明确授权使用的版本，控制面代码及其 sha 对任务执行面不暴露。

### 2g. ADR-0019 的 `output_authority` 字段暂停生效

在本 ADR 被接受后：

1. `output_authority` 字段保留在 role metadata 中不再承载任何语义。
2. runner 的工作区路由改由 role 的 `needs`（即声明的 capability 集）隐式决定：声明了 `control_plane` surface capability 的 role 在其 setup 阶段会获得 Trenni 准备好的挂载；job 内部的 cwd 由 job-side capability 的 setup 返回值决定（见 ADR-0016 §2a 的 emit-data 模式）。
3. ADR-0019 文档转入 Suspended 状态，不作为当前架构的一部分引用。

**原因**：`output_authority` 试图把"在哪里写"与"谁负责真值"两件事混为一个字段，但前者属于执行表面（由本 ADR 的 surface + ref 模型承接），后者属于真值模型（由 event store 唯一承担，参见 ADR-0020）。拆开之后，该字段已无独立职责。

## 3. 期望达到的结果

- Bundle 作者能在单一 `capabilities/` 目录里用装饰器显式标注每段代码的执行面，不需要维护多份目录或多份配置。
- 自由演化（evolve）与控制面信任（master）两种诉求可以独立演进，互不阻塞。
- Trenni 主进程不会因为加载 bundle 代码而扩大攻击面或承担 bundle bug 的崩溃风险。
- 控制面版本变更可以独立于代码合并被调度、审计和回滚。
- smoke test 的结果由 `(control_plane_sha, job_bundle_sha)` 二元组唯一决定，便于复现与定位。
- ADR-0019 在概念上被替换为执行表面 + 真值模型的干净二分，不再承担"输出权威"这一越界表述。

## 4. 容易混淆的概念

- **surface 不是 authority**
  - surface 只决定"在哪个进程里跑"，不决定"谁是真值来源"。
  - 所有事实——工具是否被调用、capability 是否完成、外部 runtime 是否生效——仍然只能由事件证明。

- **master 不是 production，evolve 不是 dev**
  - master 是"控制面信任版本"，评估点是"是否经过人工 review"。
  - evolve 是"自由演化面"，评估点是"是否能在隔离容器里跑起来"。
  - 它们不是部署环境分级。

- **PR 合并 ≠ 控制面切换**
  - PR 合并只改变 master ref，不改变 Trenni 正在使用的 sha。
  - Trenni 使用的 sha 由 `BundleControlPlaneSwitched` 事件决定，与合并独立。

- **子进程隔离 ≠ 容器隔离**
  - 控制面子进程仍与 Trenni 共享 host kernel 与文件系统权限。
  - 子进程提供的是进程/资源/崩溃/import-cache 隔离，不是安全沙箱。
  - 安全边界仍由 PR review 与 master ref 本身提供。

## 5. 对之前 ADR 或文档的修正说明

- **ADR-0015（Bundle as Repo）**：继续有效。本 ADR 在其基础上补充了"bundle 仓库至少提供 evolve / master 两个语义不同 ref"的约定。
- **ADR-0016（Capability Model）**：继续有效。本 ADR 为 capability 协议增加必填字段 `surface`，取值 `control_plane` 或 `job_side`。
- **ADR-0018（Capability-Only Role Lifecycle）**：继续有效。本 ADR 明确 Trenni 侧的 control_plane capability 执行发生在 ADR-0018 §2a 描述的生命周期**之前**（job 容器启动前的准备阶段），不破坏 capability-only 的统一生命周期断言。
- **ADR-0019（Role Output Authority）**：Suspended。字段 `output_authority` 保留但无语义，工作区路由由本 ADR 的 surface + ref 模型承接。
- **ADR-0020（Reconciled Job Terminal State）**：继续有效。本 ADR 明确重申：surface 不是真值来源，终态解释仍由 ADR-0020 的多层事件重建完成。
- **文档 `docs/archive/notes/2026-04-14-execution-surface-and-control-plane-capabilities.zh-CN.md`**：本 ADR 是该讨论纪要的正式收敛，与其中"引入 control-plane capability"的方向一致，但放弃了"白名单 / built-in only"的约束，改用 git ref + PR 作为信任边界。

## 6. 未决问题

以下问题本 ADR 不给出答案，留待后续设计：

1. **`BundleControlPlaneSwitched` 事件的权限模型**：谁有权发、如何签名、如何防止伪造。一种候选是 operator-only + 事件签名；另一种是通过受控自动化 agent 经由特定入口发布。
2. **子进程通信协议的具体形态**：是 JSON-RPC、是结构化日志行、还是 capability SDK 抽象。需要结合 Palimpsest 已有的 tool 装饰器模式一起设计。
3. **控制面子进程的资源策略**：超时、内存上限、并发度、失败重试语义。
4. **现有 built-in capability 是否需要暴露 `surface="control_plane"` 分支**：例如 `git_workspace` 的 clone 是否该迁移到控制面子进程里跑，而不是由 Trenni 直接执行。
5. **evolve 上若包含未 promote 的 control_plane capability 定义，如何告警或禁用**：避免 bundle 作者误以为 evolve 修改会立即生效。
6. **factorio_runtime 的具体拆分方案**：作为 canonical example，单独落一份实现 runbook。

## 7. 一句话总结

**surface（装饰器）决定 capability 在哪里跑；ref（git）决定用哪个被审核版本；两者正交，通过子进程与事件驱动切换把 bundle 的自由演化面和控制面信任面干净切开。**

---

## 附录 A：MVP 接口合同

以下合同是本 ADR §2 决策的具体落地形态，属于"已决但未在正文展开"的实现细节。

### A.1 控制面 capability 沿用 ADR-0016/0018 的 setup/finalize 方法名

控制面 capability 不引入新协议，沿用现有 Capability 协议：

- **`setup(ctx)`**：在 job 容器启动前由 Trenni 子进程调用。返回 `FinalizeResult(events, success)`。
- **`finalize(ctx)`**：在 job 容器退出后由 Trenni 子进程调用。返回 `FinalizeResult(events, success)`。

setup 返回值中的 `events` 由 Trenni 主进程落入 event store；`success=false` 会导致 Trenni 取消本次 job 启动。

finalize 返回值中的 `events` 同样落入 event store；`success=false` 会被 ADR-0020 的多层终态解释纳入考量。

### A.2 needs 列表两侧各自按 surface 过滤

role 声明 `needs=["factorio_mount", "factorio_runtime"]` 时：

- Trenni 从 bundle 的 capabilities 目录加载所有 capability，**只执行 `surface="control_plane"` 的 setup/finalize**。
- Palimpsest 同样从 bundle 的 capabilities 目录加载，**只执行 `surface="job_side"` 的 setup/finalize**。

role 作者不感知 surface，只声明自己需要哪些能力。surface 是 capability 定义处的固有属性。

### A.3 子进程通信协议采用 JSON lines over stdin/stdout

Trenni 与控制面子进程之间的通信协议：

- **输入帧**（父 → 子）：`{"op": "setup"|"finalize", "capability": "<name>", "context": {...}}`
- **输出帧**（子 → 父）：`{"ok": true|false, "events": [...], "success": bool}`

一个子进程处理一个 bundle 的一次 job 的所有控制面 capability（单次 fork，多次帧）。子进程退出标志着 finalize 结束。

stderr 透明转发到 Trenni 日志，不参与协议。

### A.4 Master ref 物化采用 git worktree

Trenni 为每个 bundle 维护一个本地 bare clone（如 `~/trenni/bundles/<name>.git`）。

每次 job 启动前：
1. 从 bare clone `git worktree add <tmpdir> <switched_sha>`
2. 子进程 cwd 设在该 worktree
3. job 完成后 `git worktree remove <tmpdir>`

性能优化（sha 复用 cache）不进 MVP。

### A.5 切换事件 schema 与 bootstrap

contracts 新增两个事件类型：

```
BundleControlPlaneVersionProposed:
  bundle: str
  sha: str
  proposed_by: str     # optimizer / ci
  merged_at: datetime
  pr_ref: str | None

BundleControlPlaneSwitched:
  bundle: str
  sha: str
  switched_by: str     # operator id / automation id
  reason: str          # "initial bootstrap" / "rollback to <sha>"
```

Bootstrap：Trenni 启动时，对每个已注册 bundle，若 event store 中无 `BundleControlPlaneSwitched` 事件，**拒绝启动涉及该 bundle 的 job**，并日志提示 operator 发送初始切换事件指向当前 master HEAD。

权限：通过 Pasloe 的 source 级别 key 控制（不阻塞本 ADR）。

### A.6 output_authority 字段直接删除语义

不保留过渡路径。`output_authority` 参数在 role decorator 中保留（向后兼容不报错），但 runner 不再读取。

runner 的 cwd 选择改由 capability setup 返回值决定：
- 声明 `surface="job_side"` capability 的 role，由该 capability 的 setup 返回值中的 `cwd` 字段决定。
- 无任何 capability 的 role，沿用 ADR-0018 的 ephemeral 临时目录。
- **`bundle_workspace as cwd` 的历史捷径删除**——想写 bundle 的 role 必须通过 capability 声明 cwd。

### A.7 Built-in capability 全部迁移到 bundle

删除 `BUILTIN_CAPABILITIES` 字典（当前包含 `git_workspace` 和 `cleanup`）。

每个 bundle 必须自行提供所需的 capability 实现。bundle example（如 `factorio-bundle`）提供参考实现供新 bundle 作者复制使用。

这消除了"默认 capability"与"bundle 扩展 capability"之间的优先级歧义，让 capability 来源唯一指向 bundle。

### A.8 控制面子进程的资源策略（MVP 默认值）

- 超时：300 秒（setup + finalize 总时长）
- 内存：不限（受 host ulimit 约束）
- 并发度：单 bundle 单 job = 单子进程（无并发控制面）
- 失败重试：不重试。setup 失败取消 job；finalize 失败记录事件，终态解释由 ADR-0020 处理。

后续可根据实际负载收紧。

---

## 附录 B：§6 未决问题的更新状态

原 §6 列出的六个未决问题，经附录 A 合同确定后，状态如下：

| # | 原问题 | 状态 | 解决位置 |
|---|--------|------|----------|
| 1 | `BundleControlPlaneSwitched` 权限模型 | 已决 | A.5（Pasloe source key） |
| 2 | 子进程通信协议形态 | 已决 | A.3（JSON lines） |
| 3 | 控制面子进程资源策略 | 已决 | A.8（MVP 默认值） |
| 4 | built-in capability 是否暴露 control_plane | 已决 | A.7（全部迁移到 bundle） |
| 5 | evolve 上未 promote 的控制面代码告警 | 未决 | 暂不处理，靠 code review |
| 6 | factorio_runtime 拆分 runbook | 未决 | 作为 plan 的执行产物 |

附录 B 标注的"未决"项不阻塞 MVP 实现。
