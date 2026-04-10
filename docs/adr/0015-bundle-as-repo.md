# 0015: Bundle 即独立 Git 仓库（取代独立 Artifact Store）

## 1. 现状与存在的问题

Copy-modify-publish 设计在 Factorio 闭环 smoke test 的反复迭代中暴露出一个根本问题：每一次尝试把新能力放进 ADR-0013 定义的独立 Artifact Store，最终都在重新发明 git 已经提供的机制（内容寻址、原子 publish、历史、回滚、分发）。同时 `TODO-bundle-isolation.md` 明确把 "bundle manifests" 与 "multi-repo bundle distribution" 列为 Not In Scope，但 Factorio 闭环把这两件事推到了必须处理的地步。具体矛盾有三：

1. **Implementer 写入路径无法审计**：当前 `workspace_override` bind mount `evo_root` RW，没有版本、没有校验、LLM 可以声称完成却未实际调用工具（smoke test 报告实验 2）。
2. **大状态无法塞进 Event Store**：完整 git 仓库或 Factorio save 存档都不可能以事件 payload 形态落入 Pasloe。ADR-0013 设想的"Artifact Store 作为双真实源之一"在 code-like 场景里永远和 git 重合，在 binary 场景里必然走外部引用，这个二元性让统一抽象无法自洽。
3. **`evo` 作为 palimpsest submodule 是全量时代的遗产**：当年 palimpsest = 演化系统本体，evo = 它的数据。bundle 概念出现后，palimpsest 降级为通用 runtime，但 evo 仍挂在它下面，职责严重错位。

## 2. 做出的决策与原因

**决策**：**Artifact Store 不作为独立子系统存在**；**git 是 code-like 产物的原生权威后端**；**每个 bundle 是独立 git 仓库**；**Event Store 通过 URI 引用一切外部大对象**。

### 2.1 Event 承载 URI 引用，不建统一 Store

Event 的外部引用字段是字符串 URI，按 scheme 分辨解引用方式：
- `inline:` / 直接在 payload 里 — 小数据（观察事件、job metadata）
- `file://<path>` — pasloe 持久卷中的裸文件（Factorio save、日志归档）
- `git+<remote>@<sha>` — code-like 产出（scripts、prompts、role 代码、bundle 定义本身）
- `http(s)://` — 外部只读资源（文档、数据集、mod 下载源）

Event Store 只保证 "**我忠实记录了你声明过的引用**"，**不**负责内容持久化、**不**解引用、**不**验证引用背后的字节仍然可达。持久化保证属于各 scheme 背后的系统（git 托管、文件系统、HTTP 源）。

### 2.2 Git 是 code-like 产物的原生后端

任何 text/source 形态的 artifact 都走 git。Copy-modify-publish 的具体映射：
- **checkout** = `git clone --depth 1 <bundle_remote>@<sha>` 到 ephemeral workspace
- **modify** = agent 在 workspace 内自由改文件
- **publish** = `git add -A`；若 `git diff --cached --quiet` 为真则 publication 失败；否则 `git commit && git push`
- **版本 / 历史 / 回滚 / 分发** = git 原生能力

**Hallucination gate 是 `git diff` 的硬规则**：staging 非空即 commit；staging 为空即 publication 报错。不做 whitespace 过滤、不做语义判断。"变更是否解决了 goal" 由 evaluator role 独立回答。

### 2.3 每个 bundle 是独立 git 仓库

`evo/` 作为 palimpsest 内部目录的角色被废除。每个 bundle 是一个自包含的 git 仓库：

```
factorio-bundle/
├── bundle.yaml     # 元数据 + 声明式 artifacts
├── capabilities/   # setup + finalize 生命周期管理（ADR-0016）
├── roles/          # role 定义（声明 needs + contexts）
├── tools/          # bundle 私有工具（palimpsest runtime 加载）
├── contexts/       # context provider（LLM 上下文组装）
├── observations/   # observation analyzer（注册到 Trenni，ADR-0017）
├── prompts/        # prompt 文件
├── scripts/        # bundle 私有代码（role 执行时引用）
├── lib/            # 共用工具库
└── examples/       # 可选示例
```

