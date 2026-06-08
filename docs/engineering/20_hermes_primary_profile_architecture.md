# Hermes 主画像架构设计

## 1. 核心结论

长期目标采用“方案 C”：

```text
Hermes native memory = 主画像系统
ai-reading-coach = 阅读业务账本、证据库、触达和反馈系统
```

这意味着 ARC 不应该把自己推断出的 `profile_items` 当作最高优先级的“用户本人画像”。ARC 可以保存阅读推荐、反馈、点击、阅读进度和审计记录，但用户长期偏好、思维模式、阶段状态和原生个人画像应优先由 Hermes 维护。

当前 ARC 已经能维护一套结构化画像，但这套画像主要服务阅读推荐闭环。它有价值，但不能替代 Hermes 对用户跨场景、跨会话、跨任务的长期理解。

## 2. 为什么不能只靠 ARC 自己画像

ARC 当前画像来源主要是：

```text
data/reading_coach.db
  -> profile_items
  -> feedback_events
  -> recommendations

memory/USER.md
memory/MEMORY.md
```

这套系统的问题是：

- 数据来源只覆盖阅读推荐和反馈，不覆盖用户在 Hermes 原生 chat 中表达的长期目标、人格偏好、表达习惯和真实上下文。
- 画像生成逻辑由 ARC prompt 和规则驱动，容易把阅读场景里的短期偏好误判成全局偏好。
- ARC 的 reflection wrapper 当前明确禁止 Hermes 修改 memories，因此 Hermes 即使参与生成，也只是一次性 JSON 输出者。
- Hermes UI、Hermes CLI 和 ARC 之间会出现多套 profile/memory，各自理解用户。

用户的核心需求不是“ARC 生成更多画像”，而是“ARC 推荐和阅读系统更还原 Hermes 已经理解的那个我”。

## 3. 目标分工

| 组件 | 主职责 | 不应承担 |
| --- | --- | --- |
| Hermes native memory | 主用户画像、长期记忆、自我理解、跨场景偏好 | 业务事实数据库、飞书投递、幂等控制 |
| ARC SQLite | 推荐记录、反馈事件、阅读进度、证据链、审计记录 | 最高优先级人格画像 |
| ARC memory files | ARC 对阅读系统的已应用反思和策略记录 | Hermes 原生个人画像替代品 |
| Hermes Web UI / CLI | 原生对话、长期记忆更新、画像解释 | ARC 业务页面和投递可靠性 |
| ARC workflow | 定时、搜索、推荐展示、反馈采集、失败降级 | 黑箱式自动改写用户主画像 |

主从关系：

```text
Hermes native profile
  -> ARC 读取为最高优先级上下文

ARC feedback events
  -> 作为证据发送给 Hermes
  -> Hermes 判断是否进入长期画像

ARC profile_items
  -> 阅读业务局部画像
  -> 只作为低优先级补充或候选假设
```

## 4. 推荐调用链

目标调用链：

```text
run-daily
  -> ARC 读取业务事实
       - 最近推荐
       - 反馈事件
       - 阅读进度
       - 推荐失败/误读信号
  -> ARC 读取 Hermes native profile snapshot
       - SOUL.md
       - Hermes memory export
       - Hermes profile summary
  -> ARC 调用 Hermes
       - 请求 Hermes 基于原生画像和业务证据生成推荐意图/排序/解释
       - 通过专门的 profile-update route 判断是否更新 native memory
  -> ARC 写业务结果
       - recommendations
       - reading_packs
       - delivery outbox
       - run_logs
```

prompt 上下文必须显式分层：

```text
Priority 1: Hermes native profile
Priority 2: User explicit ARC feedback
Priority 3: ARC structured reading profile
Priority 4: ARC inferred hypotheses
Priority 5: Single-run weak signals
```

禁止把所有上下文混成一段“用户画像”，否则模型无法区分原生事实、业务事实、推断和假设。

