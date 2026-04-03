# Yoitsu 极简开发向导

本指南为开发者提供关于系统调试与部署的最简环境说明。相关 API 细节、接口调用与容器内环境变量配置详情，请直接查阅对应模块代码目录下的配置文件或脚手架注释。

## 部署与容器编排 (Deployment via Quadlet)

由于涉及高强度的运行时隔离和执行器编排，Yoitsu 通过 Systemd 集成了 Podman (即 Quadlet) 来进行服务调度。
- 关键基础容器包括 `pasloe.container`、`postgres.container` （基于 pasloe 网络），以及负责调度的 `trenni.container` 和本地开发辅助 `yoitsu-dev.pod`。
- 其他工作执行任务均由 Trenni 通过其集成的 `PodmanBackend` 动态拉取或运行，无需开发人员手动通过 shell 干预。

## 代码质量保障 (Testing)

所有的代码修改必须符合契约，测试全量覆盖所有的调度边界逻辑：
- 我们使用标准 `pytest` 作为统一的测试推进器，通过 `pytest tests/` 执行基本校验。
- 测试过程中会模拟 `TaskView` 的状态回放以替代复杂的运行时集成；涉及重构时（如状态机变更或事件格式调整），请密切结合 `yoitsu-contracts` 仓库下的断言要求进行联调测试。
