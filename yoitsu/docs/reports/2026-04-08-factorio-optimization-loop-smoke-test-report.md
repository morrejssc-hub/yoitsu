# Factorio 优化闭环 Smoke Test 实验报告

**日期**: 2026-04-08  
**目标**: 验证 Factorio bundle 的 worker → optimizer → implementer → eval 闭环是否正常工作

---

## 一、实验背景

### 1.1 目标链路

```
用户任务 (trigger)
    │
    ▼
Worker (执行游戏内任务，产生 observation)
    │
    ▼ (eval_spec 触发)
Evaluator (验证 worker 输出)
    │
    ▼ (如果需要优化)
Optimizer (分析 observation.tool_repetition 等模式)
    │
    ▼ (输出 ReviewProposal)
Implementer (创建新脚本)
    │
    ▼
Evaluator (验证脚本是否真的创建)
    │
    ▼
下一轮 Worker (使用新脚本，预期减少 tool call 次数)
```

### 1.2 预期行为

1. Worker 执行任务，产生 `observation.tool_repetition` 事件
2. Optimizer 分析重复模式，输出改进建议
3. Implementer 创建新脚本到 `evo/factorio/scripts/`
4. Worker preparation 将新脚本同步到 Factorio mod
5. 第二轮执行使用新脚本，预期减少 tool call

---

## 二、实验过程

### 实验 1: 初始环境测试

**时间**: 07:40 - 08:00  
**存档**: `yoitsu-clean-20260408-074006.zip`

**操作**:
1. 手动创建干净存档
2. 启动 Factorio server
3. 提交 trigger: `用挖矿机挖 50 个铁矿`

**结果**:
- Worker 任务 `cea1b56a44951470` 卡在 `pending`
- 原因: 旧任务 `069d651f70757012` 占用 bundle slot，但容器已退出

**修复**: 手动发送 `agent.job.failed` 事件清理旧任务

**发现**:
- Trenni 没有正确检测容器退出状态
- 缺少 runtime_lost 恢复机制

---

### 实验 2: 第一次完整链路测试

**时间**: 08:00 - 08:15  
**存档**: `yoitsu-clean-20260408-074006.zip` (复用)

**操作**:
1. 提交 trigger (无 eval_spec)
2. Worker 完成，触发 optimizer

**结果**:
- Worker: `completed` (直接用 `atomic.inventory_add` 添加铁矿)
- Optimizer: `completed` (输出 ReviewProposal)
- Implementer: `completed` (声称创建了 `scan_area_resources.lua`)

**问题**:
1. **文件不存在**: Implementer 报告成功，但 `/home/holo/yoitsu/evo/factorio/scripts/` 下没有新文件
2. **没有验证机制**: 没有检查 LLM 是否真的调用了 bash 工具

**根因分析**:
- Implementer 使用 `workspace_override` 直接 bind mount `evo_root`
- 但容器完成后立即被删除，无法审计
- LLM 可能 "撒谎" - 声称完成但未调用工具

---

### 实验 3: 环境重置脚本验证

**时间**: 08:14 - 08:20

**创建**: `scripts/reset-factorio-smoke-env.sh`

**功能**:
```bash
1. 停止 Factorio 进程
2. cleanup-test-data.sh --skip-backup (清空 Pasloe/Trenni 状态)
3. build-job-image.sh --no-cache (重建 job image)
4. deploy-quadlet.sh --skip-build (重启服务)
5. 创建新存档
6. 启动 Factorio
```

**发现的问题**:
- `cleanup-test-data.sh` 有语法 bug: `SKIP_BACKUP="${1:-}" == "--skip-backup"`
- 缺少 `evo_root_host` 配置导致 mount 不生效

---

### 实验 4: Evaluator Role 添加

**时间**: 08:30 - 09:00

**问题识别**: 没有验证机制，LLM 可能撒谎

**解决方案**: 添加 `evaluator` role

**实现**:
```python
# evo/factorio/roles/evaluator.py
@role(name="evaluator", ...)
def evaluator(**params) -> JobSpec:
    return JobSpec(
        preparation_fn=evaluator_preparation,  # 使用 workspace_override
        context_fn=context_spec(
            system="factorio/prompts/evaluator.md",
            sections=[],
        ),
        publication_fn=evaluator_publication,
        tools=["bash"],
    )
```

**多次修复**:
1. `context_spec()` 缺少 `sections` 参数
2. `JobSpec` 不支持 `params` 参数
3. 缺少 `preparation_fn`

---

### 实验 5: eval_spec 传递修复

**时间**: 09:00 - 09:30

**问题**: `eval_spec` 在 trigger data 中，但没有传递到 TaskRecord

**修复**:
```python
# trenni/supervisor.py _process_trigger()
self.scheduler.record_task_submission(
    ...
    eval_spec=data.eval_spec,  # 新增
)
```

---

### 实验 6: 最终验证

**时间**: 17:00 - 17:15  
**存档**: `yoitsu-clean-20260408-165556.zip`