## 5. 反馈回写链路

用户在飞书或 ARC 页面反馈后，ARC 应保存原始事实：

```text
feedback_events
  - recommendation_id
  - feedback_type
  - reason_code
  - free_text
  - source channel
  - created_at
```

然后把事件作为证据交给 Hermes：

```text
reading.feedback.ingest
  input:
    - feedback event
    - related recommendation
    - previous Hermes native profile summary
    - recent ARC reading facts
  output:
    - whether native memory should update
    - proposed memory delta
    - confidence
    - evidence ids
```

Hermes 可以自己维护主画像，但必须满足两个约束：

- 只有明确反馈、多次行为或高价值自述才写入长期记忆。
- 每次写入都要产生 ARC 可记录的审计事件，至少包括 route、摘要、证据、时间和状态。

## 6. 当前 wrapper 需要调整的地方

当前 `/home/ubuntu/projects/hermes-agent/bin/reflect-json` 的调用方式适合“安全 JSON 生成”，但不适合“让 Hermes 自己维护画像”，因为它明确包含：

```text
Do not modify files, databases, memories, messages, network channels, or apply patches.
```

因此需要新增一类 route，而不是直接改掉所有现有 route：

| Route | 是否允许写 Hermes memory | 用途 |
| --- | --- | --- |
| `reading.recommend.intent` | 否 | 生成搜索/推荐主题 |
| `reading.recommend.generate` | 否 | 生成候选推荐 |
| `reading.fast_read_pack` | 否 | 生成阅读包 |
| `reading.reflection.generate` | 否 | 生成 ARC reflection 草稿 |
| `reading.feedback.ingest` | 否，Hermes 只返回决策；ARC 受控写入 | 把明确反馈交给 Hermes 判断是否更新主画像 |
| `reading.profile.sync_snapshot` | 否 | 从 Hermes 主画像生成 ARC 可读 snapshot |

这样可以保留当前安全边界，同时给主画像更新开一个可审计、可限流、可回滚的专门通道。

2026-06-07 已采用更保守的落地方式：`reading.feedback.ingest` 的 prompt 仍禁止 Hermes 直接改文件或 memory，Hermes 只返回 `profile_update_v1` 决策；ARC 业务编排层校验结果后，只 upsert `/home/ubuntu/.hermes/memories/USER.md` 中带 `[arc-reading-profile]` 标记的单条 entry，并写入 SQLite 审计表。

## 7. Hermes Native Profile Snapshot 与 Native USER Memory

ARC 不应每次直接解析大量 Hermes chat 历史。更稳妥的是维护一个 ARC 可读 snapshot：

```text
memory/HERMES_NATIVE_PROFILE.md
```

内容由 Hermes 原生画像导出或摘要生成：

```markdown
# HERMES_NATIVE_PROFILE

## Stable Identity

## Long-term Interests

## Reading Preferences

## Thinking Style

## Current Stage

## Aversion Patterns

## Open Questions

## Source Notes
```

ARC daily prompt 优先读取这个 snapshot。snapshot 只作为上下文，不直接覆盖 ARC SQLite。

从 2026-06-05 起，ARC 还会把这份 Hermes 生成的阅读画像同步为 Hermes built-in user memory：

```text
/home/ubuntu/.hermes/memories/USER.md
```

Hermes 的 built-in memory 是文件型存储，`USER.md` 和 `MEMORY.md` 位于当前 `HERMES_HOME/memories/` 下，entry 使用 `§` 分隔。ARC 只维护一条带标记的 entry：

```text
[arc-reading-profile] User reading profile: ...
```

同步策略：

