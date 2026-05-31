# hermes-agent 接入设计

## 1. 为什么做

当前项目已经有一版自研 Hermes Reflection MVP：Python 后端从 SQLite 读取推荐、反馈和画像事实，调用 OpenAI 兼容模型生成 reflection 草稿，再由人工审批后追加到 `memory/USER.md` 和 `memory/MEMORY.md`。

这版 MVP 能跑通闭环，但它把“长期记忆解释能力”写在项目内部，后续如果要接入真正的 `hermes-agent`、替换模型、扩展记忆策略或并行验证多个 agent，会出现几个问题：

- 外部 agent 和业务编排耦合。
- 失败边界不清晰，容易影响每日推荐。
- 输出契约没有独立定义，难以替换实现。
- 当前 custom reflection 没有明确 fallback 身份。

因此本阶段目标不是引入 OpenClaw，也不是重写推荐系统，而是先把 Hermes 反思能力抽象成可插拔 agent adapter。

## 2. 做成什么样

目标结构：

```text
SQLite facts / weekly report
  |
  v
Reflection Context Builder
  |
  v
ReflectionAgentAdapter
  |
  +--> hermes-agent CLI adapter
  |
  +--> custom LLM reflection fallback
  |
  v
reflections draft row
  |
  v
manual approve/apply or automatic approve/apply
  |
  v
memory/USER.md + memory/MEMORY.md
  |
  v
memory/change_logs/YYYY-MM-DD_reflection_<id>_<mode>.md
  |
  v
run-daily reads applied memory only
```

`hermes-agent` 在系统中的位置是 Python Orchestrator 后面的解释层。它不直接写 SQLite，不直接修改 `USER.md` / `MEMORY.md`，不发送飞书消息，不参与反馈回写。它只接收上下文，输出符合契约的 JSON 草稿。

## 3. 和当前 Reflection MVP 的关系

当前 `app/reflection.py` 继续保留这些职责：

- 构造 reflection run log。
- 读取 SQLite 事实并构造上下文。
- 调用 adapter 生成 JSON 草稿。
- 规范化输出字段。
- 写入 `reflections` 表。
- 写 `memory/reflections/reflection_{id}.md` 草稿。
- 可选发送飞书“待人工确认”摘要。
- 执行手动 `approve-reflection` / `apply-reflection`，或在开启配置后自动 approve/apply。
- 自动 apply 时写入 `memory/change_logs` 审计文件。

新增的 `app/reflection_adapter.py` 只负责生成草稿：

- `CustomLLMReflectionAdapter`：保留现有模型生成逻辑。
- `HermesAgentCliAdapter`：通过本机命令调用 `hermes-agent`，用 stdin 传入 JSON payload，从 stdout 读取 JSON。
- `FallbackReflectionAdapter`：`hermes-agent` 失败时自动回退到 custom LLM reflection。

默认配置仍是 `custom`，因此不部署 hermes-agent 时，现有行为不变。

## 4. 输入数据来自哪里

输入由 Python 后端统一构造，避免外部 agent 直接读取数据库：

- `recommendations`：最近周期内的推荐、书名、主题、系统假设、画像维度、收益和风险。
- `feedback_events`：反馈类型、原因、自由文本、关联推荐和系统假设。
- `profile_items`：结构化画像、权重、置信度、证据数和最近证据。
- weekly report：当前系统已有的 7 天画像复盘摘要。
- aggregate signals：反馈类型分布、原因分布、正反馈主题、误读信号。

`hermes-agent` 收到的 payload 包含：

- `task`
- `format`
- `system_prompt`
- `user_prompt`
- `context`
- `output_contract`
- `constraints`

约束明确写入 payload：

- agent 不直接 apply patch。
- 是否自动 apply 由 Python 后端配置控制。
- 不修改 SQLite。
- 不发送消息。

## 5. 输出数据写到哪里

adapter 输出必须是 JSON object，字段与当前 reflection MVP 兼容：

- `period_summary`
- `accurate_observations`
- `long_term_interest_changes`
- `short_term_focus_changes`
- `knowledge_gaps`
- `reading_preferences`
- `aversion_patterns`
- `action_stage`
- `system_misunderstandings`
- `next_week_strategy`
- `reflection_questions`
- `user_md_patch`
- `memory_md_patch`