其中 `roles/` `tools/` `contexts/` 为 runtime 强依赖的最小必需集合；`capabilities/` `observations/` 为本次架构重构新增的标准目录（参见 [ADR-0016](0016-capability-model.md)、[ADR-0017](0017-observation-unified-interface.md)）；`prompts/` 为默认约定目录；`scripts/` `lib/` `examples/` 为 bundle 自主决定的扩展空间。

Trenni 在现有 `bundles` 配置下为每个 bundle 增加 `source` 字段，用于指向该 bundle 的远端仓库与 ref（完整示例见 §2.7）。Trenni 允许**同时注册多个 bundle**，每个 bundle **独立演化**——没有中央 base 仓库、没有 submodule、没有 monorepo。

Palimpsest 不再持有 "evo 在哪" 的全局概念，但仍然通过 `BundleSource` 结构（§2.7）**知道当前 job 的 workspace 物化在何处**——workspace 路径由 trenni 在派发前准备好并通过 JobConfig 传入。Palimpsest 的关注范围从"在 evo 树里定位 bundle"压缩为"在指定的 workspace 里加载 roles/tools/contexts"。

### 2.4 Bundle 作为"任务类工具包"，声明与 ad-hoc 引用并存

`bundle.yaml` 的 `artifacts` 字段做**静态声明**（例如 Factorio save 模板、mod git URL、外部数据集），供 trenni 启动期建立索引与依赖校验。但 role 运行时仍然可以 emit **未声明的 URI 引用**——两者在 event schema 上没有区别，都是 `artifact.published` 事件里的 ref 字段。

区别只在可发现性：声明的可静态列出和 lint；未声明的只能通过事件流回溯。这让 bundle schema 呈现"接近封闭但允许溢出"的语义。

### 2.5 Publication 的三层职责分工

publication 阶段承担两类检查，evaluator 承担第三类，三者正交：

1. **变更存在性 gate（hallucination gate）**：`git diff --cached --quiet` 为真即 publication 失败。它只回答"agent 是否真的改了文件"。不做 whitespace 过滤、不做语义判断。这是 ADR-0015 强制引入的最小门槛。
2. **结构可接受性 gate（guardrail）**：bundle/role 可声明的 publication-time 检查，例如 Lua 语法校验、路径白名单、禁止修改某些受保护文件、Factorio DYNAMIC 脚本约束。相当于当前 `palimpsest/palimpsest/stages/finalization.py` 里的 guardrail 职责在新模型里的继承者。这层**允许**被 bundle 扩展，但默认只有 (1)。
3. **目标达成语义判断**：由 evaluator role 在独立 job 中回答"这批 commit 是否解决了 goal"。不在 publication 链路上。

三层的拆分解除了 smoke test 中 evaluator 同时承担"文件是否存在"和"goal 是否达成"两种性质不同的检查所导致的职责缠绕。(1)(2) 由 publication 在 commit 之前 gatekeep；(3) 只能在 commit 发生后以 read-only 方式评估。

### 2.6 Fresh start，不迁移历史

当前 `palimpsest/evo/factorio/` 的 git 历史在 bundle-as-repo 模型下无法无缝延续（submodule 边界、路径前缀、权限模型都变了）。且 Factorio 闭环 smoke test 尚未跑通，历史中没有值得保留的演化成果。**新的 factorio-bundle 仓库从空白初始化**，现有 `evo/factorio/` 的内容以单个"初始提交"形式导入。

### 2.7 Contract Migration（旧字段的去处）

本 ADR 要求对 `yoitsu-contracts` 中的若干字段做结构性替换。具体替换关系如下，细节（字段名终态、是否保留兼容别名）由 Phase 1 落地计划决定，但**替换方向**在本 ADR 拍板：

