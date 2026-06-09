# Hermes 子 Agent 与 Daily Workflow 策略

更新时间：2026-06-09

实现状态：

- 2026-06-08：已落地 `reading.recommend.review_v1` shadow 路径。默认关闭，可通过 `ARC_ENABLE_RECOMMEND_REVIEW_SHADOW=true` 或 `ReadingCoachWorkflow(..., recommend_review_shadow_enabled=True)` 启用。输出写入 `artifacts`，artifact type 为 `recommendation_review`，本地 JSON 路径位于 `library/recommendation-reviews/YYYY/MM/`。
- 2026-06-08：已落地候选过滤解释 artifact。每次 `run-daily` 会写 `recommendation_candidate_explainability` artifact，记录候选书是否 selected/rejected、`excluded_by`、source-aware 分数、source status 和 reject reason。本地 JSON 路径位于 `library/recommendation-decisions/YYYY/MM/`。
- 2026-06-08：已落地 daily agent runtime capability 建模。每次 `run-daily` 创建 `run_logs` 后立即将 `hermes_runtime_capabilities` 写入 `run_logs.metadata_json`，记录当前 provider/runtime 是否支持 native thread、delegation、memory、file、terminal、web、session_search 以及是否允许副作用。
- 2026-06-08：已落地 `reading.recommend.plan_v1` hint route。Hermes adapter 支持输出 3 个推荐 slot、搜索 query、候选标准和风险控制；ARC 只把 plan 当作主题/搜索 hint，仍由 ARC 执行推荐生成、hard exclusion、source-aware ranking、落库和投递。输出写入 `recommendation_plan` artifact，本地 JSON 路径位于 `library/recommendation-plans/YYYY/MM/`。
- 2026-06-08：已落地 `reading.recommend.agentic_shadow_v1` shadow route。默认关闭，仅在 `ARC_ENABLE_AGENTIC_SHADOW=true` 或 `ReadingCoachWorkflow(..., agentic_shadow_enabled=True)` 时启用；输出写入 `recommendation_agentic_shadow` artifact，本地 JSON 路径位于 `library/agentic-shadows/YYYY/MM/`，并记录 `subagents_used`、roles、latency、trace mode 和 warnings。
- 2026-06-09：已落地 shadow comparison artifact。每次 agentic shadow 成功后同步写 `recommendation_shadow_comparison` artifact，本地 JSON 路径位于 `library/shadow-comparisons/YYYY/MM/`，对比 baseline 与 shadow 的 profile fit、novelty、start path、source validity、cost、latency、overlap 和替换建议。
- 2026-06-09：已落地 shadow feedback alignment。新增 `align-shadow-feedback` CLI，可在用户反馈出现后读取历史 `recommendation_shadow_comparison` artifact 和 SQLite `feedback_events`，输出 `recommendation_shadow_feedback_alignment` artifact，本地 JSON 路径位于 `library/shadow-feedback-alignments/YYYY/MM/`。
- 2026-06-09：已落地 P3 review gating decision artifact。默认关闭，可通过 `ARC_ENABLE_REVIEW_GATING=true` 或 `ReadingCoachWorkflow(..., review_gating_enabled=True)` 启用。当前阶段只写 `recommendation_gating_decision` artifact，本地 JSON 路径位于 `library/gating-decisions/YYYY/MM/`；不会默认拦截正式推荐入库、reading pack 或投递。
- 2026-06-09：已落地 P3 `request_regenerate_slot` observe-only 支持。Gating 会从 `recommendation_review` 的 `candidate_reviews.status=replace/remove/revise/regenerate/needs_check` 或 `revision_instructions` 提取结构化 `requested_actions`，但当前 run 不自动重生成、不改 selected recommendations。
- 2026-06-09：已完成 P3 agentic runtime wrapper 评估。结论是短期不新增 wrapper，继续用 `reflect-json` 承载 bounded JSON routes；只有当需要真实 bounded delegation 时，才新增实验性 `hermes-agentic-json`，并保持只读、无副作用、shadow-first。
- 2026-06-09：已落地 P3 bounded delegation policy。`agentic_shadow` 的 `shadow_config` 现在包含 `delegation_policy`，当前固定为 `mode=simulated_trace`、`bounded_delegation_allowed=false`、`read_only=true`、`side_effects_allowed=false`，并写入 artifact / cost metadata。
- 2026-06-09：已落地 P3 agentic shadow budget policy。`shadow_config`、`delegation_policy` 和 `cost_logs.metadata_json` 会记录 `max_wall_time_seconds`、`max_model_calls`、`max_search_calls`，作为未来 `hermes-agentic-json` 的硬预算契约。
- 2026-06-09：已落地 P3 agentic shadow tool permission policy。`shadow_config.tool_permissions` 默认 `read_only`，显式禁止 file/database/memory/message/delivery 副作用，并写入 agentic shadow artifact 与 cost metadata。
- 2026-06-09：已完成 P0 边界命名修正。Adapter 文档明确 `reflect-json` 是 bounded one-shot JSON route，payload 中的本地链路字段从 `previous_turns` 改为 `explicit_payload_context_turns`，避免误解为 Hermes native session/thread。
- 2026-06-09：已落地 `reading.recommend.candidate_research_v1` 候选研究员小流程。默认关闭，可通过 `ARC_ENABLE_CANDIDATE_RESEARCH=true` 或 `ReadingCoachWorkflow(..., candidate_research_enabled=True)` 启用；输出写入 `recommendation_candidate_research` artifact，本地 JSON 路径位于 `library/candidate-research/YYYY/MM/`，并作为 ARC run-local explicit payload context 的前置研究摘要。
- 2026-06-09：已落地 `reading.recommend.fact_check_v1` 事实核验员小流程。默认关闭，可通过 `ARC_ENABLE_RECOMMEND_FACT_CHECK=true` 或 `ReadingCoachWorkflow(..., fact_check_enabled=True)` 启用；输出写入 `recommendation_fact_check` artifact，本地 JSON 路径位于 `library/fact-checks/YYYY/MM/`，检查书名/作者/source URL 可信度。

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

