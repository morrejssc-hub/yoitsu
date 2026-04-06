# Factorio Tool Evolution Guidance

当你分析 `observation.tool_repetition` 事件时，如果：
- `team == "factorio"`
- `tool_name` 包含 `factorio_call_script(actions.*)`
- `call_count >= 5`

这表示 worker 反复调用了同一个 action 脚本，存在抽象成更高层脚本的机会。

## 应输出的 ReviewProposal

```json
{
  "problem_classification": {
    "category": "tool_reliability",
    "severity": "medium",
    "summary": "Worker repeatedly called actions.place (10 times), pattern: grid_5x2"
  },
  "executable_proposal": {
    "action_type": "improve_tool",
    "description": "Create actions/place_grid.lua to encapsulate grid placement pattern",
    "estimated_impact": "Reduce tool calls from 10 to 1 for grid placement tasks"
  },
  "task_template": {
    "goal": "在 teams/factorio/scripts/actions/ 下创建 place_grid.lua，封装网格放置模式（参考 arg_pattern: grid_5x2）",
    "role": "implementer",
    "team": "default",
    "budget": 1.5
  }
}
```

## 关键点

- `task_template.role` 必须是 `"implementer"`（不是 worker）
- `task_template.team` 是 `"default"`（implementer 不占用 factorio 串行锁）
- `goal` 要明确指定文件路径和参考的 arg_pattern

## 分析流程

1. 检查 observation.tool_repetition 事件中的 `arg_pattern`
2. 分析重复调用的参数模式（如 grid_5x2 表示 5x2 网格）
3. 设计新脚本的接口，接受高层参数（如 width, height, entity）
4. 输出 ReviewProposal JSON 在 summary 字段中