| 旧概念 | 去处 | 说明 |
|---|---|---|
| `evo_root`（JobConfig / runtime） | 废除 | 取代物是 `bundle_source.workspace` —— trenni 在派发 job 前准备好的 ephemeral clone 绝对路径 |
| `evo_sha`（JobConfig / event） | 废除 | 取代物是 `bundle_source.resolved_ref` —— 该 job 物化时 checkout 的 bundle repo commit sha（由 trenni 从 selector 解析得到） |
| `workspace_override`（WorkspaceConfig） | 整体废除 | 不再允许 bind mount 任何 live 树；workspace **总是** ephemeral clone |
| `ArtifactBinding`（ref/relation/path/metadata） | 形态保留，语义改写 | `ref` 从 artifact store 内部地址改为 URI 字符串（§2.8）；`path` 继续表示"ref 内部子路径"（仅对容器型 ref 有意义）；`relation` `metadata` 不变 |
| `ArtifactRef` / `LocalFSBackend` / `Blob` / `Tree` | 废除 | 独立 artifact store 模块整体退役，相关测试与调用点随 Phase 1 清理 |

新增一个 `BundleSource` 结构承载"该 job 的 bundle 身份 + 物化位置"，形如 `{name, repo_uri, selector, resolved_ref, workspace}`：

- `name`：稳定的逻辑身份（例如 `"factorio"`），用于和 `TrenniConfig.bundles[name]` 做运行时/调度查找
- `repo_uri`：bundle 仓库的远端地址（`git+file://` / `git+ssh://` / `git+https://`）
- `selector`：registry 配置中声明的分支名或 tag 名（如 `evolve`、`main`、`v1.2.3`），**由人类或 bundle owner 在配置时指定**
- `resolved_ref`：trenni 从 selector 解析出的 commit sha，是本次 job 实际 checkout 的固定快照
- `workspace`：trenni 在本机物化出来的 ephemeral 目录绝对路径

**selector 与 resolved_ref 的分工**：selector 是"意图声明"（我想用 evolve 分支的最新状态），resolved_ref 是"执行定格"（实际 checkout 了 sha a1b2c3d）。resolved_ref 由 trenni 在派发 job 前**动态解析**，保证可复现性。

**Trenni registry 采用按 name 键控的结构**，而不是裸 URL 列表。§2.3 的 YAML 示例应被理解为如下形态（具体字段名以 Phase 1 落地为准）：

```yaml
bundles:
  factorio:
    source:
      url: "git+file:///home/holo/bundles/factorio-bundle.git"
      selector: evolve    # 分支名或 tag 名，由 trenni 解析成 commit sha
    runtime: { ... }          # 现有 runtime 配置结构保持
    scheduling: { ... }       # 现有 scheduling 配置结构保持
  webdev:
    source:
      url: "git+ssh://git@github.com/.../webdev-bundle.git"
      selector: main
```

字段 `selector` 允许使用分支名（如 `evolve`、`main`）或 tag 名（如 `v1.2.3`）；trenni 在派发 job 时将其解析为实际 commit sha 并填入 `BundleSource.resolved_ref`。

这样可以和当前 `TrenniConfig.bundles: dict[str, BundleConfig]` 的心智模型对齐，避免 registry 引入第二套 bundle 身份体系。

### 2.8 URI 合同

URI 是外部引用的**唯一**表达形式。本 ADR 只定义 scheme 集合和子路径语法，具体解析库与缓存策略留给 Phase 1。

**Scheme 集合**（Phase 1 最小必需）：

- `inline:` — 保留标识位；小数据直接走 event payload 的领域字段，不必真的构造 `inline:` URI
- `file:///<absolute-path>` — pasloe 持久卷内的裸文件（Factorio save、日志归档）；可达性由文件系统保证
- `git+file://<path>@<ref>[#<subpath>]` — 本机 bundle/仓库快照
- `git+ssh://<host>/<path>@<ref>[#<subpath>]` — 远端 bundle/仓库快照（SSH 鉴权）
- `git+https://<host>/<path>@<ref>[#<subpath>]` — 远端 bundle/仓库快照（HTTPS 鉴权）
- `http(s)://<host>/<path>` — 外部只读资源（文档、数据集、mod 下载源）

