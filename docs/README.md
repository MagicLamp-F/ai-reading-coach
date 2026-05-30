# 文档目录

本目录包含两类文档。

## 工程化文档

入口：[engineering/README.md](./engineering/README.md)

当前最新方向：

```text
腾讯云国内轻量服务器
+ 国内模型/API
+ 飞书作为第一交互入口
+ SQLite 事实记忆
+ Python 编排层
+ Hermes 长期记忆与反思层
+ OpenClaw 后续 Gateway/Skill 执行层
```

工程化文档用于指导项目实施、架构演进和验收，包括：

- 为什么做。
- 做成什么样。
- 为什么这样设计。
- 系统怎么闭环。
- 数据怎么设计。
- 怎么分阶段实现。
- 飞书怎么先接入。
- 服务器基础环境和 Codex 怎么安装配置。
- 如何运行、观测和验收。
- Hermes、OpenClaw、飞书、数据库和文件系统如何共同支撑长期阅读画像与阅读历程。

当前进展：

- [当前进展总结](./engineering/10_current_progress_summary.md)
- [Hermes 记忆 Agent 与阅读中台设计](./engineering/12_hermes_memory_agent_platform.md)
- [7 天试运行 Runbook](./engineering/09_trial_run_runbook.md)

## 探索性文档

- [推荐反馈驱动的多维用户建模 MVP](./user_modeling_feedback_mvp.md)

用于记录产品想法、反馈机制和用户建模方向。工程化文档基于这份探索文档整理而来，并结合最新决策更新为“飞书优先”的实施路径。
