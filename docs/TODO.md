
## 2026-04-08: Implementer 应该用 copy-modify-publish 模式

**当前问题**：
- `workspace_override` 直接 bind mount evo_root RW
- Agent 在容器内直接写 host 的 live bundle
- 容器被快速清理，无法审计实际行为
- 绕过了版本控制，无法回滚

**正确设计**：
1. Preparation: 复制 evo/factorio/scripts 到临时目录
2. Interaction: Agent 在临时目录修改文件
3. Publication:
   - 验证 Lua 语法
   - 复制回 evo_root 或提交到 git
   - 记录变更

**临时修复（MVP）**：
- 持久化容器日志用于审计
- 验证写入是否成功后再返回

**相关文件**：
- `evo/factorio/roles/implementer.py`
- `evo/factorio/lib/preparation.py`
- `trenni/trenni/runtime_builder.py`