**子路径语法**：`git+*` scheme **必须**支持 `#<subpath>` 尾缀，用于指向仓库内某个具体文件或目录。例如：

- `git+file:///home/holo/bundles/factorio-bundle.git@a1b2c3d#prompts/worker.md` — 指向特定 commit 下的 worker prompt 文件
- `git+ssh://git@github.com/holo/factorio-bundle.git@a1b2c3d#scripts/place_entity.lua` — 指向特定 commit 下的脚本

`@<ref>` 必须是 commit sha 或 tag，**不允许**使用分支名（分支名非固定会破坏可复现性）。`#<subpath>` 为可选——未指定时引用整个仓库快照。

**Event Store 的承诺**：它忠实记录 URI 字符串，保证该字符串在时刻 t 被声明过，**不**解析、**不**拉取、**不**校验字节可达性。内容权威由 URI scheme 背后的系统各自承担（git 托管、文件系统、HTTP 源）。

### 为什么选这个方向

1. Git 已经成熟地提供了 ADR-0013 试图重新发明的全部核心能力
2. "code-like" 与 "binary-like" 产物的访问模式、修改模式、持久化模式彻底不同，强行统一抽象从一开始就是错的；URI scheme 是这个异质性的正确承载层
3. Bundle 作为"任务类工具包"的语义天然对应一个独立仓库：代码、prompt、数据、演化历史同生共死
4. 依赖外部 git 托管（GitHub 等）消除 pasloe 侧自建对象存储的压力，也让 bundle 在主机间的迁移变成 `git clone` 一条命令

## 3. 期望达到的结果

- Factorio 闭环 smoke test 跑通：implementer 产生一个真实可审计的 git commit；hallucination 不再能伪装成成功
- Palimpsest 里关于 `evo_root` 的所有硬引用被移除；palimpsest 变成纯粹的 runtime，不知道 bundle 来自哪里
- Trenni 获得多 bundle 仓库注册能力；bundle 之间完全解耦，可以独立演化、独立 rollback
- Event 流中所有大对象以 URI 引用形式出现；event payload 体积回归到 "时序事件" 应有的大小
- `docs/architecture.md` 的 "双真实数据源" 叙事被简化为 "**Event Store 为唯一时序真实源；内容真实源按 URI scheme 分布式分派**"

## 4. 容易混淆的概念

### 4.1 "Artifact" 作为概念 vs "Artifact Store" 作为模块
本 ADR 废除的是 **模块**（独立的存储子系统），不是 **概念**。Artifact 仍然是系统的 first-class 概念——只不过它的物理存在形式从"统一 content-addressed store"改为"一个 URI 引用 + 该 scheme 背后系统的存储"。

### 4.2 Event Store 权威 vs 内容权威
- **Event Store** 权威地回答："时刻 t 由 task T 声明产生了引用 X"
- **URI 背后的系统** 权威地回答："引用 X 的字节是什么"

两层职责正交。Event Store 的 append-only 保证事件不可变；git / 文件系统 / content-addressing 各自保证内容不可变。两层都是 append-only 的，颗粒度不同。

### 4.3 Bundle 仓库 vs Bundle runtime workspace
- **Bundle 仓库**：trenni registry 里的远端 git URI，是 bundle 定义与演化的**权威来源**
- **Workspace**：trenni 为每次 job 准备的 ephemeral clone，agent 在其上工作，publish 时 commit + push 回权威仓库，clone 本身立即丢弃

Workspace **永远不是**权威。把 workspace 当长期存储的任何做法（包括此前的 `workspace_override` 直接 bind mount `evo_root`）都是 bug。

### 4.4 声明 artifact vs 未声明 artifact
两者在运行时路径上完全一致——都是 event 里的 URI 引用。区别只在**启动期可见性**：声明的在 bundle schema 里，能被 trenni 索引和 lint；未声明的只能从事件流事后扫出。

## 5. 对之前 ADR 或文档的修正说明