**操作**:
```json
{
  "trigger_type": "manual",
  "goal": "用挖矿机挖 50 个铁矿",
  "role": "worker",
  "bundle": "factorio",
  "eval_spec": {"role": "evaluator"}
}
```

**结果**:
- Worker: `partial` (60/60 iterations exhausted)
- Evaluator: `completed`
- Task final state: `partial`
- Semantic verdict: `pass` (正确识别任务未完成)

**Evaluator 输出摘要**:
```
任务目标"用挖矿机挖 50 个铁矿"未完成

缺失的关键功能：
1. 没有脚本能够等待挖矿机工作产出铁矿
2. 没有脚本能够从箱子或地面收集产出的铁矿
3. 没有脚本能够验证是否收集了 50 个铁矿
```

---

## 三、发现的设计问题

### 3.1 Implementer 直接写 Live Bundle (严重)

**当前设计**:
```python
# workspace_override 直接 bind mount evo_root
# LLM 在容器内直接写入 host 的 live bundle
# 没有版本控制，无法回滚
```

**问题**:
1. 绕过了 copy-modify-publish 流程
2. 没有语法验证
3. 依赖 `max_concurrent_jobs=1` 串行化 (不安全)
4. 中途失败可能留下损坏状态
5. 容器被立即删除，无法审计

**正确设计**:
```
1. Preparation: 复制 evo/factorio/scripts 到临时目录
2. Interaction: Agent 在临时目录修改文件
3. Publication:
   - 验证 Lua 语法
   - 验证 DYNAMIC 约束
   - 复制回 evo_root 或提交到 git
   - 记录变更
```

### 3.2 LLM Hallucination (严重)

**现象**:
- LLM 声称"脚本已创建完成"
- 但实际 `LLM returned no tool calls`
- 没有调用 bash，文件自然不存在

**根因**:
- LLM 可能产生虚假完成报告
- 没有强制工具调用验证
- Interaction loop 没有检测这种模式

**修复方向**:
1. Interaction loop 层面: 检测声称完成但无 tool calls
2. Publication 层面: 强制验证文件存在
3. Prompt 层面: 加强约束

### 3.3 容器生命周期管理 (中等)

**问题**:
- 容器完成立即删除
- 无法审计历史执行
- 无法事后检查日志

**临时修复** (调试用):
```python
# trenni/supervisor.py _cleanup_handle()
# TODO: debug - skip cleanup for now
return
```

**正确设计**:
- 保留容器日志到持久化存储
- 或: 保留容器 N 小时后再清理
- 或: 提取关键日志事件存储

### 3.4 Eval 触发机制 (中等)

**当前**:
- 需要手动指定 `eval_spec`
- 依赖用户/trigger 配置

**改进方向**:
- 默认 eval: 每个 implementer 任务自动触发 eval
- 或: 基于角色类型的默认 eval 策略

---

## 四、代码变更汇总

### 4.1 新增文件

| 文件 | 用途 |
|------|------|
| `scripts/reset-factorio-smoke-env.sh` | 环境重置脚本 |
| `evo/factorio/roles/evaluator.py` | Evaluator role 定义 |
| `evo/factorio/prompts/evaluator.md` | Evaluator prompt |
| `tests/test_factorio_smoke_reset_script.py` | 重置脚本测试 |
| `docs/TODO.md` | 待办事项 |

### 4.2 修改文件

| 文件 | 变更 |
|------|------|
| `scripts/cleanup-test-data.sh` | 修复语法错误 |
| `trenni/trenni/runtime_builder.py` | evo mount 改为 RW |
| `trenni/trenni/supervisor.py` | 传递 eval_spec, 跳过 cleanup (调试) |
| `trenni/trenni/config.py` | 添加 evo_root_host 字段 |
| `trenni/trenni/runtime_types.py` | volume_mounts 支持 RW 标志 |
| `trenni/trenni/podman_backend.py` | 生成 Podman mount payload |

### 4.3 提交记录

```
1c7bfac fix(factorio): add missing evaluator_preparation import and function
d6d645a fix(factorio): add preparation_fn to evaluator role
3416e32 fix(factorio): remove invalid params from evaluator JobSpec
cfcc38f fix(factorio): add required sections arg to evaluator context_spec
95da003 fix(trenni): pass eval_spec from trigger to task record
c877e85 feat(factorio): add evaluator role to validate implementer output
c073d9f fix(trenni): mount evo_root RW for implementer writes
0e1aafc fix(scripts): correct cleanup-test-data.sh skip-backup check
4e9d97c test: codify factorio smoke environment reset
```

---

## 五、重新设计建议

### 5.1 Implementer 改用 Copy-Modify-Publish

**Phase 1: Preparation**
```python
def implementer_preparation(*, evo_root: str, **kwargs) -> WorkspaceConfig:
    # 1. 创建临时工作目录
    workspace = tempfile.mkdtemp(prefix="implementer-")
    
    # 2. 复制 factorio/scripts 到工作目录
    src = Path(evo_root) / "factorio" / "scripts"
    dst = Path(workspace) / "factorio" / "scripts"
    shutil.copytree(src, dst)
    
    # 3. 记录原始文件列表用于 diff
    original_files = set(dst.rglob("*.lua"))
    
    return WorkspaceConfig(
        repo="", 
        new_branch=False,
        workspace_override=workspace,
        # 传递 context 用于 publication
        context={"evo_root": evo_root, "original_files": original_files}
    )
```