Python 后端把输出规范化后写入：

- `reflections` 表：状态为 `draft`。
- `memory/reflections/reflection_{id}.md`：便于人工审查。
- `run_logs`：记录本次 adapter 和失败信息。

只有 `apply-reflection` 会追加写入：

- `memory/USER.md`
- `memory/MEMORY.md`

## 6. 必须人工审批的步骤

默认情况下仍可人工执行：

- `approve-reflection --id <id>`：把草稿从 `draft` 标记为 `approved`。
- `apply-reflection --id <id>`：只允许对 `approved` 草稿追加写入长期记忆。

禁止行为：

- `hermes-agent` 自己直接 apply。
- `hermes-agent` 直接写 `USER.md` / `MEMORY.md`。
- `hermes-agent` 直接更新画像表。
- 让 daily recommendation 使用 draft reflection。

如果用户希望全链路自动化，可以启用：

```env
HERMES_REFLECTION_AUTO_APPLY=true
DAILY_REFLECTION_ENABLED=true
DAILY_REFLECTION_DAYS=1
```

此时 `run-daily` 完成推荐后会自动生成 reflection，自动 approve/apply，并写入 `memory/change_logs`。失败只记录 warning，不中断日推。

## 7. 失败降级策略

必须隔离失败边界：

- `run-daily` 不调用 hermes-agent。它只读取已经应用的 `USER.md` / `MEMORY.md`，读取失败则使用“暂无 Hermes long-term memory”。
- `generate-reflection` 使用 `HERMES_REFLECTION_PROVIDER=hermes-agent` 时，如果 hermes-agent 命令不存在、超时、退出非 0 或输出非 JSON，会自动 fallback 到 `custom`。
- fallback 信息写入 `run_logs.warning_message`。
- 如果 primary 和 fallback 都失败，只标记本次 `hermes_reflection` run 为 `failed`，不写 reflection 草稿，不影响每日推荐和反馈链路。
- 飞书待确认摘要发送失败只记录 warning，不影响草稿入库。

## 8. 配置与切换

默认配置：

```env
HERMES_REFLECTION_PROVIDER=custom
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=60
HERMES_REFLECTION_AUTO_APPLY=false
DAILY_REFLECTION_ENABLED=false
DAILY_REFLECTION_DAYS=1
```

切到 hermes-agent：

```env
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=60
```

回滚到自研 reflection：

```env
HERMES_REFLECTION_PROVIDER=custom
```

切换后无需改 Feishu、SQLite 或 daily recommendation 代码，只影响 `generate-reflection`。

## 9. 操作流程

生成草稿：

```bash
python3 -m app.cli generate-reflection --days 7
```

生成并自动应用：

```bash
python3 -m app.cli generate-reflection --days 1 --auto-apply
```

查看草稿：

```bash
python3 -m app.cli list-reflections
python3 -m app.cli show-reflection --id <id>
```

人工确认后审批：

```bash
python3 -m app.cli approve-reflection --id <id>
```

人工确认后应用：

```bash
python3 -m app.cli apply-reflection --id <id>
```

验证 daily 是否使用已应用记忆：

```bash
python3 -m app.cli run-daily
```

## 10. 验收标准

- 默认 `HERMES_REFLECTION_PROVIDER=custom` 时，现有 reflection 流程行为不变。
- 设置 `HERMES_REFLECTION_PROVIDER=hermes-agent` 后，`generate-reflection` 会先调用 hermes-agent。
- hermes-agent 成功时，输出写入 `reflections` 的 `draft` 记录。
- hermes-agent 失败时，自动 fallback 到 custom reflection，并在 run log 写 warning。
- primary 和 fallback 都失败时，只失败本次 reflection run，不影响 `run-daily`。
- 默认人工 approve/apply 仍可用；启用 `HERMES_REFLECTION_AUTO_APPLY=true` 后可自动 apply。
- 自动 apply 必须写入 `memory/change_logs` 审计文件。
- draft reflection 不会进入每日推荐上下文；只有已应用的 `USER.md` / `MEMORY.md` 会被 `run-daily` 读取。
- Feishu 推送、反馈链接、SQLite 画像回写和 weekly report 不被修改。