- `memory/HERMES_NATIVE_PROFILE.md` 缺失或占位时，Hermes 先通过 `reading.profile.sync_snapshot` 基于 ARC evidence 生成 snapshot。
- 如果 Hermes 同时返回 `hermes_user_memory_entry`，ARC 使用该 compact entry 写入 native `USER.md`。
- 如果已有 snapshot，ARC 会从 snapshot 派生 compact entry 并 upsert 到 native `USER.md`。
- upsert 只替换 `[arc-reading-profile]` 这一条，保留 Hermes UI/CLI 里已有的其它 USER memories。
- 写入超出 Hermes user memory 字符上限、路径不可写或内容包含注入风险时，流程直接失败，不走 fallback。

注意：Hermes 会在新会话启动时冻结读取 built-in memory。写入 `USER.md` 后，已经打开的 UI 会话不一定立刻把新画像注入 prompt；新会话或重启 bridge 后才会稳定生效。

后续可以从这些来源生成 snapshot：

- `/home/ubuntu/.hermes/SOUL.md`
- Hermes native memory export
- Hermes selected session summaries
- 用户手动确认过的长期画像

## 8. 防污染原则

主画像系统最危险的问题是“模型把短期噪声写成长期事实”。必须执行以下规则：

- 单次 dislike 不改长期画像，只记录为候选信号。
- 单次 like 可增强主题置信度，但不直接定义稳定偏好。
- 自由文本优先级高于按钮反馈。
- 用户明确自述优先级高于模型推断。
- ARC 推断永远低于 Hermes native profile。
- 互相冲突时生成 `known_conflicts`，不要静默覆盖。
- 自动写 Hermes memory 前必须有 evidence summary。
- 敏感信息默认不写长期记忆。

## 9. 实施阶段

### Phase 1: 只读对齐 + native USER memory 同步

目标：让 ARC 推荐先使用 Hermes 原生画像，并把 Hermes 生成的阅读画像同步到 Hermes built-in USER memory。

任务：

- 新增 `HermesNativeProfileProvider`。
- 读取 `memory/HERMES_NATIVE_PROFILE.md`。
- 如果文件不存在，调用 `reading.profile.sync_snapshot`，以 ARC SQLite reading profile 和 ARC applied memory 为主证据生成初始 snapshot。
- 将 snapshot/upsert entry 同步到 `/home/ubuntu/.hermes/memories/USER.md`。
- 修改 daily profile context，把 Hermes native profile 放在最高优先级。
- 保留 ARC `profile_items`，但标记为 `ARC inferred reading profile`。

验收：

- run-daily 的 prompt 中能看到 Hermes native profile 在最前面。
- ARC 推荐理由明确映射到 native profile 或 ARC feedback。
- Hermes native `USER.md` 出现 `[arc-reading-profile]` entry。
- native profile 生成或 USER memory 写入失败时系统失败暴露，不静默降级。

### Phase 2: 反馈证据上送

目标：ARC 把阅读反馈交给 Hermes 判断，不再只由 ARC 自己沉淀画像。

任务：

- 新增 `reading.feedback.ingest` route。已完成。
- `run-daily` 开始时处理未处理反馈，调用 Hermes。已完成。
- Hermes 返回 `should_update_native_memory`、`memory_entry`、`rationale`、`confidence`、`evidence_summary`。已完成。
- ARC 记录 `hermes_profile_update_events` 审计表。已完成。
- `/metrics` 暴露 `reading_coach_hermes_profile_updates_total{status=...}`。已完成。

验收：

- 每条关键反馈都有可追踪的 Hermes ingest 结果。
- Hermes ingest 失败会记录 `failed` 审计行，并让本次 `run-daily` 失败；不走 fallback，也不把反馈标记 processed。
- 没有证据的推断不写入 native memory。

### Phase 3: Hermes 主画像写入

目标：允许 Hermes 判断画像增量，由 ARC 在受控 route 中写入 native memory。

任务：

- 保留 Hermes 直接 memory 写入禁令，避免 route agent 黑箱改文件。已决定。
- 限制 ARC 只写 `[arc-reading-profile]` 单条 entry。已完成。
- 增加审计表和 Prometheus status 计数。已完成。
- 增加备份、回滚和每日写入次数限制。待做。

