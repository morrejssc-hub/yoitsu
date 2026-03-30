# Factorio 驱动的治理层构建

Date: 2026-03-30
Status: Draft

## 一、背景与动机

### 1.1 演化冷启动问题

Yoitsu 的核心价值主张是连续可演化——agent 通过修改 evo 层来改进自身。但演化需要选择压力，选择压力来自大量、多样、可量化的任务。

当前缺失的是：**一个足够丰富的外部任务环境来驱动演化循环**。

SWE-bench 等 coding benchmark 是离散的一次性测试用例，无法提供持续的、有状态积累的任务流。我们需要一个开放式环境，在其中 agent 面对不断升级的挑战，且每一步的结果都可量化。

### 1.2 治理层缺失

当前系统能执行、能分支、能发布、能评估。但没有能力回答：

- 某个 role 的平均效率是否在下降？
- 哪些 evo/tool 被频繁调用但产出低？
- agent 是否在重复执行应该被脚本化的操作？
- 某次 evo 变更是改进还是退化？

单个 job 没有自省动机——完成目标即退出。治理层的职责是**跨 job 的模式识别和优化信号提取**，它不能在真空中设计，必须在真实任务中被需求驱动出来。

### 1.3 为什么是 Factorio

Factorio 是一个工厂建造与自动化游戏。它的特性天然适合作为演化任务源：

| 特性 | 对演化系统的意义 |
|---|---|
| 完全可量化的游戏状态 | items/min、科技进度、电力平衡——硬指标，不需要 LLM 做语义判断 |
| 无限且自然分层的任务空间 | 微观（放传送带）→ 中观（设计产线）→ 宏观（规划全局布局），匹配递归 spawn |
| 持续有状态的环境 | 不是一次性测试，工厂状态持续积累，决策有长期后果 |
| 确定性强 | 和平模式下几乎完全确定性，benchmark 可重复 |
| 丰富的 Lua modding API | agent 可以编写脚本扩展自身能力 |
| RCON 远程控制接口 | 可通过网络与运行中的游戏交互 |

---

## 二、核心设计：限制行动、开放信息、鼓励脚本

### 2.1 交互模型

Agent 与 Factorio 的交互分为三类，权限递减：

| 类别 | 描述 | 限制 |
|---|---|---|
| **查看** | 读取游戏状态（实体、库存、产能、地图） | 无限制，鼓励 |
| **脚本** | 提交 Lua 脚本供游戏执行（信息收集或自动化） | 无限制，鼓励 |
| **行动** | 直接操作游戏世界（放置、拆除、配置实体） | 有预算限制 |

这个设计的意图：

- **行动受限**形成经济压力，迫使 agent 先思考再行动，类似 budget 机制
- **信息开放**鼓励 agent 构建更好的感知——写 Lua 脚本扫描瓶颈、统计产能、分析物流
- **脚本鼓励**让 agent 的演化路径自然指向自动化：手动操作 → 写脚本辅助 → 写脚本自动化 → 组合脚本解决更大问题

### 2.2 演化路径

```
手动操作，逐个放置实体
    ↓
写信息脚本，获得全局视野（瓶颈在哪、缺什么）
    ↓
写自动化脚本，将重复操作封装（铺设传送带、平衡产线）
    ↓
优化脚本，提升效率和通用性
    ↓
组合脚本，解决更大规模问题（整个子工厂的自动布局）
```

每一步都在 evo 层留下版本化的工具，可被后续 job 复用，也可被治理层评估。

---

## 三、与 Yoitsu 架构的映射

### 3.1 Evo 层映射

| Evo 目录 | Factorio 中的含义 |
|---|---|
| `evo/roles/` | 侦察员（扫描地图和资源）、产线设计师（规划生产链）、物流规划师（传送带和火车网络）、脚本编写者（编写 Lua 工具） |
| `evo/tools/` | agent 编写的 Lua 脚本，封装为 Yoitsu tool（信息查阅、自动化操作、蓝图生成） |
| `evo/contexts/` | 工厂状态摘要、recipe 树、当前瓶颈分析、资源分布 |
| `evo/prompts/` | 针对不同任务类型的决策指导 |

### 3.2 Spawn 分解映射

一个宏观目标（如"自动化红瓶绿瓶生产"）自然分解为：

```
planner: 自动化红瓶绿瓶
├── task: 建立铁矿开采和冶炼
├── task: 建立铜矿开采和冶炼
├── task: 建立齿轮生产线
├── task: 建立电路板生产线
├── task: 建立红瓶组装
├── task: 建立绿瓶组装
└── join: 验证整体产能并优化
```

每个子任务是一个 job，使用 evo/roles 中的角色，可能调用 evo/tools 中的 Lua 脚本。

### 3.3 验证映射

| Yoitsu 验证层 | Factorio 实现 |
|---|---|
| Structural verdict | job 执行是否成功（脚本是否报错、操作是否完成） |
| Semantic verdict (eval job) | 硬指标检查：目标产量是否达标、电力是否平衡、无死锁 |
| Evo benchmark | 跨版本对比：同一任务在 evo v1 vs v2 下的产量、行动次数、token 消耗 |

---

## 四、治理层：从 Factorio 中自然浮现

治理层不预先设计完整规范，而是在 Factorio 任务中被需求驱动出来。以下是预期会浮现的治理需求：