- **ADR-0013（Artifact Store）被本 ADR 取代**。独立 store 作为模块不再存在。ADR-0013 中 "Blob / Tree 实体"、"ArtifactRef / ArtifactBinding 脱钩"、"双数据真相源" 等细节沦为历史记录。其对 git 的定位（"外部兼容收据 Compatibility Receipt"）被本 ADR 反转：git 在 code-like 场景下是**原生权威后端**。
- **ADR-0012（Factorio 隔离方案）**：文中"Factorio bundle 的 scripts 通过 `evo/factorio/scripts/` 管理"的隐含假设失效；正确表述是"Factorio bundle 作为独立 git 仓库，其 scripts 目录由该仓库自身 git 历史管理"。ADR-0012 的其他决定（独有镜像、RCON 桥接、`max_concurrent_jobs=1`）仍然有效。
- **`docs/TODO-bundle-isolation.md`**：本 ADR 覆盖了其 "Not In Scope" 列表的前两项（bundle manifests、multi-repo bundle distribution），为之提供继任方案。该 TODO 的 "Target State" 第 1 条（`evo/<bundle>/` 目录布局）被废除，由 bundle 独立仓库取代。其余条目（bundle 为唯一隔离边界、无全局 fallback、`bundle` 为 envelope 字段等）仍然有效。
- **`docs/architecture.md`**：
  - "双真实数据源 (Pasloe + Artifact Store)" 段落需要改写为 "Event Store 唯一时序真实源 + URI 分派内容真实源"
  - "Git 作为兼容收据" 需要反转为 "Git 作为 code-like artifact 的原生后端"
  - "可演化隔离区 (Evo Layer)" 一节整体作废：`evo/` 目录不再存在，bundle 的演化在各自仓库的 `evolve` 分支进行

- **`palimpsest/docs/design.md`**：原文将 "evo repo 作为自由表面" 作为 runtime 的中心概念，本 ADR 之后它应改写为 "runtime 消费由 trenni 准备的 `BundleSource.workspace`；evo 概念在 runtime 视角消失"。

- **`palimpsest/palimpsest/runtime/tools.py`** 中 spawn tool 的 LLM-facing 描述（`"isolated git clone; auto-commits and pushes"`）需在 Phase 1 内被显式改写为面向 bundle workspace 的表述，避免 LLM 把"isolated git clone"误解为 evo 整树的快照。

  以上三处具体改动由后续 Phase 1 实施计划落地，本 ADR 只触发修订需求。此外，在 Phase 1 代码落地**之前**，上述文件以及 `docs/TODO-bundle-isolation.md` 和 `docs/adr/0013-artifact-store.md` 需先打 `Superseded by ADR-0015` 的状态标，防止其旧语义被误引用。

- **`docs/reports/2026-04-08-factorio-optimization-loop-smoke-test-report.md`**：§5（重新设计建议）整体被本 ADR 取代；§1–§4 的实验事实仍然有效；§6 的 TODO 列表被 Phase 1 实施计划取代。

## 6. 尚未决定的事项

以下细节不在本 ADR 拍板范围，留待 Phase 1 实施计划决定：

1. `bundle.yaml` vs `bundle.py`（声明式 vs 可执行）
2. Trenni 对 bundle clone 的缓存策略（per-job ephemeral vs long-lived worktree）
3. Push 策略（同步 push 失败即 task fail vs commit 先行 + 异步推送）
4. Per-bundle 并发上限的配置位置（bundle.yaml 自声明 vs trenni config 覆盖）
5. Bundle repo 的 secret 注入（环境变量键名约定，如 `YOITSU_BUNDLE_GIT_TOKEN`）
6. `evolve` 分支约定的强制程度（ADR 推荐但不强制，细节交给 bundle convention 文档）
7. 新 factorio-bundle 仓库的物理落地路径（交给运维约定）

## 7. 后续 ADR 扩展

- **[ADR-0016](0016-capability-model.md)**：定义了 bundle 内部的运行时服务管理模型（capability），取代 role 级别的 `preparation_fn` / `finalization_fn` 单一函数绑定。
- **[ADR-0017](0017-observation-unified-interface.md)**：定义了 observation 统一分析接口，bundle 可在 `observations/` 目录中提供自定义 analyzer。