所以当前 `run-daily` 不是 Hermes native thread，也不是 Hermes 主 agent 编排子 agent。ARC 的 `local_session.explicit_payload_context_turns` 只是显式塞进下一次 payload 的局部上下文，不是 Hermes 原生多轮会话。

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

- [x] 新增/更新 Hermes 与 ARC 边界说明，明确 ARC owns SQLite、delivery、run state、memory application。
- [x] 在 adapter 文档中明确 `reflect-json` 是 oneshot，不是 Hermes native thread。
- [x] 把 `local_session.previous_turns` 命名为 explicit payload context，避免误解为 Hermes session。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter docstring 说明 reflect-json 是 bounded one-shot JSON route
  -> local_session.context_type=arc_explicit_payload_context
  -> local_session.explicit_payload_context_turns 代替 previous_turns

docs/engineering/22_hermes_subagent_daily_workflow_strategy.md
  -> 第 1-6 节明确 ARC owns SQLite / artifact / memory application / delivery / run state
  -> 第 3 节明确 reflect-json 是 hermes --oneshot，不是 native thread
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_carries_run_local_session_context_between_routes` 验证 payload 使用 `context_type=arc_explicit_payload_context` 和 `explicit_payload_context_turns`，且不再输出 `previous_turns`。
- 验证命令：`python3 -m py_compile app/daily_agent_adapter.py && python3 -m unittest tests.test_daily_agent_adapter -q`。

### P1: Capability 建模

- [x] 为 daily adapter 增加 capability object：

```json
{
  "schema_version": "daily_agent_runtime_capabilities_v1",
  "provider": "hermes-agent",
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

- [x] 将 capability 写入 run metadata。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.runtime_capabilities()
  -> daily_recommendation_runtime_capabilities()
  -> 对 Hermes reflect-json、legacy-local 和 custom adapter 做统一能力归一化

app/repository.py
  -> Repository.merge_run_metadata()
  -> 使用 BEGIN IMMEDIATE 读取并合并 run_logs.metadata_json，避免覆盖既有 channel 等 run metadata

app/workflow.py
  -> ReadingCoachWorkflow.run_daily_recommendations()
  -> create_run() 后立即写入 metadata.hermes_runtime_capabilities
```

落库示例：

```json
{
  "channel": "lark",
  "hermes_runtime_capabilities": {
    "schema_version": "daily_agent_runtime_capabilities_v1",
    "provider": "hermes-agent",
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
}
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_reports_reflect_json_runtime_capabilities` 验证 Hermes adapter 输出 `runtime=reflect-json`，并显式声明不支持 native thread、delegation、memory、file、terminal、web、session_search 和副作用。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_records_runtime_capabilities_in_run_metadata` 验证 daily run 会把能力对象写入 `run_logs.metadata_json.hermes_runtime_capabilities`，且不覆盖原有 `channel` metadata。
- 验证命令：`python3 -m py_compile app/daily_agent_adapter.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

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

- [x] 定义 `recommendation_plan_v1` schema。
- [x] 新增 `reading.recommend.plan_v1` 调用。
- [x] plan 失败 fallback 到当前 `reading.recommend.intent`。
- [x] plan 只作为 query/generate hint，不直接决定推荐。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.plan_recommendations()
  -> route: reading.recommend.plan_v1
  -> output_schema: recommendation_plan_v1
  -> normalize_recommendation_plan()

app/recommendation_plan.py
  -> RecommendationPlanService
  -> 负责检测 agent 是否支持 plan route、失败降级、记录 cost、写 recommendation_plan artifact

app/workflow.py
  -> build RecommendationHistoryContext 后尝试 plan route
  -> plan 有效时用 slots[].theme 作为今日主题
  -> Tavily 搜索优先使用 slots[].search_queries[0]
  -> plan 无效或不支持时 fallback 到原 reading.recommend.intent / default themes
```

失败边界：

```text
plan_v1 不支持、返回空 slots、返回非 JSON object 或执行异常时，只回退到当前 intent/default theme 路径；
不会跳过 ARC hard exclusion、source-aware ranking、recommendation_candidate_explainability、review shadow、落库或投递状态机。
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
      "candidate_criteria": ["必须是书籍", "有明确作者和阅读入口"],
      "risk_controls": ["避免已读书", "避免文章/课程页"],
      "reason": "贴合科幻经典偏好，同时避开近期疲劳主题"
    }
  ],
  "global_risk_controls": ["Hard exclusions are binding."],
  "plan_summary": "Plan is used as ARC search/generation hint only.",
  "confidence": 0.8
}
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_plans_recommendations_with_route_payload` 验证 Hermes payload 使用 `route=reading.recommend.plan_v1`、`output_schema=recommendation_plan_v1`，并保留 no-side-effect constraints。
- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_recommendation_plan_normalization_bounds_slots` 验证 plan schema 归一化、slot 类型归一化、字段截断和 confidence clamp。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_uses_recommendation_plan_as_search_hint_when_agent_supports_it` 验证 daily run 会使用 plan 的 search query，写 `recommendation_plan` artifact，记录 `cost_logs.operation='reading.recommend.plan_v1'`，并且最终仍由 ARC 写 `recommendations`。
- 验证命令：`python3 -m py_compile app/daily_agent_adapter.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

### P2: Candidate Researcher

- [x] 定义 `candidate_research_v1` schema。
- [x] 新增 `reading.recommend.candidate_research_v1` 调用。
- [x] 候选研究员默认关闭，启用后在搜索结果之后、正式推荐生成之前运行。
- [x] 输出 `candidate_dossiers`，只作为 research hint 和 audit artifact，不直接落库或投递。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.research_candidates()
  -> route: reading.recommend.candidate_research_v1
  -> output_schema: candidate_research_v1
  -> normalize_candidate_research()
  -> 把候选 dossier 摘要写入 explicit_payload_context_turns，供后续 generate route 参考

app/recommendation_candidate_research.py
  -> RecommendationCandidateResearchService
  -> 默认关闭、失败降级、记录 cost、写 recommendation_candidate_research artifact

app/workflow.py
  -> Tavily/search 之后调用 candidate research
  -> 正式 recommend.generate 之前完成候选研究
  -> 不跳过 ARC hard exclusion、source-aware ranking、candidate explainability、review、gating、落库和投递
```

配置项：

```env
ARC_ENABLE_CANDIDATE_RESEARCH=false
```

输出示例：

```json
{
  "schema_version": "candidate_research_v1",
  "candidate_dossiers": [
    {
      "title": "Research Book",
      "author": "Hermes",
      "slot_type": "profile_fit",
      "theme": "经典文学",
      "source_url": "https://example.test/book",
      "evidence": ["search result supports this is a book"],
      "profile_fit": "fits stable literary preference",
      "novelty": "adjacent to prior positive signal",
      "start_path": "read opening chapter",
      "risks": ["needs final ARC validation"],
      "confidence": 0.8
    }
  ],
  "research_warnings": [],
  "confidence": 0.75
}
```

失败边界：

```text
candidate_research_v1 默认关闭；
agent 不支持 route 时只写 run warning；
route 执行异常或返回非 object 时只写 run warning；
研究结果不直接写 recommendations、不更新 memory、不发消息；
正式候选仍由 recommend.generate 产生，ARC 继续执行 hard exclusion 和 source-aware ranking。
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_researches_candidates_with_route_payload` 验证 Hermes payload 使用 `route=reading.recommend.candidate_research_v1`、`output_schema=candidate_research_v1`，并保留 no-side-effect constraints。
- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_candidate_research_normalization_bounds_dossiers` 验证 dossier 字段截断、slot 归一化、warnings 和 confidence clamp。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_candidate_research_artifact_when_enabled` 验证启用 candidate research 后，daily run 仍写正式 `recommendations`，同时写 `recommendation_candidate_research` artifact，并记录 `cost_logs.operation='reading.recommend.candidate_research_v1'`。
- 验证命令：`python3 -m py_compile app/cli.py app/daily_agent_adapter.py app/recommendation_candidate_research.py app/recommendation_agentic_shadow.py app/recommendation_shadow_alignment.py app/recommendation_gating.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

### P2: Fact Checker

- [x] 定义 `recommendation_fact_check_v1` schema。
- [x] 新增 `reading.recommend.fact_check_v1` 调用。
- [x] 事实核验员默认关闭，启用后在 ARC 选出候选后、review shadow 前运行。
- [x] 输出 `verified|uncertain|unverified` 检查结果，只作为 audit artifact，不直接改推荐。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.fact_check_recommendations()
  -> route: reading.recommend.fact_check_v1
  -> output_schema: recommendation_fact_check_v1
  -> normalize_recommendation_fact_check()

app/recommendation_fact_check.py
  -> RecommendationFactCheckService
  -> 默认关闭、失败降级、记录 cost、写 recommendation_fact_check artifact

app/workflow.py
  -> hard exclusion / source-aware ranking 后调用 fact check
  -> review shadow / agentic shadow / gating 前完成核验
  -> 不直接改 selected recommendations、SQLite 主表、memory 或 delivery
```

配置项：

```env
ARC_ENABLE_RECOMMEND_FACT_CHECK=false
```

输出示例：

```json
{
  "schema_version": "recommendation_fact_check_v1",
  "checks": [
    {
      "title": "Fact Book",
      "author": "Hermes",
      "status": "verified",
      "identity_confidence": 0.9,
      "source_validity": "book_page",
      "evidence": ["publisher page found"],
      "risks": [],
      "recommended_action": "keep"
    }
  ],
  "global_warnings": [],
  "confidence": 0.85
}
```

失败边界：

```text
fact_check_v1 默认关闭；
agent 不支持 route 时只写 run warning；
route 执行异常或返回非 object 时只写 run warning；
核验结果不直接 block、不直接 replace、不写 memory、不发消息；
未来如进入 gating，也必须由 ARC local confirmation 决定是否执行强制动作。
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_fact_checks_recommendations_with_route_payload` 验证 Hermes payload 使用 `route=reading.recommend.fact_check_v1`、`output_schema=recommendation_fact_check_v1`，并保留 no-side-effect constraints。
- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_recommendation_fact_check_normalization_bounds_checks` 验证 status、source_validity、recommended_action、confidence 的归一化和 clamp。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_fact_check_artifact_when_enabled` 验证启用 fact check 后，daily run 仍写正式 `recommendations`，同时写 `recommendation_fact_check` artifact，并记录 `cost_logs.operation='reading.recommend.fact_check_v1'`。
- 验证命令：`python3 -m py_compile app/cli.py app/daily_agent_adapter.py app/recommendation_candidate_research.py app/recommendation_fact_check.py app/recommendation_agentic_shadow.py app/recommendation_shadow_alignment.py app/recommendation_gating.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

### P2: Shadow Mode

- [x] 新增 `reading.recommend.agentic_shadow_v1` route。
- [x] 新增 shadow 配置项。
- [x] shadow 输出写 `artifacts` 或独立 audit JSON。
- [x] shadow 失败不影响 production run。
- [x] 记录 `subagents_used`、roles、cost、latency、warnings。

当前实现：

```text
app/daily_agent_adapter.py
  -> HermesDailyRecommendationAdapter.agentic_shadow_recommendations()
  -> route: reading.recommend.agentic_shadow_v1
  -> output_schema: agentic_shadow_v1
  -> normalize_agentic_shadow()

app/recommendation_agentic_shadow.py
  -> RecommendationAgenticShadowService
  -> 负责默认关闭、配置读取、调用 agent、延迟计时、记录 cost、写 recommendation_agentic_shadow artifact

app/workflow.py
  -> recommendation review shadow 后调用 agentic shadow
  -> 调用位置在正式 recommendations / reading packs / delivery 前
  -> shadow 结果不进入正式推荐决策
```

配置项：

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

失败边界：

```text
agentic_shadow_v1 默认关闭；
agent 不支持 route 时只写 run warning；
route 执行异常或返回非 object 时只写 run warning；
不修改 selected recommendations、SQLite 主业务表、USER.md、memory、delivery outbox 或消息通道。
```

输出示例：

```json
{
  "schema_version": "agentic_shadow_v1",
  "subagents_used": 2,
  "roles": ["profile_history_reviewer", "source_quality_reviewer"],
  "trace_mode": "simulated_trace",
  "baseline_assessment": {
    "profile_fit": 0.8,
    "novelty": 0.6,
    "start_path_quality": 0.7,
    "source_validity": 0.9,
    "risks": []
  },
  "shadow_recommendations": [],
  "comparison": {
    "baseline_strengths": ["stable"],
    "shadow_strengths": ["more novel"],
    "tradeoffs": ["needs evidence"],
    "recommended_action": "observe_only"
  },
  "warnings": [],
  "confidence": 0.7
}
```

功能佐证：

- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_runs_agentic_shadow_with_route_payload` 验证 Hermes payload 使用 `route=reading.recommend.agentic_shadow_v1`、`output_schema=agentic_shadow_v1`，并保留 no-side-effect constraints。
- 单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_agentic_shadow_normalization_clamps_metadata` 验证 `subagents_used`、roles、trace mode 和 confidence 归一化。
- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_agentic_shadow_artifact_when_enabled` 验证启用 shadow 后，daily run 仍写正式 `recommendations`，同时写 `recommendation_agentic_shadow` artifact，并记录 `cost_logs.operation='reading.recommend.agentic_shadow_v1'`、`subagents_used` 和 `latency_ms`。
- 验证命令：`python3 -m py_compile app/daily_agent_adapter.py app/recommendation_agentic_shadow.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

### P2: Evaluation

- [x] 新增 shadow comparison artifact。
- [x] 对比 baseline 和 shadow 推荐。
- [x] 记录 profile fit、novelty、start path、source validity、cost、latency。
- [x] 将用户反馈与 review/shadow 判断做后验对齐。

当前实现：

```text
app/recommendation_agentic_shadow.py
  -> agentic shadow 成功后写 recommendation_agentic_shadow artifact
  -> 同步写 recommendation_shadow_comparison artifact
  -> comparison 完全由 ARC deterministic code 生成，不新增模型调用
```

comparison artifact 记录：

```text
baseline:
  - 正式 selected recommendations
  - Hermes shadow 返回的 baseline_assessment 中的 profile_fit / novelty / start_path_quality / source_validity

shadow:
  - shadow_recommendations
  - subagents_used / roles / trace_mode / warnings / confidence
  - novelty_proxy：shadow 中不和 baseline 重合的书占比
  - source_validity_proxy：shadow 推荐中带 source_url 的占比

comparison:
  - generated candidate count
  - baseline/shadow overlap count
  - replacement suggestion count
  - shadow source URL coverage
  - latency_ms
  - cost_units
  - agent_recommended_action

feedback_alignment:
  - comparison 初始状态为 pending_future_feedback
  - 记录 baseline_book_keys 和 shadow_book_keys
  - align-shadow-feedback 会在未来 feedback_events 产生后输出后验对齐 artifact
```

输出示例：

```json
{
  "schema_version": "recommendation_shadow_comparison_v1",
  "comparison": {
    "baseline": {
      "count": 3,
      "metrics": {
        "profile_fit": 0.8,
        "novelty": 0.6,
        "start_path_quality": 0.7,
        "source_validity": 0.9
      }
    },
    "shadow": {
      "count": 1,
      "metrics": {
        "novelty_proxy": 1.0,
        "source_validity_proxy": 1.0
      }
    },
    "comparison": {
      "overlap_count": 0,
      "replacement_suggestion_count": 1,
      "latency_ms": 123,
      "cost_units": 1
    },
    "feedback_alignment": {
      "status": "pending_future_feedback"
    }
  }
}
```

功能佐证：

- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_agentic_shadow_artifact_when_enabled` 验证启用 agentic shadow 后，会同时写 `recommendation_agentic_shadow` 和 `recommendation_shadow_comparison` artifact；comparison 中包含 baseline count、shadow count、replacement suggestion count、cost units 和 `feedback_alignment.status=pending_future_feedback`。
- 单元测试 `tests.test_workflow.WorkflowTests.test_shadow_feedback_alignment_uses_later_baseline_feedback` 验证在正式推荐产生用户反馈后，`RecommendationShadowFeedbackAlignmentService.align_recent()` 会输出 `recommendation_shadow_feedback_alignment` artifact，并把 baseline outcome 标记为 positive/ready。
- 验证命令：`python3 -m py_compile app/cli.py app/daily_agent_adapter.py app/recommendation_agentic_shadow.py app/recommendation_shadow_alignment.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

后验对齐命令：

```bash
python3 -m app.cli align-shadow-feedback --days 30 --limit 50
```

当前实现：

```text
app/recommendation_shadow_alignment.py
  -> RecommendationShadowFeedbackAlignmentService
  -> 读取 recommendation_shadow_comparison artifact
  -> 查询同一 run 的 delivered baseline recommendation feedback
  -> 查询 shadow book keys 的历史反馈
  -> 输出 recommendation_shadow_feedback_alignment artifact

app/cli.py
  -> align-shadow-feedback
  -> 支持 --days / --limit / --library-dir
```

alignment artifact 记录：

```text
baseline:
  - delivered recommendation 的 direct feedback
  - positive / negative / neutral / outcome
  - feedback type 和 reason code 分布

shadow:
  - shadow book keys 的历史反馈
  - 注意：除非 shadow 书也曾正式投递，否则这是 title/author 维度的间接反馈

feedback_alignment:
  - ready：已有 baseline feedback，可做后验判断
  - pending_future_feedback：还没有正式推荐反馈
```

### P3: Gating

- [x] 新增 `ARC_ENABLE_REVIEW_GATING=false`。
- [x] 支持 `request_regenerate_slot`。
- [x] 支持 `suggest_block_delivery` observe-only 决策，且 Hermes review/shadow 不能单独触发强制阻断。
- [x] 所有 gating decision 写入 run artifact。

当前实现：

```text
app/recommendation_gating.py
  -> RecommendationGatingService
  -> 读取同一 run 最新 recommendation_review / recommendation_agentic_shadow artifact
  -> 汇总 review verdict、agentic shadow recommended_action 和 ARC local confirmations
  -> 提取 request_regenerate_slot requested_actions
  -> 写 recommendation_gating_decision artifact

app/workflow.py
  -> recommendation review shadow
  -> agentic shadow
  -> review gating decision artifact
  -> 正式 recommendations / reading packs / delivery
```

配置项：

```env
ARC_ENABLE_REVIEW_GATING=false
ARC_REVIEW_GATING_ENFORCE_BLOCK=false
```

当前安全边界：

```text
P3 gating 当前是 observe-only；
默认不会阻断正式 recommendations 入库、reading pack 生成或飞书 delivery；
review verdict=reject 只会把 suggested_action 标为 suggest_block_delivery；
review requested regenerate 只会把 suggested_action 标为 request_regenerate_slot；
LLM review/shadow suggestion 不能单独变成强制 block；
未来如启用强制 block，也必须同时满足 ARC local block confirmation，例如 selected_recommendations 为空。
```

`request_regenerate_slot` 当前触发来源：

```text
recommendation_review.review.candidate_reviews[].status:
  - replace
  - remove
  - revise
  - regenerate
  - needs_check

recommendation_review.review.revision_instructions:
  - 当没有候选级 action 时，作为 recommendation_set 级 regenerate request 记录
```

local confirmations 当前包括：

```text
block:
  - no_selected_recommendations

warn:
  - selected_count_below_target
  - missing_reading_path
```

输出示例：

```json
{
  "schema_version": "recommendation_gating_decision_v1",
  "decision": {
    "mode": "observe_only",
    "suggested_action": "suggest_block_delivery",
    "enforced_action": "observe_only",
    "review": {
      "artifact_present": true,
      "verdict": "reject"
    },
    "agentic_shadow": {
      "artifact_present": false,
      "recommended_action": ""
    },
    "requested_actions": [],
    "local_confirmations": []
  }
}
```

功能佐证：

- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_review_gating_decision_artifact_when_enabled` 验证启用 review shadow + gating 后，daily run 仍写 3 条正式推荐，同时写 `recommendation_gating_decision` artifact；accept verdict 会得到 `suggested_action=allow_delivery`、`enforced_action=observe_only`。
- 单元测试 `tests.test_workflow.WorkflowTests.test_review_gating_reject_remains_observe_only_without_local_block` 验证 Hermes review 返回 `reject` 时，gating artifact 只记录 `suggested_action=suggest_block_delivery`，没有 ARC local block confirmation 时仍保持 `enforced_action=observe_only`，正式推荐仍落库 3 条。
- 单元测试 `tests.test_workflow.WorkflowTests.test_review_gating_records_regenerate_slot_request_as_observe_only` 验证 Hermes review 要求替换单个 `profile_fit` slot 时，gating artifact 会写 `requested_actions[].action=request_regenerate_slot`，`suggested_action=request_regenerate_slot`，但 `enforced_action=observe_only`，正式推荐仍落库 3 条。
- 验证命令：`python3 -m py_compile app/cli.py app/daily_agent_adapter.py app/recommendation_agentic_shadow.py app/recommendation_shadow_alignment.py app/recommendation_gating.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

### P3: Agentic Runtime

- [x] 评估是否需要新 wrapper，例如 `hermes-agentic-json`。
- [x] 支持 bounded delegation policy。
- [x] 支持 max wall time、max subagents、max model calls、max search calls。
- [x] 工具权限默认只读。
- [x] 禁止 file/database/memory/message side effects。

评估结论：

```text
短期 daily workflow 不需要新增 wrapper。

原因：
  - 已落地的 plan / review / agentic_shadow / gating 都是 bounded JSON route。
  - 当前 `reflect-json` 的 no-side-effect 边界更适合生产 daily。
  - ARC 仍是 SQLite、artifact、memory application、delivery 和 run state 的唯一 owner。
  - 在没有 shadow 后验收益数据前，引入 native delegation runtime 会增加成本、延迟和审计复杂度。

中期只有在需要真实 Hermes 子 agent delegation 时，才新增实验性 `hermes-agentic-json`。
```

`hermes-agentic-json` 若未来实现，必须满足：

```text
runtime scope:
  - 只能服务 shadow / review / verifier route。
  - 不能成为 run-daily 主 orchestrator。
  - 不能直接写 SQLite、library artifacts、USER.md、MEMORY.md、delivery outbox 或消息通道。

required controls:
  - max_wall_time_seconds
  - max_subagents
  - max_model_calls
  - max_search_calls
  - read_only_tools=true
  - side_effects_allowed=false
  - structured trace artifact
  - route-level timeout and fallback
```

决策记录：

| 选项 | 当前结论 | 理由 |
| --- | --- | --- |
| 继续 `reflect-json` | 采用 | 足够承载 bounded JSON routes，失败边界清楚，已有 runtime capability 和测试覆盖。 |
| 立即替换为 agentic wrapper | 不采用 | 会把 daily 自动任务暴露给更高非确定性，且目前 shadow 后验数据不足。 |
| 新增实验性 `hermes-agentic-json` | 暂缓 | 等 agentic shadow leaderboard / feedback alignment 证明收益后，再做只读实验 runtime。 |

功能佐证：

- `app/daily_agent_adapter.py` 的 `runtime_capabilities()` 已明确记录 `runtime=reflect-json`，且 `supports_delegation=false`、`supports_file=false`、`supports_terminal=false`、`supports_web=false`、`side_effects_allowed=false`。
- `run_logs.metadata_json.hermes_runtime_capabilities` 已在 daily run 开始时写入，可作为后续判断是否允许 agentic runtime 的事实依据。
- 已有单元测试 `tests.test_daily_agent_adapter.DailyAgentAdapterTests.test_hermes_adapter_reports_reflect_json_runtime_capabilities` 和 `tests.test_workflow.WorkflowTests.test_daily_run_records_runtime_capabilities_in_run_metadata` 证明当前 runtime capability 被正确声明和落库。
- 回归验证命令：`python3 -m py_compile app/cli.py app/daily_agent_adapter.py app/recommendation_agentic_shadow.py app/recommendation_shadow_alignment.py app/recommendation_gating.py app/recommendation_plan.py app/recommendation_review.py app/recommendation_explainability.py app/workflow.py app/repository.py && python3 -m unittest tests.test_daily_agent_adapter tests.test_workflow -q`。

bounded delegation policy 当前实现：

```text
app/recommendation_agentic_shadow.py
  -> shadow_config.delegation_policy
  -> mode=simulated_trace
  -> bounded_delegation_allowed=false
  -> max_subagents / max_wall_time_seconds / max_model_calls / max_search_calls
  -> allowed_roles 受 ARC_AGENTIC_SHADOW_MAX_SUBAGENTS 限制
  -> read_only=true
  -> side_effects_allowed=false
  -> shadow_config.tool_permissions.default=read_only
  -> 禁止 file/database/memory/message/delivery 写副作用

app/daily_agent_adapter.py
  -> agentic_shadow prompt 明确要求遵守 context.shadow_config.delegation_policy
  -> bounded_delegation_allowed=false 时只能模拟子角色分析，不能声称 native delegation
  -> prompt 明确要求遵守 context.shadow_config.tool_permissions
  -> max_wall_time_seconds / max_model_calls / max_search_calls 被声明为硬预算上限
```

artifact / cost metadata 佐证：

```json
{
  "shadow_config": {
    "delegation_policy": {
      "mode": "simulated_trace",
      "bounded_delegation_allowed": false,
      "max_wall_time_seconds": 90,
      "max_model_calls": 1,
      "max_search_calls": 0,
      "read_only": true,
      "side_effects_allowed": false,
      "tool_permissions": {
        "default": "read_only",
        "allow_file_write": false,
        "allow_database_write": false,
        "allow_memory_write": false,
        "allow_message_send": false,
        "allow_delivery_state_change": false
      }
    }
  },
  "cost_metadata": {
    "delegation_mode": "simulated_trace",
    "bounded_delegation_allowed": false,
    "max_wall_time_seconds": 90,
    "max_model_calls": 1,
    "max_search_calls": 0,
    "tool_permission_default": "read_only",
    "side_effects_allowed": false
  }
}
```

新增配置项：

```env
ARC_AGENTIC_SHADOW_TIMEOUT_SECONDS=90
ARC_AGENTIC_SHADOW_MAX_SUBAGENTS=2
ARC_AGENTIC_SHADOW_MAX_MODEL_CALLS=1
ARC_AGENTIC_SHADOW_MAX_SEARCH_CALLS=0
```

新增测试：

- 单元测试 `tests.test_workflow.WorkflowTests.test_daily_run_writes_agentic_shadow_artifact_when_enabled` 现在额外验证 `shadow_config.delegation_policy` / `shadow_config.tool_permissions` 会传给 agent、写入 artifact，并把 `delegation_mode=simulated_trace`、`bounded_delegation_allowed=false`、`max_wall_time_seconds`、`max_model_calls`、`max_search_calls`、`tool_permission_default=read_only`、`side_effects_allowed=false` 写入 `cost_logs.metadata_json`。

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
