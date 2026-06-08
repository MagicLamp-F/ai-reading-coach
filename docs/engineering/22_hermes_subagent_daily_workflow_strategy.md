# Hermes 子 Agent 与 Daily Workflow 策略

更新时间：2026-06-08

实现状态：

- 2026-06-08：已落地 `reading.recommend.review_v1` shadow 路径。默认关闭，可通过 `ARC_ENABLE_RECOMMEND_REVIEW_SHADOW=true` 或 `ReadingCoachWorkflow(..., recommend_review_shadow_enabled=True)` 启用。输出写入 `artifacts`，artifact type 为 `recommendation_review`，本地 JSON 路径位于 `library/recommendation-reviews/YYYY/MM/`。
- 2026-06-08：已落地候选过滤解释 artifact。每次 `run-daily` 会写 `recommendation_candidate_explainability` artifact，记录候选书是否 selected/rejected、`excluded_by`、source-aware 分数、source status 和 reject reason。本地 JSON 路径位于 `library/recommendation-decisions/YYYY/MM/`。

## 1. 核心结论

不应该让 Hermes 子 agent 承接 `ai-reading-coach` 的完整 `run-daily` workflow。

推荐长期边界是：

```text
ARC = business orchestrator / source of truth / fact ledger / delivery runtime
Hermes = bounded JSON decision layer / profile reasoning layer / content generator
Hermes subagents = bounded planners / reviewers / candidate expanders / fact checkers
```

也就是：

```text
不推荐：
ARC -> Hermes 主 agent -> 子 agents 自主完成完整 daily workflow
    -> 写库 / 投递 / 更新画像 / 控制 run 状态

推荐：
ARC -> 构造严格上下文、预算、schema 和权限边界
    -> 调 Hermes bounded route
    -> Hermes 可在局部 route 内使用受限子 agent 做规划、审查、候选扩展和事实核验
    -> ARC 校验、过滤、排序、落库、更新 USER.md、写 artifact、飞书 delivery 和审计
```

一句话判断：

```text
不要把 ARC daily workflow agent 化；
要把 Hermes subagent 产品化为 ARC 可调用的受控 review / plan / fact-check route。
```

## 2. 项目真实需求与边界

`ai-reading-coach`，简称 ARC，不是单纯的每日推荐脚本，而是个人阅读推荐、读书包生成、反馈画像更新的长期闭环系统：

```text
Hermes native USER.md [arc-reading-profile] 主画像
-> ARC 从 SQLite 推荐/反馈历史构造 RecommendationHistoryContext
-> Hermes 生成主题、推荐、读书包和画像更新决策
-> ARC 写 SQLite、artifact、飞书 delivery/outbox、审计和硬校验
-> 用户反馈进入下一轮画像与推荐
```

ARC 当前负责：

- `run_logs` 生命周期和失败状态。
- SQLite 事实表：`recommendations`、`books`、`feedback_events`、`profile_items`、`reading_packs`、`artifacts`、`book_sources`、`hermes_profile_update_events`。
- 未处理反馈的状态迁移。
- `RecommendationHistoryContext` 构造：hard exclusions、negative feedback、positive anchors、history fatigue、recent recommendations。
- Tavily 和公开来源搜索。
- hard-exclusion 过滤、source-aware ranking、候选入库。
- reading pack artifact 写入 `library/`。
- 飞书投递、delivery outbox 和重试。
- Hermes native `USER.md` 中 `[arc-reading-profile]` 的受控 upsert。

Hermes 当前负责：

- `reading.feedback.ingest`：返回 `profile_update_v1` 决策。
- `reading.recommend.intent`：生成 2 个 `profile_fit` + 1 个 `exploration` 今日主题。
- `reading.recommend.generate`：生成候选书及推荐理由。
- `reading.deep_read_pack`：生成结构化读书包。
- reflection 和主画像判断。

关键原则：

```text
Hermes can propose.
ARC validates, persists, delivers, audits, and applies.
```

## 3. 当前 Runtime 现实

ARC 当前通过：

```text
/home/ubuntu/projects/hermes-agent/bin/reflect-json
```

调用 Hermes。

`reflect-json` 本质是：

