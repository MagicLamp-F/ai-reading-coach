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
14. [Hermes 基础架构与接入状态](./13_hermes_foundation_architecture_status.md)：当前 Hermes wrapper、模型配置、验证结果、失败边界和下一步路线。
15. [快速读完包设计](./14_fast_read_pack_design.md)：说明阅读包的数据模型、artifact 保存、飞书预览、失败降级和验收标准；当前实现已升级到 `reading.deep_read_pack` / `deep_read_pack_v2`。
16. [当前已有能力与待做方案总览](./15_current_scope_and_next_plan.md)：用一份总览说明已经完成什么、还要验证什么、下一阶段该做什么，以及 OpenClaw 的位置。
17. [模型成本分流与投递可靠性](./16_model_cost_routing_and_delivery_reliability.md)：记录 Hermes/Codex/Antigravity/Gemini/OpenClaw 的分层使用方案、分步骤接入计划，以及 2026-06-02 飞书 daily 未送达的限流原因和修复方向。
18. [书源驱动阅读计划与每日伴读包需求评估](./17_source_driven_reading_plan_design.md)：评估用户提供书源、配置阅读天数或每日分钟数、每日生成待读片段和伴读快读包的用途、优劣、适用边界和 MVP 收敛方式。
19. [渐进式导读伴读体验设计](./18_progressive_guided_reading_experience_design.md)：面向低耐心阅读状态，设计第一版短导读启动、第二版自适应伴读、追剧式阅读和核心页面体验。
20. [渐进式导读伴读操作手册](./19_guided_reading_user_operation_manual.md)：说明如何在页面导入 EPUB/Markdown/TXT 书源、管理书源、创建阅读计划、阅读每日导读、提交反馈和启用飞书推送。
21. [Hermes 主画像架构设计](./20_hermes_primary_profile_architecture.md)：定义 Hermes native memory 作为主画像、ARC 作为阅读业务账本的方案 C，说明画像主从关系、反馈上送、写入审计和分阶段实施计划。
22. [技术项目骨架与运行流程](./21_technical_project_skeleton.md)：说明目录职责、正常日推链路、画像优先级、Hermes 严格模式、关键配置、验证命令和大改后的文档/提交规则。
23. [2026-06-02 Hermes / ARC / Feishu 总结](./development_history/2026-06-02_hermes_arc_delivery_and_reading_ui_summary.md)：总结 Hermes 默认生成、长快读包、ARC 阅读页、飞书投递可靠性、移动端阅读体验修复、验证结果和 GitHub 认证恢复步骤。

新增 systemd 单元：

- `deploy/systemd/ai-reading-coach-guided-reading.service`：发送到期的渐进式导读飞书卡片。
- `deploy/systemd/ai-reading-coach-guided-reading.timer`：默认每天 08:30 触发导读推送。

探索文档：

- [推荐反馈驱动的多维用户建模 MVP](../user_modeling_feedback_mvp.md)
