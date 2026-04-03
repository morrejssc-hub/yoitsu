# Yoitsu 待办与演进路线图 (TODO)

本文件汇总了系统的短期清理清理任务、长期演化路线以及基于后续架构迭代（例如 Artifact Store 的全面落地）的改进点。

## 第一阶段：短期债务清理反馈

- [ ] 完全废弃并删除向后兼容使用的 `SpawnTaskData` 内嵌的 `prompt` 与 `params` 字段。
- [ ] 矫正 `SupervisorJobLaunchedData` 等事件里的残留语义（确保属于 resolved config 而非 delta 偏移记录）。
- [ ] **调度器分离 (P2)**：将摄取 (intake) 与执行 (execution) 代码流基于新的控制面流进行彻底隔离分离。
- [ ] **执行安全性 (P1)**：为 `evo/` 内部纯 Python 工具的执行施加基于子进程的安全隔离与硬超时的约束边界（当前仅影响纯进程内调用）。
- [ ] **预算补全 (P1)**：补齐旧示例与测试用例的 `root budget` 必须指定的架构要求；梳理验证 `join-job` 延续任务对预算继承体系的处理逻辑。

## 第二阶段：五步系统迭代演进闭环

> [!NOTE] 
> 该部分进度不受 `Artifact Store` (ADR-0013) 在底层落地实施的具体时序影响，可并行实施。

1. **GitHub 通用客户端**：提供单一的 API 层为 Tool 和 Context 提供 PR查询、评论读取与条件合并。
2. **外部任务摄流（解决冷启动）**：启用 CI/CD 执行失败与 GitHub 带有特定标签的 Issue 事件作为新的触发源（Trigger）。
3. **闭环 Reviewer Role**：基于 GitHub 给出的上下文完成审阅代码、产生审查建议，并探索其直接批准进行自动合并的能力。
4. **Pasloe 自视能力查询补充**：增强 Pasloe 查询任务时间线、成功率维度的只读聚合查询接口。
5. **内循环自优化 (Self-Optimization Loop)**：根据前述步骤积攒的执行任务量分析失败上下文，自发创建调整 `evo/` 层策略的优化任务。

## 第三阶段：Artifact Store 后续落地验证

- [ ] **产物存储接管**：在新的 `docs/architecture.md` 下，确保非 Git 兼容类任务（例如 Factorio 的 Rcon 与大文件游戏状态记录）使用 Artifact `blob` 与 `tree` 完整固化，脱离现有纯 Git 的强制依赖假设。