```bash
hermes --oneshot <prompt> --ignore-rules
```

它要求 Hermes 只返回 JSON，并且当前 wrapper 禁用或不使用：

```text
delegation
memory
terminal
file
browser
web
session_search
```

`app/daily_agent_adapter.py` 中也明确记录：

```text
hermes_internal_thread = not_supported_by_current_reflect_json_wrapper
```

所以当前 `run-daily` 不是 Hermes native thread，也不是 Hermes 主 agent 编排子 agent。ARC 的 `local_session.previous_turns` 只是显式塞进下一次 payload 的局部上下文，不是 Hermes 原生多轮会话。

因此，直接让 Hermes 子 agent 承接完整 daily workflow 不是小改 adapter，而是引入新的 agent execution runtime。

## 4. 为什么不让子 Agent 接管完整 Daily

### 4.1 ARC 是事实账本

完整 daily workflow 涉及：

- feedback 是否处理过。
- 推荐是否已入库。
- hard exclusions 是否命中。
- reading pack artifact 是否生成。
- 飞书是否已投递或进入 outbox。
- Hermes profile update 是否已审计。
- run 是否应标记成功、失败或部分成功。

这些是确定性业务状态，不应交给 LLM agent 黑箱维护。

### 4.2 画像更新必须受控

当前正确链路是：

```text
feedback_events(processed_at IS NULL)
-> Hermes reading.feedback.ingest
-> profile_update_v1
-> ARC validates
-> hermes_profile_update_events
-> ARC controlled upsert native USER.md [arc-reading-profile]
-> ARC profile_items
-> feedback_events.processed_at
```

不应改成：

```text
Hermes 子 agent 读反馈后自行改 USER.md / memory
```

否则单次弱信号可能被长期化，造成主画像污染。

### 4.3 Hard Exclusions 是规则，不是建议

Hermes 可以理解 hard exclusions，但最终必须由 ARC deterministic code 执行过滤。推荐历史、负反馈、近期重复和已读状态不能只靠 prompt 约束。

### 4.4 Delivery 是副作用

飞书投递、outbox 和 retry 需要幂等、重试、状态机和审计。Hermes 可以生成内容，不应直接发消息或更新投递状态。

### 4.5 Daily 是长期自动任务

每日自动任务更需要：

- 可回放。
- 可审计。
- 可限流。
- 可失败隔离。
- 可成本估算。
- 可 schema validation。
- 可回滚。

Hermes 子 agent 的优势是开放性 reasoning，不是业务流程状态机。

## 5. 适合交给 Hermes 子 Agent 的环节

### 5.1 推荐计划

新增候选 route：

```text
reading.recommend.plan_v1
```

职责：

- 解释当前主画像和推荐历史。
- 规划 2 个 `profile_fit` + 1 个 `exploration` slot。
- 输出搜索 query、候选标准、风险控制。
- 明确哪些主题需要避免历史疲劳。

它只作为 ARC 搜索和生成的 hint，不直接落库。

### 5.2 推荐审查

新增候选 route：

```text
reading.recommend.review_v1
```

职责：

- 检查候选书是否真是书，而不是文章、课程或网页。
- 检查是否命中 hard exclusions 或 history fatigue。
- 检查是否符合用户偏好：偏好书籍本身、技术内容需要开始路径、避免连续重复大部头。
- 检查 2 `profile_fit` + 1 `exploration` 结构是否成立。
- 输出 keep/remove/replace/needs_check 建议。

### 5.3 候选扩展

子 agent 可以按主题拆分：

```text
profile_fit_candidate_agent_1
profile_fit_candidate_agent_2
exploration_candidate_agent
```

每个子 agent 只生成候选和理由，主 Hermes route 汇总，ARC 再执行硬校验、来源评分和入库。

### 5.4 事实核验

未来可用 verifier 子 agent 检查：

- 书名是否真实。
- 作者是否匹配。
- 中文译名是否常见。
- source URL 是否支持该书存在。
- 推荐理由是否和书本实际内容匹配。

但 verifier 只能返回 `verified|uncertain|unverified`，不能直接决定落库。

### 5.5 Reading Pack 质量审查

子 agent 可审查：