验收：

- Hermes native memory 出现可解释增量。
- ARC 审计记录能说明“为什么写入”。
- 写入失败直接暴露并中断，不写 fallback 画像。

### Phase 4: 主从收敛

目标：ARC 不再把局部画像当成主画像，而是把它作为证据和业务视图。

任务：

- `profile_items` 增加 source/confidence/source_priority 语义。
- 标记 `hermes_native`、`arc_explicit_feedback`、`arc_inferred`。
- 推荐解释中展示来源层级。
- 周报区分“原生画像变化”和“阅读业务画像变化”。

验收：

- 用户能看到某条画像来自 Hermes 原生记忆、明确反馈还是 ARC 推断。
- 推荐错误能追溯是 native profile 错、ARC 推断错，还是候选书源错。

## 10. 当前配置含义

当前已开启：

```env
DAILY_REFLECTION_ENABLED=true
HERMES_REFLECTION_AUTO_APPLY=true
```

这只表示：

```text
run-daily 后 ARC 会自动生成 reflection
并自动写入 ARC memory/USER.md 和 memory/MEMORY.md
```

它不表示：

```text
Hermes native memory 会自动学习 ARC 反馈
Hermes UI chat 的个人画像会自动同步到 ARC
ARC 已经以 Hermes native profile 为主画像
```

因此这两个开关是 ARC 画像增强开关，不是主画像对齐方案。

当前已完成的是两条受控路径：

- snapshot -> Hermes native `USER.md` 的 `[arc-reading-profile]` 同步。
- 反馈事件 -> Hermes `reading.feedback.ingest` 决策 -> `hermes_profile_update_events` 审计 -> 可选 upsert 同一条 native `USER.md` entry。

这仍不表示 Hermes route agent 可以任意写 memory。所有文件写入由 ARC 编排层执行，失败必须暴露。

## 10.1 每日 intent route 加固

`reading.recommend.intent` 是只读主题决策 route，不负责画像写入、推荐落库或消息发送。2026-06-08 的加固规则如下：

- 输出升级为 `themes_v2`：`{"themes":[{"theme":"主题1","slot":"profile_fit","reason":"..."}, ...]}`；ARC adapter 仍兼容旧 `themes_v1` 字符串列表。
- 主题语义顺序固定：前 2 个为 `profile_fit`，第 3 个为 `exploration`。
- 当画像证据支持时，今日主题至少覆盖 1 个文学/经典名著方向，至少覆盖 1 个科幻经典方向。
- 工程技术、商业、效率工具书和 AI Agent 商业化不能占满今日主题；如果推荐历史显示高频疲劳且没有新正反馈，应降频。
- 主题必须能直接指导下游选书，不能只是“人生意义”“技术与社会”这类过抽象兴趣标签。
- Hermes payload 会先提供 `effective_profile_summary`，再提供有长度上限的原始 `profile_context`，减少重复 reflection 历史对主题选择的污染。
- `reading.recommend.generate` 会收到 `theme_intents`，因此候选书筛选不再只依赖主题顺序推断 slot 和推荐理由。
- 该 route 的 constraints 显式禁止修改 SQLite、文件、memory、消息、网络通道和 patches；所有副作用仍由 ARC 执行。

## 11. 最终验收标准

- ARC daily recommendation 明确使用 Hermes native profile 作为最高优先级上下文。
- ARC 不再把自己的 `profile_items` 伪装成用户完整画像。
- Hermes 可以从 ARC 反馈中学习，但写入路径受控、可审计、可回滚。
- 用户能区分原生画像、明确反馈、ARC 推断和待验证假设。
- Hermes UI、Hermes CLI 和 ARC 对“用户是谁”的理解逐步收敛。
- 任一组件失败时，原始反馈和推荐事实不会丢失。