**Phase 2: Publication**
```python
def implementer_publication(workspace_path: str, context: dict, **kwargs) -> tuple[str, list]:
    workspace = Path(workspace_path)
    evo_root = Path(context["evo_root"])
    original_files = context["original_files"]
    
    # 1. 找到新文件和修改的文件
    new_scripts = (workspace / "factorio" / "scripts").rglob("*.lua")
    
    # 2. 验证每个文件
    for script in new_scripts:
        # Lua 语法检查
        valid, error = validate_lua_syntax(script)
        if not valid:
            raise PublicationError(f"Syntax error in {script.name}: {error}")
        
        # DYNAMIC 约束检查
        valid, error = check_dynamic_constraint(script)
        if not valid:
            raise PublicationError(f"Constraint violation in {script.name}: {error}")
    
    # 3. 复制回 evo_root
    for script in new_scripts:
        target = evo_root / "factorio" / "scripts" / script.relative_to(workspace / "factorio" / "scripts")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(script, target)
    
    # 4. 返回结果
    return None, []
```

### 5.2 强制 Tool Call 验证

**在 Interaction Loop 中**:
```python
# palimpsest/stages/interaction.py

def run_interaction_loop(...):
    ...
    if llm_response.content and not tool_calls:
        # LLM 返回了文本但没有调用工具
        if any(keyword in llm_response.content for keyword in ["完成", "created", "done", "success"]):
            # LLM 声称完成但没有实际操作
            logger.warning("LLM claims completion without tool calls - likely hallucination")
            
            # 强制要求工具调用或明确放弃
            forced_response = ask_llm("You claimed completion but made no tool calls. "
                                      "Either call tools to complete the task, "
                                      "or explicitly state you cannot complete it.")
            if not forced_response.tool_calls:
                raise InteractionError("LLM hallucination detected: claims success without action")
```

### 5.3 日志持久化

**方案 A**: 容器日志收集
```yaml
# trenni.dev.yaml
runtime:
  podman:
    log_driver: "json-file"
    log_opts:
      max-size: "10m"
      max-file: "3"
      path: "/var/log/yoitsu/jobs"
```

**方案 B**: 事件存储
```python
# 在 job 完成时提取关键日志
async def _extract_job_logs(self, job_id: str) -> dict:
    logs = await self.backend.get_logs(job_id)
    key_events = extract_key_events(logs)  # tool calls, errors, etc.
    await self.client.emit("agent.job.logs", {
        "job_id": job_id,
        "key_events": key_events,
    })
```

### 5.4 默认 Eval 策略

```python
# trenni/supervisor.py _handle_job_done()

async def _handle_job_done(self, event: Event, ...):
    ...
    # 如果是 implementer role，自动触发 eval
    if job.role == "implementer" and not task.eval_spawned:
        default_eval_spec = EvalSpec(role="evaluator")
        await self._spawn_eval_job(task, default_eval_spec)
```

---

## 六、后续工作

### 短期 (P0)
1. [ ] 恢复 `_cleanup_handle` 正常逻辑（当前跳过清理用于调试）
2. [ ] 实现 Implementer copy-modify-publish
3. [ ] 添加 tool call 验证防止 LLM hallucination

### 中期 (P1)
4. [ ] 实现日志持久化
5. [ ] 添加 implementer 默认 eval 策略
6. [ ] 增强 evaluator prompt

### 长期 (P2)
7. [ ] 添加 Lua 语法检查到 CI
8. [ ] 实现脚本版本控制
9. [ ] 添加回滚机制

---

## 七、附录

### A. Evaluator 发现的脚本缺陷

当前 Factorio bundle 缺少以下功能：

| 功能 | 现有脚本 | 缺失 |
|------|----------|------|
| 扫描资源位置 | `scan_resources_area.lua` | ✅ |
| 放置挖矿机 | `examples/setup_mining.lua` | ✅ |
| 等待挖矿机产出 | - | ❌ |
| 收集产出物品 | - | ❌ |
| 验证收集数量 | - | ❌ |

### B. 测试数据

**Experiment 6 详细结果**:
```json
{
  "task_id": "2daa5025c5385d6b",
  "goal": "用挖矿机挖 50 个铁矿",
  "state": "partial",
  "result": {
    "structural": {"partial": 1},
    "semantic": {
      "verdict": "pass",
      "summary": "任务目标未完成，缺少关键脚本"
    }
  }
}
```

### C. 环境信息

```
Factorio: 2.0.76
Trenni: 95da003
Palimpsest: 94a51415ce058a044953a2c99c3207f6693a3206
Pasloe: (from postgres volume)
Python: 3.11
Podman: (from system)
```