- 是否有“从哪里开始读”。
- 是否过于空泛。
- 是否连接用户实践、个人发展或现实行动路径。
- 是否把书籍内容误写成泛泛推荐语。

ARC 仍负责写 `reading_packs`、`artifacts` 和 `library/`。

### 5.6 Shadow Evaluation

最适合的第一步是 shadow mode：

```text
正式结果：当前 ARC baseline
影子结果：Hermes agentic review / agentic recommendation
用途：只做对比，不投递、不写主表、不改 memory
```

## 6. 不适合交给 Hermes 子 Agent 的环节

以下环节应保持 ARC 独占：

- SQLite 写入：`recommendations`、`books`、`feedback_events`、`profile_items`、`reading_packs`、`artifacts`、`run_logs`。
- `feedback_events.processed_at` 更新。
- `hermes_profile_update_events` 审计写入。
- native `USER.md` 中 `[arc-reading-profile]` 的 upsert。
- hard-exclusion 最终过滤。
- source-aware ranking 最终执行。
- reading pack artifact 文件写入。
- 飞书投递、delivery outbox 和 retry。
- run-level 成功/失败状态。
- 任意 code patch、配置修改或业务文件写入。

## 7. 实施路线

### Phase 0: 固定当前生产边界

保持：

```text
ARC orchestration
Hermes reflect-json oneshot JSON route
no delegation / memory / file / terminal / browser / web / session_search
```

补充可观测性：

- route name。
- prompt version。
- input hash / output hash。
- schema validation result。
- model/provider。
- latency。
- candidate count。
- hard exclusion hits。
- fatigue hits。
- source confidence。

### Phase 1: 新增 Review Route

新增：

```text
reading.recommend.review_v1
```

建议先不开子 agent，仍使用 oneshot JSON。

调用位置：

```text
recommend.generate
-> ARC 初步 hard exclusion
-> review_v1
-> ARC final ranking / persist
```

初期可只 shadow，不改变正式投递。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.review_recommendations()
  -> route: reading.recommend.review_v1
  -> output_schema: recommendation_review_v1

app/recommendation_review.py
  -> RecommendationReviewShadowService
  -> 负责开关判断、调用 adapter、记录 cost、写 recommendation_review artifact

app/workflow.py
  -> generate candidates
  -> hard exclusion
  -> source-aware ranking
  -> recommendation review shadow
  -> recommendations / reading packs / delivery
```

失败边界：

```text
review_v1 shadow 失败只写 run warning，不影响正式 daily 推荐、入库、reading pack 或投递。
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_reviews_recommendations_with_shadow_route_payload` 验证 Hermes payload 使用 `route=reading.recommend.review_v1`、`output_schema=recommendation_review_v1`，并保留 no-side-effect constraints。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_recommendation_review_shadow_artifact_when_enabled` 验证启用 shadow 后，daily run 仍成功，review 输出写入 `artifacts.artifact_type='recommendation_review'`，并记录 `cost_logs.operation='reading.recommend.review_v1'`。

输出示例：

```json
{
  "schema_version": "recommendation_review_v1",
  "verdict": "accept",
  "candidate_reviews": [
    {
      "candidate_id": "string",
      "status": "keep",
      "reasons": ["string"],
      "profile_fit_score": 0.82,
      "fatigue_risk": "low",
      "start_path_quality": "good",
      "resource_type_risk": "none"
    }
  ],
  "global_warnings": [],
  "revision_instructions": []
}
```

### Phase 2: 新增 Plan Route

新增：

```text
reading.recommend.plan_v1
```

输出示例：

```json
{
  "schema_version": "recommendation_plan_v1",
  "slots": [
    {
      "slot_type": "profile_fit",
      "theme": "经典科幻中的文明想象与技术伦理",
      "search_queries": ["经典科幻 文明想象 技术伦理 书籍"],
      "candidate_criteria": ["必须是书籍", "有明确阅读入口"],
      "risk_controls": ["避免最近重复主题", "避免纯技术文章"]
    }
  ]
}
```

ARC 使用方式：

- 作为 Tavily query hint。
- 作为 recommend.generate input。
- 作为 review 对照。
- 不替代 hard exclusion 和 ranking。

