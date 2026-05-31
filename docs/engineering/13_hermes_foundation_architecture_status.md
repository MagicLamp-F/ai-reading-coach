# Hermes 基础架构与接入状态

## 1. 当前结论

截至 2026-05-31，`ai-reading-coach` 的 Hermes 基础接入已经完成第一阶段闭环：

```text
ai-reading-coach
  -> ReflectionAgentAdapter
  -> /home/ubuntu/projects/hermes-agent/bin/reflect-json
  -> hermes --oneshot
  -> 已配置的大模型 API
  -> reflection JSON
  -> SQLite reflections draft
```

这意味着：

- `hermes-agent` 已安装在主项目同级目录，不在 `ai-reading-coach` 子目录内。
- `ai-reading-coach` 已经能通过 adapter 调用外部 Hermes。
- Hermes 已经能完成真实模型推理。
- wrapper 已经能从 stdin 接收 JSON，并向 stdout 返回合法 reflection JSON object。
- `generate-reflection` 已经能生成 `draft` reflection。
- `approve-reflection` 和 `apply-reflection` 仍然必须人工执行。
- `run-daily` 不依赖 Hermes 实时调用，不会因为 Hermes 失败而中断。

当前基础搭建可以认为完成一半以上：长期记忆反思链路已经接通，快速读完包的 SQLite/artifact/飞书预览链路已经完成初版；更长期的 Hermes fast-read route adapter、OpenClaw 候选书来源和业务总览页面尚未开始。

## 2. 当前组件分工

| 组件 | 当前职责 |
| --- | --- |
| `ai-reading-coach` | 业务编排、定时任务、SQLite 事实层、飞书推送、反馈回写、人工审批 |
| SQLite | 推荐、反馈、画像、reflection draft、运行日志的 source of truth |
| `ReflectionAgentAdapter` | 统一 reflection agent 接口，隔离外部 agent 失败 |
| `HermesAgentCliAdapter` | 把 reflection 请求序列化为 stdin JSON，调用外部命令 |
| `reflect-json` | 把项目协议转换为 Hermes oneshot 调用，并校验/包装输出 |
| Hermes | 读取已配置模型，执行语义反思，生成 JSON 草稿 |
| 飞书 | 第一交互通道，负责每日推荐和反馈入口 |

关键原则不变：

```text
SQLite 保存事实。
Hermes 生成解释。
Python 后端负责控制、审计和人工审批。
```

Hermes 不直接写数据库，不直接写 `USER.md` / `MEMORY.md`，不直接发送飞书消息。

## 3. wrapper 是什么

`/home/ubuntu/projects/hermes-agent/bin/reflect-json` 是一个很薄的协议适配器，不是重新实现 Hermes。

它存在的原因是：`ai-reading-coach` 需要一种稳定的机器协议：

```text
stdin:  JSON request
stdout: JSON object
exit:   0 表示成功，非 0 表示 fallback
```

而 Hermes 原生 CLI 更偏向人类或 agent 交互：

```bash
hermes
hermes --oneshot "..."
hermes chat -q "..."
hermes-acp
hermes mcp serve
```

这些入口不是天然的 `stdin JSON -> stdout JSON` 业务协议，所以需要 wrapper 做四件事：

1. 接收 `ai-reading-coach` 传来的 reflection payload。
2. 拼成 Hermes 能理解的严格 prompt。
3. 调用 `hermes --oneshot`。
4. 校验 Hermes 输出，如果是 JSON 则透传和补齐字段；如果失败则以非 0 退出。

## 4. wrapper 的输入输出

`HermesAgentCliAdapter` 会向 wrapper 发送：

```json
{
  "task": "ai_reading_coach.reflection",
  "format": "json",
  "system_prompt": "...",
  "user_prompt": "...",
  "context": {},
  "output_contract": {},
  "constraints": {
    "do_not_apply_patches": true,
    "human_approval_required": true,
    "do_not_modify_sqlite": true,
    "do_not_send_messages": true
  }
}
```

wrapper 成功时必须输出一个 JSON object，字段兼容当前 reflection MVP：

```text
period_summary
accurate_observations
long_term_interest_changes
short_term_focus_changes
knowledge_gaps
reading_preferences
aversion_patterns
action_stage
system_misunderstandings
next_week_strategy
reflection_questions
user_md_patch
memory_md_patch
```

