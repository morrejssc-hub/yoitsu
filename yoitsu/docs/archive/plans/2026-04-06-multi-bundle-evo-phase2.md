# Multi-Bundle Evo Architecture (Phase 2)

**Status:** Design draft, not implemented in MVP

**Problem:** 当前 evo 是单一 git repo，所有 teams 的资产都在同一个仓库里。这导致：
- 任务域（如 factorio）无法作为独立 repo 分发和版本控制
- 第三方任务域集成需要 fork yoitsu 主仓库
- evo SHA 是单一字符串，无法表达"factorio team 用 v1.2.3，minecraft team 用 v2.0.1"

**目标架构：**

```
yoitsu-evo/  (全局 evo，yoitsu 核心 roles/tools)
├── roles/
├── tools/
└── contexts/

factorio-agent/  (独立 bundle)
├── teams/factorio/
│   ├── roles/
│   ├── tools/
│   ├── contexts/
│   └── scripts/
└── mod/

minecraft-agent/  (另一个 bundle)
├── teams/minecraft/
    └── ...
```

**运行时组装：**
- trenni config 配置 bundle manifest：
  ```yaml
  evo_bundles:
    - repo: https://github.com/org/yoitsu-evo
      ref: main
      priority: 0
    - repo: https://github.com/org/factorio-agent
      ref: v1.2.3
      priority: 10
    - repo: https://github.com/org/minecraft-agent
      ref: v2.0.1
      priority: 10
  ```
- `_materialize_evo_root` 改成 `_materialize_evo_bundles`，返回一个虚拟 evo 目录（overlayfs 或 Python 路径合并）
- RoleManager / tool loader / context loader 扫描多个 bundle，按 priority 决定 shadow 顺序

**需要的改动：**
1. TrenniConfig 加 `evo_bundles: list[BundleSpec]`
2. runner.py `_materialize_evo_root` 改成多 repo checkout + overlay
3. JobConfig.evo_sha 改成 `evo_bundle_refs: dict[str, str]`（bundle_name → sha）
4. ReviewProposal 加 `target_bundle: str` 字段，implementer 知道写哪个 repo

**MVP workaround：**
- factorio-agent 仓库本身就是 evo（顶层加 roles/tools/contexts 空目录）
- `PALIMPSEST_EVO_DIR` 环境变量指向 factorio-agent clone 路径
- 只支持单一任务域

**Phase 2 实施时机：**
- 当需要接入第二个任务域（如 minecraft）时
- 或当 factorio-agent 需要独立分发给其他 yoitsu 部署时