### Phase 3: Agentic Shadow Mode

新增实验 route：

```text
reading.recommend.agentic_shadow_v1
```

配置默认关闭：

```env
ARC_ENABLE_AGENTIC_SHADOW=false
ARC_AGENTIC_SHADOW_MAX_SUBAGENTS=2
ARC_AGENTIC_SHADOW_TIMEOUT_SECONDS=90
ARC_AGENTIC_SHADOW_ALLOW_WEB_SEARCH=false
ARC_AGENTIC_SHADOW_ALLOW_MEMORY=false
ARC_AGENTIC_SHADOW_ALLOW_FILE=false
ARC_AGENTIC_SHADOW_ALLOW_TERMINAL=false
ARC_AGENTIC_SHADOW_ALLOW_SESSION_SEARCH=false
```

shadow 子任务：

- profile/history reviewer。
- candidate source reviewer。
- reading pack reviewer。

约束：

- 不参与正式推荐。
- 不投递。
- 不写 native `USER.md`。
- 不写主业务表。
- 输出只写 artifact / audit JSON。

### Phase 4: 复杂场景有限启用

只有 shadow 数据证明有收益后，才允许复杂场景使用 agentic route。

触发条件示例：

```python
def should_use_agentic_recommendation(ctx):
    return any([
        ctx.candidate_count < MIN_CANDIDATES,
        ctx.history_fatigue_score > THRESHOLD,
        ctx.negative_feedback_recently,
        ctx.theme_intents_are_cross_domain,
        ctx.review_verdict in {"revise", "reject"},
        ctx.exploration_intent_confidence < THRESHOLD,
    ])
```

即使启用，权限仍是：

```text
Hermes suggests.
ARC executes.
```

### Phase 5: 有限 Gating

未来可选：

```env
ARC_ENABLE_REVIEW_GATING=false
```

允许 Hermes review 返回：

- `request_regenerate_slot`
- `warn_delivery`
- `suggest_block_delivery`

但最终执行必须由 ARC 本地规则确认。

## 8. TODO List

### P0: 文档和边界

- [ ] 新增/更新 Hermes 与 ARC 边界说明，明确 ARC owns SQLite、delivery、run state、memory application。
- [ ] 在 adapter 文档中明确 `reflect-json` 是 oneshot，不是 Hermes native thread。
- [ ] 把 `local_session.previous_turns` 命名为 explicit payload context，避免误解为 Hermes session。

### P1: Capability 建模

- [ ] 为 daily adapter 增加 capability object：

```json
{
  "runtime": "reflect-json",
  "supports_native_thread": false,
  "supports_delegation": false,
  "supports_memory": false,
  "supports_file": false,
  "supports_terminal": false,
  "supports_web": false,
  "supports_session_search": false,
  "side_effects_allowed": false
}
```

- [ ] 将 capability 写入 run artifact 或 run metadata。

### P1: Review Route

- [x] 定义 `recommendation_review_v1` schema。
- [x] 新增 Hermes daily adapter 方法 `review_recommendations()`。
- [x] 新增配置 `ARC_ENABLE_RECOMMEND_REVIEW_SHADOW=false`。
- [x] review route 失败时不影响 daily。
- [x] review 输出写 artifact。
- [x] review route 记录 `cost_logs.operation='reading.recommend.review_v1'`。

### P1: Hard Constraint Explainability

- [x] 记录每个候选被过滤或选中的原因。
- [x] 输出 `excluded_by`：hard exclusion、source confidence / source reject reason、not selected。
- [x] 将过滤解释写入 run artifact，方便和 agentic shadow 对比。
- [x] artifact type 为 `recommendation_candidate_explainability`，schema 为 `recommendation_candidate_explainability_v1`。

当前实现：

```text
app/recommendation_explainability.py
  -> RecommendationCandidateExplainabilityService
  -> 输出 candidate_count / selected_count / decisions

app/workflow.py
  -> 保留 raw_candidates
  -> 计算 hard_exclusion_keys
  -> source-aware ranking 写 recommendation_candidates
  -> 写 recommendation_candidate_explainability artifact
```

输出示例：