Python 后端随后负责规范化、入库和写草稿 Markdown。

当前 reflection payload 已在兼容旧 `task` 字段的同时，增加 route 化字段：

```text
route=reading.reflection.generate
domain=reading
memory_scope=user_profile, reading_profile, book_history
tool_policy=none
output_schema=reflection_v1
```

这只是 route 化协议的第一步，不改变 wrapper 调用方式；后续 `reading.fast_read_pack`、`reading.recommend.rank` 可以沿用同一结构。

## 5. Hermes 模型配置

当前模型配置通过 Hermes 自己的交互式配置完成，不再要求把模型 key 写进 `ai-reading-coach`。

推荐分工：

```text
Hermes 模型/provider/base_url/key:
  由 Hermes 自己的配置管理

ai-reading-coach:
  只保留如何调用 Hermes 的配置
```

`ai-reading-coach` 推荐配置：

```env
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180
```

wrapper 默认使用当前用户的 Hermes 配置：

```text
HERMES_HOME=/home/ubuntu/.hermes
```

如果后续需要隔离 profile，可以显式设置：

```env
HERMES_AGENT_HERMES_HOME=/home/ubuntu/projects/hermes-agent/.ai-reading-coach-hermes
```

但当前已验证的路径是跟随全局 Hermes 配置。

## 6. 安全边界

当前 wrapper 做了这些限制：

- Hermes 运行 cwd 固定为 `/home/ubuntu/projects/hermes-agent/runtime`。
- 不在 `ai-reading-coach` 项目目录内运行 Hermes。
- 调用 Hermes 时加 `--ignore-rules`，避免读取项目内 agent 规则。
- wrapper 不打印 API key。
- 失败时只打印 exit code、cwd、prompt length、stdout/stderr length 等脱敏诊断。
- `generate-reflection` 只生成 draft，不会自动 apply。

需要注意：Hermes oneshot 自身会采用非交互执行模式，因此仍要依赖 wrapper 的 cwd、prompt 约束和业务侧人审边界来降低风险。当前阶段不让 Hermes 直接拥有写数据库、发飞书或 apply memory 的权限。

## 7. 已验证结果

已经完成以下验证：

```text
直接 Hermes:
  /home/ubuntu/projects/hermes-agent/.venv/bin/hermes --oneshot 'Return exactly: hello' --ignore-rules
  -> hello

wrapper smoke:
  /home/ubuntu/projects/hermes-agent/bin/reflect-json --debug-smoke
  -> exit_code=0, stdout_length=6, visible_model_response=true

wrapper stdin JSON:
  stdin JSON request -> reflect-json
  -> 输出合法 reflection JSON object

主项目 reflection:
  HERMES_REFLECTION_PROVIDER=hermes-agent
  HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
  python3 -m app.cli generate-reflection --days 7 --no-lark
  -> Hermes reflection draft generated: id=3
```

生成结果：

```text
reflection id: 3
status: draft
period: 2026-05-24..2026-05-31
markdown: memory/reflections/reflection_3.md
```

这证明当前 Hermes 已经不仅是安装完成，而是完成了真实模型推理并返回了业务可消费的 reflection JSON。

## 8. 未完成事项

当前还没有做：

- 自动 approve/apply。这个仍然必须人工做。
- Hermes route 化协议。当前还是 reflection 专用 payload。
- `reading.recommend.rank`。
- `reading.fast_read_pack`。
- OpenClaw 候选书来源。
- reading-pack / summary / artifact 数据库表。
- 飞书应用机器人回调。
- 业务总览页面。

下一步建议优先级：

1. 保持当前 Hermes reflection 链路稳定运行 1-2 次。
2. 把 wrapper 协议升级成 route 化，但先只支持 `reading_coach.reflection`。
3. 设计 `reading.fast_read_pack` 输出 schema。
4. 增加文件 artifact 元数据表，开始沉淀每日 reading-pack。
5. 再考虑 OpenClaw 作为候选书和工具执行来源。

## 9. 回滚方式

如需回滚到当前自研 reflection：

```env
HERMES_REFLECTION_PROVIDER=custom
```

无需改飞书、SQLite、反馈服务或 daily recommendation。