### 4.1 跨 Job 模式检测

| 信号 | 含义 | 治理动作 |
|---|---|---|
| 同一操作序列在多个 job 中重复出现 | 应该被脚本化 | 提示 agent 或自动生成 evo/tool 候选 |
| 某个 role 的 token 消耗持续偏高但产出不增 | role 定义或 context 可能有问题 | 标记为待优化，触发 evo 改进任务 |
| 某个 evo/tool 被频繁调用但结果经常被丢弃 | 工具质量低或使用场景不匹配 | 降低推荐权重或触发重写 |
| eval 反复因同类指标失败 | 策略层面的系统性问题 | 回溯到 prompt/context，生成改进假设 |

### 4.2 Evo 变更门控

每次 evo 变更必须通过：

1. **回归测试**：在标准化 Factorio 场景上运行，产出不低于当前版本
2. **增量验证**：在变更针对的具体场景上运行，产出高于当前版本
3. **成本检查**：token 消耗不显著增加

变更通过门控后才能合并到 evo 主线。失败的变更保留记录但不合并。

### 4.3 Scorecard

每个 evo 版本维护 scorecard：

```yaml
evo_sha: abc123
metrics:
  red_science_task:
    items_per_min: 45
    actions_used: 23
    token_cost_usd: 0.12
    elapsed_ticks: 18000
  green_science_task:
    items_per_min: 30
    actions_used: 31
    token_cost_usd: 0.18
    elapsed_ticks: 24000
  # ...
trend: improving  # 或 degrading / stable
```

---

## 五、Factorio 接入层

Agent 不直接操控 Factorio。中间需要一个 bridge 层处理双向通信。

### 5.1 接入路径

```
Agent (Palimpsest job)
    ↓ Yoitsu tool calls
Factorio Bridge (中间层)
    ↓ RCON commands / Lua injection
Factorio Server (headless)
    ↓ Lua API
Game World
```

### 5.2 Bridge 职责

- **状态查询**：将 RCON 返回的游戏数据结构化为 agent 可消费的 JSON
- **行动执行**：将 agent 的高层操作指令翻译为 Factorio Lua 命令
- **脚本管理**：接收 agent 提交的 Lua 脚本，注入游戏运行，返回结果
- **行动预算**：追踪和限制 agent 的直接操作次数
- **状态快照**：支持保存/恢复游戏状态，用于 benchmark 回放

### 5.3 Agent 可用的工具集

作为 Palimpsest tool 暴露给 agent：

| 工具 | 类别 | 描述 |
|---|---|---|
| `factorio_inspect` | 查看 | 查询指定区域/实体类型的当前状态 |
| `factorio_production_stats` | 查看 | 获取全局或指定物品的生产/消耗统计 |
| `factorio_execute_lua` | 脚本 | 提交 Lua 代码片段在游戏中执行并返回结果 |
| `factorio_register_script` | 脚本 | 注册一个持久化的 Lua 脚本（定时执行或事件触发） |
| `factorio_place_entity` | 行动 | 在指定位置放置实体（消耗行动预算） |
| `factorio_remove_entity` | 行动 | 移除指定实体（消耗行动预算） |
| `factorio_configure_entity` | 行动 | 修改实体配置如 recipe、过滤器（消耗行动预算） |
| `factorio_craft` | 行动 | 手动合成物品（消耗行动预算） |
| `factorio_advance_time` | 控制 | 推进游戏时间指定 tick 数，观察结果 |

---

## 六、里程碑

### M0：Factorio Bridge 基础

- Factorio headless server 的启动和管理
- RCON 连接和基本命令执行
- 最小工具集实现：`factorio_inspect`、`factorio_execute_lua`、`factorio_place_entity`
- 一个手动验证：agent 能在空地图上放置一个采矿机 + 熔炉 + 箱子

### M1：单任务闭环

- 完整工具集实现
- 行动预算追踪
- 定义第一个 benchmark 场景：从空地上自动化红瓶生产
- agent 能完成 benchmark 并产出可量化结果（items/min）
- eval job 能自动验证结果

### M2：Evo 演化闭环

- agent 编写的 Lua 脚本能被持久化到 evo/tools
- 后续 job 能复用前序 job 产出的工具
- 可观测到跨 job 的效率提升（同一任务用更少 action 达到更高产量）
- evo SHA 锚定和版本对比可用

### M3：治理层基础

- 跨 job 模式检测的第一批规则上线
- evo 变更门控（回归测试 + 增量验证）
- Scorecard 自动生成和趋势追踪
- 一个端到端 demo：展示 agent 发现瓶颈 → 写脚本 → 演化工具 → 治理层确认改进

### M4：任务复杂度升级

- 扩展 benchmark 到绿瓶、蓝瓶、紫瓶
- 多任务并行（spawn 分解 + join）
- 更长时间跨度的演化观测
- 治理层处理退化检测和回滚

---

## 七、待讨论

- Factorio bridge 是独立仓库还是放在 yoitsu 主仓库中？
- Bridge 用 Python 实现还是其他语言？
- Headless server 是跑在 Podman 容器中（和 job 共享网络）还是独立部署？
- 行动预算的具体数值如何确定？按 tick 还是按操作次数？
- 是否需要一个 Factorio mod 来增强 API 能力（原生 RCON 能力有限）？
- 游戏版本固定策略（避免更新导致 API 变化）