```json
{
  "schema_version": "recommendation_candidate_explainability_v1",
  "run_id": 123,
  "candidate_count": 4,
  "selected_count": 2,
  "decisions": [
    {
      "title": "Candidate 2",
      "author": "Author",
      "status": "rejected",
      "excluded_by": ["source_coverage_below_threshold"],
      "source_scoring": {
        "user_fit_score": 0.8,
        "source_coverage_score": 0.0,
        "final_score": 0.36,
        "source_status": "source_missing",
        "reject_reason": "source_coverage_below_threshold"
      }
    }
  ]
}
```

功能佐证：

- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_source_aware_selects_only_source_qualified_candidates` 验证 source-aware 场景会写 `recommendation_candidate_explainability` artifact。
- 同一测试断言 artifact 中 `candidate_count=4`、selected decision 为 2 条，rejected decision 包含 `source_coverage_below_threshold`。

### P2: Plan Route

- [ ] 定义 `recommendation_plan_v1` schema。
- [ ] 新增 `reading.recommend.plan_v1` 调用。
- [ ] plan 失败 fallback 到当前 `reading.recommend.intent`。
- [ ] plan 只作为 query/generate hint，不直接决定推荐。

### P2: Shadow Mode

- [ ] 新增 `reading.recommend.agentic_shadow_v1` route。
- [ ] 新增 shadow 配置项。
- [ ] shadow 输出写 `artifacts` 或独立 audit JSON。
- [ ] shadow 失败不影响 production run。
- [ ] 记录 `subagents_used`、roles、cost、latency、warnings。

### P2: Evaluation

- [ ] 新增 shadow comparison artifact。
- [ ] 对比 baseline 和 shadow 推荐。
- [ ] 记录 profile fit、novelty、start path、source validity、cost、latency。
- [ ] 将用户反馈与 review/shadow 判断做后验对齐。

### P3: Gating

- [ ] 新增 `ARC_ENABLE_REVIEW_GATING=false`。
- [ ] 支持 `request_regenerate_slot`。
- [ ] 支持 `suggest_block_delivery`，但必须 ARC 本地规则确认。
- [ ] 所有 gating decision 写入 run artifact。

### P3: Agentic Runtime

- [ ] 评估是否需要新 wrapper，例如 `hermes-agentic-json`。
- [ ] 支持 bounded delegation。
- [ ] 支持 max wall time、max subagents、max model calls、max search calls。
- [ ] 工具权限默认只读。
- [ ] 禁止 file/database/memory/message side effects。

## 9. 风险矩阵

| 风险 | 严重度 | 概率 | 说明 | 缓解 |
| --- | --- | --- | --- | --- |
| 输出不稳定 | 高 | 中 | 多 agent 增加非确定性和 JSON 漂移 | 严格 schema、shadow 先行、失败 fallback |
| 成本上升 | 中-高 | 高 | 子 agent 会放大模型调用次数 | max_subagents、max_model_calls、采样运行 |
| 延迟上升 | 中 | 高 | 子 agent 启动和搜索增加耗时 | max_wall_time、复杂场景才启用 |
| 画像污染 | 高 | 中 | 子 agent 直接写 memory 会长期污染画像 | 禁止子 agent 写 memory，ARC 受控 upsert |
| 违反 hard exclusion | 高 | 中 | LLM 可能忽略排除项 | ARC deterministic filtering |
| 幻觉书名/作者 | 中-高 | 中 | 候选扩展可能引入伪书 | verifier、source-aware ranking、uncertain 标记 |
| 审计困难 | 高 | 中 | 多 agent 中间过程难复盘 | structured trace、input/output hash |
| 失败不可隔离 | 高 | 中 | agentic route 失败可能影响 daily | shadow mode、route-level fallback |
| 工具权限越界 | 高 | 低-中 | file/terminal/memory/message 权限带来副作用 | 最小 toolset、无写权限 |
| 双重事实源 | 高 | 中 | Hermes 自行 session_search 可能和 ARC history 冲突 | 禁 session_search，由 ARC 注入唯一事实上下文 |
| 过度工程化 | 中 | 高 | daily 推荐未必需要多 agent | 先 review，再 shadow，以数据决定 |

## 10. 后期扩展方式

### 10.1 Review Dashboard

在 Web 管理端展示：

- 每日推荐 review verdict。
- 每本书的 profile fit、fatigue risk、source risk。
- Hermes 建议替换但 ARC 未采纳的候选。
- 用户后续反馈是否验证了 review 判断。

### 10.2 Agentic Shadow Leaderboard

长期保存 baseline 与 agentic shadow 的对比：

- 哪个 route 推荐更贴合画像。
- 哪个 route 更少重复。
- 哪个 route 更少错书。
- 哪个 route 的 reading suggestion 更可执行。
- 成本/延迟收益比。

### 10.3 Candidate Research Dossier

把候选书调研拆成结构化 dossier：

```text
book identity
source evidence
profile fit
reading entry
risks
why not selected
```

未来可用于解释为什么某本书被选中或淘汰。

### 10.4 Source-Aware Verifier

新增只读 verifier：

- 检查 source URL 是否书籍页面。
- 检查标题作者一致性。
- 标记 `verified|uncertain|unverified`。
- 将 verifier 结果纳入 source-aware ranking。

### 10.5 Adaptive Trigger Policy

不是每天都启用 agentic route，而是根据风险触发：

- 最近负反馈增加。
- 历史疲劳升高。
- source confidence 低。
- 候选数量不足。
- exploration 主题跨度大。
- review 判定 `revise|reject`。

### 10.6 Human-in-the-loop Gating

对高风险推荐进入人工确认：

```text
Hermes review warns
-> ARC marks pending_review
-> Web admin shows issue
-> user/admin approve / regenerate / skip
```

### 10.7 Hermes Native Thread Runtime

如果未来 Hermes 提供可控 session/thread API，可新增 runtime：

```text
hermes-agentic-json
```

要求：

- 可绑定 ARC `run_id`。
- 可限制工具集。
- 可记录 subagent trace。
- 可取消和超时。
- 输出严格 JSON。
- 不允许副作用。

### 10.8 Reading Pack Multi-review

对 deep read pack 引入多角度审查：

- 内容结构 reviewer。
- 用户画像 reviewer。
- source grounding reviewer。
- reading entry reviewer。

只用于提升内容质量，不改变 artifact 写入权。

### 10.9 Feedback Semantics Classifier

用 Hermes 子 agent 辅助判断反馈强弱：

- explicit self-report。
- weak signal。
- temporary mood。
- hard exclusion。
- positive anchor。
- exploration success/fail。

但仍保持 `profile_update_v1 -> ARC validate -> ARC upsert`。

## 11. 验收标准

第一阶段验收：

- 当前 production `run-daily` 不依赖 Hermes delegation。
- `review_v1` shadow 失败不影响正式推荐。
- review 输出可查询、可回放。
- 候选过滤原因可审计。

当前验证：

```bash
python3 -m py_compile app/daily_agent_adapter.py app/recommendation_review.py app/workflow.py
python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q
```

新增候选解释后，验证命令更新为：

```bash
python3 -m py_compile app/daily_agent_adapter.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py
python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q
```

第二阶段验收：

- `plan_v1` 可作为 query/generate hint。
- `plan_v1` 失败可 fallback。
- plan 输出不直接落库。

第三阶段验收：

- `agentic_shadow_v1` 默认关闭。
- 启用后不投递、不写 memory、不写主业务表。
- shadow artifact 记录 subagents、cost、latency、warnings。
- 能与用户反馈做后验对比。

生产 gating 验收：

- 默认关闭。
- Hermes 只能建议，ARC 决定执行。
- 所有 block/regenerate 都有本地可验证理由。
- 所有决策写入 artifact 或审计表。

## 12. 最终目标架构

```text
ARC deterministic workflow
  |
  |-- Hermes profile_update_v1 route
  |-- Hermes intent route
  |-- Hermes plan_v1 route
  |-- Hermes generate route
  |-- Hermes review_v1 route
  |-- Optional Hermes agentic_shadow_v1 route
  |-- Hermes deep_read_pack route
  |
ARC validation / hard exclusion / source-aware ranking / persistence / delivery / audit
```

最终原则不变：

```text
Hermes 子 agent 是 ARC 的智能增强器，不是 ARC 的业务执行者。
```
