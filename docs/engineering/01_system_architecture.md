# 系统架构

## 1. 当前目标架构

```text
用户
  |
  v
飞书消息 / 飞书卡片
  |
  v
飞书 Webhook 或飞书应用回调
  |
  v
Python Orchestrator
  |
  +--> SQLite 事实数据库
  |
  +--> 国内模型 / 搜索 API
  |
  +--> Reflection Agent Adapter
  |       +--> hermes-agent（可选）
  |       +--> custom reflection fallback
  |
  +--> Fast Read Pack Generator
  |       +--> Book Source Collector（公开来源摘录）
  |       +--> SQLite artifact metadata
  |       +--> library/YYYY/MM/.../reading-pack.md
  |
  +--> Daily Recommendation Agent Adapter
  |       +--> hermes-agent（可选）
  |       +--> legacy direct model branch（可回滚）
  |
  +--> OpenClaw Gateway / Skill Layer（后续）
  |
  v
飞书推送每日推荐和周期复盘
```

当前第一阶段采用“飞书优先”：

- 初版用飞书自定义机器人或 Webhook 推送每日推荐。
- 反馈初期可以使用反馈链接。
- 进阶版升级到飞书应用机器人和交互式卡片按钮回调。
- Telegram 暂不作为主入口，避免国内服务器访问不稳定。

## 2. 组件职责

### 飞书：交互入口

飞书负责用户触达和反馈收集：

- 每日推荐消息。
- 反馈按钮或反馈链接。
- 原因选择。
- 周期性复盘推送。
- 后续支持卡片状态更新。

初版可以只做：

```text
飞书自定义机器人推送消息
+ 每本书附带反馈链接
```

进阶版再做：

```text
飞书应用机器人
+ 交互式卡片
+ 按钮回调
+ 二级原因选择
```

### SQLite：事实层

SQLite 是 source of truth，保存不可丢失的原始事实：

- 推荐记录。
- 用户按钮反馈。
- 原因反馈。
- 自由文本。
- 快速读完包元数据。
- 书籍公开来源摘录和 reading pack 来源引用关系。
- 长文本 artifact 路径和 hash。
- 周期性复盘回答。
- 结构化画像条目。
- 运行日志。
- API 调用和成本记录。

原则：

- 原始事件不被覆盖。
- 画像摘要可以重算。
- 每条画像必须能追溯证据。

### Hermes / Reflection Agent：长期记忆和反思层

Hermes 负责把事实解释成语义记忆。当前实现已经把这层抽象成可插拔 `ReflectionAgentAdapter`：

- `hermes-agent` 可以作为外部 agent 实现接入。
- 当前自研 custom reflection 继续作为 fallback。
- Python Orchestrator 统一构造 SQLite 摘要和 weekly report 上下文。
- agent 只输出 reflection JSON 草稿，不直接写数据库、不直接写 memory 文件、不发送消息。
- `USER.md` / `MEMORY.md` 仍由 Python 后端在人工审批后追加写入。
- 总结长期兴趣和短期关注。
- 识别知识缺口、行动阶段、反感模式。
- 每周生成用户画像复盘。
- 提出 Skill 或推荐策略的改进建议。

Hermes 不直接替代 SQLite。SQLite 保存事实，Reflection Agent 只生成可解释草稿；草稿默认可经过 `approve-reflection` 和 `apply-reflection` 后进入 `memory/USER.md` 与 `memory/MEMORY.md`，也可以开启自动 apply。无论手动还是自动 apply，都必须写入 `memory/change_logs` 审计文件。`run-daily` 只读取已应用 memory，绝不读取 draft reflection。

### Python Orchestrator：可靠编排层

Python 后端负责确定性流程：

- 每日定时触发。
- 数据库读写。
- 调用国内模型 API。
- 调用搜索 API。
- 调用 Hermes 生成反思。
- 可选调用 Hermes 生成每日推荐主题和书单。
- 自动或手动生成快速读完包并沉淀 artifact。
- 抓取推荐记录中已有的公开书籍来源链接，清洗后作为 reading pack 上下文。
- 发送飞书消息。
- 记录运行日志。
- 控制 API 调用次数。
- 暴露指标。
- 失败时可重跑、可排查。

