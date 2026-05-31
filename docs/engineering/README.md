# 工程化文档索引

这套文档用于把“AI 读书私教系统”从想法整理成可实施、可验证、可迭代的工程项目。当前最新方向是：

```text
腾讯云国内轻量服务器
+ 国内模型/API
+ 飞书作为第一交互入口
+ SQLite 事实记忆
+ Python 编排层
+ Hermes 长期记忆与反思层
+ OpenClaw 后续作为 Gateway/Skill 执行层
```

推荐阅读顺序：

1. [项目章程](./00_project_charter.md)：为什么做、做成什么样、边界是什么。
2. [系统架构](./01_system_architecture.md)：飞书、SQLite、Hermes、OpenClaw、Python 后端如何分工。
3. [闭环设计](./02_closed_loop_design.md)：推荐、反馈、原因、反思如何形成用户建模闭环。
4. [数据契约](./03_data_contracts.md)：核心数据对象、事件、画像字段和接口边界。
5. [实施路线](./04_implementation_roadmap.md)：从当前 Python MVP 到飞书 + Hermes/OpenClaw 融合版的阶段计划。
6. [运行与验收](./05_operations_and_validation.md)：如何运行、观测、验收和复盘。
7. [飞书优先接入方案](./06_lark_first_integration.md)：为什么先接飞书、初版怎么接、后续怎么升级。
8. [服务器基础环境与 Codex 安装手册](./07_server_bootstrap_codex_manual.md)：腾讯云 Ubuntu、GLaDOS/mihomo、Codex CLI、中转 API 和交给服务器 Codex 的操作顺序。
9. [服务器 Codex 执行 Prompt：飞书初版通道](./08_server_codex_lark_mvp_prompt.md)：在服务器 Codex 中粘贴执行的最终 Prompt。
10. [7 天试运行 Runbook](./09_trial_run_runbook.md)：systemd、定时任务、备份恢复、日志和每日观察清单。
11. [当前进展总结](./10_current_progress_summary.md)：当前已完成能力、待验证事项和下一步工作。
12. [hermes-agent 接入设计](./11_hermes_agent_integration_design.md)：Reflection Agent Adapter、hermes-agent CLI 接入、fallback、人审和回滚边界。
13. [Hermes 记忆 Agent 与阅读中台设计](./12_hermes_memory_agent_platform.md)：整理 Hermes 主 Agent、wrapper、MCP/ACP、OpenClaw、飞书闭环、快速读完包、数据库与文件沉淀的长期架构。
14. [快速读完包设计](./14_fast_read_pack_design.md)：说明 `reading.fast_read_pack` 的数据模型、artifact 保存、飞书预览、失败降级和验收标准。
14. [Hermes 基础架构与接入状态](./13_hermes_foundation_architecture_status.md)：当前 Hermes wrapper、模型配置、验证结果、失败边界和下一步路线。

探索文档：

- [推荐反馈驱动的多维用户建模 MVP](../user_modeling_feedback_mvp.md)