它不负责“变聪明”，它负责让闭环可靠发生。

### OpenClaw：后续 Gateway 和 Skill 执行层

OpenClaw 暂不作为第一阶段必须项，后续用于：

- 承担多渠道 Gateway。
- 管理 session。
- 统一 Skill/tool 权限。
- 执行搜索、总结、推送、反馈处理等 Skill。
- 让飞书、企业微信、Telegram 等渠道逐步统一。

### Skill：行为规范层

Skill 用于沉淀 Agent 的工作方式：

- 如何筛选书籍。
- 如何说明推荐理由。
- 如何解释用户反馈。
- 如何更新用户画像。
- 如何生成复盘问题。

Skill 的更新应先由 Hermes 提出建议，再由用户确认后生效。

## 3. 当前实现与目标架构的关系

当前飞书优先 MVP 已实现：

- SQLite schema。
- 每日推荐 workflow。
- 飞书自定义机器人文本消息和交互式推荐卡片。
- 推荐卡片展示 `system_hypothesis`、`profile_dimensions`、推荐理由、收益、风险和建议读法。
- 每日 3 本推荐后的“今日画像测试”汇总卡片。
- 反馈链接、HMAC 签名校验、原因选择页和自由文本补充。
- 基于 `feedback_type + reason_code` 的画像回写规则。
- 7 天复盘，包含反馈分布、原因分布、画像置信度分层、可能误解、自由文本摘要和下周建议。
- 日志、基础 metrics、systemd 试运行单元和备份脚本。
- Hermes reflection adapter：支持 `custom` 默认实现和 `hermes-agent` CLI 适配器；外部 agent 失败时可回退到 custom reflection。
- Hermes daily recommendation adapter：设置 `DAILY_RECOMMENDATION_PROVIDER=hermes-agent` 后，主题和书单生成通过 Hermes wrapper 执行，业务项目不再直连模型生成 daily 推荐。
- 快速读完包 MVP：`run-daily` 默认对每条推荐生成 fast read pack，飞书卡片展示预览；也支持对已有 recommendation 手动执行 `generate-reading-pack`，生成 Markdown artifact，并把 `reading_packs` / `artifacts` 元数据写入 SQLite。
- 轻量来源层：`BookSourceCollector` 会在生成阅读包前采集推荐 `source_url` 的公开网页摘录，写入 `book_sources`，并用 `reading_pack_sources` 记录阅读包实际引用的来源；失败时不阻断日推。
- Telegram 推送和按钮反馈框架仍保留为兼容通道。

当前暂不继续完善 Telegram。下一步是把飞书初版放到真实服务器试运行，并用真实反馈验证原因体系和画像更新规则：

```text
app/lark.py
app/server.py
app/feedback.py
app/workflow.py
app/profile.py
deploy/systemd/*
docs/engineering/09_trial_run_runbook.md
```

后续改造方向：

```text
飞书自定义机器人 -> 飞书应用机器人
profile.py 的规则总结 -> Reflection Agent 草稿 -> 人审应用
硬编码 prompt -> Skill 文件
SQLite 摘要 -> Hermes memory provider / context input
多渠道接入 -> OpenClaw Gateway
推荐理由 -> 快速读完包 -> 书库/业务页面复盘
```

## 4. 关键架构原则

### 事实和解释分离

SQLite 保存事实，Hermes 生成解释。解释可以更新，事实必须保留。

### 推荐和建模分离

推荐是交互方式，建模是核心目标。不要只优化推荐命中率。

### 生成和控制分离

模型负责生成主题、推荐和总结；后端负责定时、状态、日志、成本和权限。

### 渠道和业务分离

飞书、Telegram、企业微信都只是渠道。核心业务应通过统一 channel interface 调用，避免把用户建模逻辑写死在某个平台里。

### 自动化和人审分离

反馈回写和记忆总结可以自动化。Skill 更新、策略变化和流程调整初期需要人审。
