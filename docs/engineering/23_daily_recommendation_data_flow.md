# Daily Recommendation Data Flow

更新时间：2026-06-09

本文描述 `ai-reading-coach` 当前每日推荐链路的数据流、Hermes 参与边界、ARC 事实账本边界，以及每个可扩展小流程的输入、输出和 artifact。

## 1. 总结

当前推荐系统不是“Hermes 全权接管 daily workflow”，而是：

```text
ARC = 主编排器 / 事实账本 / 规则执行器 / 投递器
Hermes = 受控 JSON 决策层 / 内容生成层 / 小流程研究与审查层
```

推荐链路的核心边界：

```text
Hermes can propose, research, review, verify.
ARC validates, filters, ranks, persists, delivers, audits.
```

Hermes 当前通过 `reflect-json` 进入：

```text
/home/ubuntu/projects/hermes-agent/bin/reflect-json
-> hermes --oneshot
```

所以当前没有 Hermes native thread，也没有真正的 Hermes 子 agent delegation。`local_session.explicit_payload_context_turns` 是 ARC 显式塞进下一次 payload 的 run-local 上下文，不是 Hermes 原生多轮会话。

## 2. 总链路

```text
run_daily_recommendations()

1. ARC 创建 run_logs
2. ARC 记录 daily agent runtime capabilities
3. ARC 开启 run-local explicit payload context
4. ARC 处理未处理 feedback
5. ARC 构造 profile_context
6. ARC 构造 RecommendationHistoryContext
7. Hermes plan route 可选生成推荐计划
8. Hermes intent route 或 plan 生成今日主题
9. ARC 搜索公开书籍信息
10. Hermes candidate researcher 可选整理候选研究 dossier
11. Hermes generate route 生成候选推荐
12. ARC hard exclusion 过滤
13. ARC source-aware ranking 可选排序
14. ARC 写 candidate explainability artifact
15. Hermes fact checker 可选核验已选候选
16. Hermes review shadow 可选审稿
17. Hermes agentic shadow 可选影子对比
18. ARC gating 可选汇总建议，当前 observe-only
19. ARC 写 recommendations
20. ARC 生成 reading pack
21. ARC 发送飞书或写 delivery_outbox
22. ARC 发送本轮 profile test summary
23. ARC finish_run(success/failed)
```

## 3. 输入数据

### 3.1 SQLite 事实数据

ARC 从 SQLite 读取：

- `recommendations`
- `books`
- `feedback_events`
- `profile_items`
- `book_sources`
- `reading_packs`
- `artifacts`
- `hermes_profile_update_events`
- `run_logs`

这些表由 ARC 维护。Hermes 不直接读写 SQLite。

### 3.2 用户画像上下文

`profile_context` 由 ARC 合成，主要来源：

```text
Hermes native USER memory [arc-reading-profile]
ARC structured profile_items
ARC long-term memory files
recent feedback and reflection signals
```

当前主画像读源是 Hermes native USER memory。ARC 本地 memory 文件只作为兼容、反思和诊断来源。

### 3.3 推荐历史上下文

`RecommendationHistoryContext` 由 ARC 从 SQLite 构造，包含：

- hard exclusions
- negative feedback
- positive anchors
- recent recommendations
- history fatigue
- repeated themes
- exact-title cooldown

Hermes 可以基于这些上下文做语义判断，但最终 hard exclusion 由 ARC deterministic code 执行。

## 4. Hermes 路由

### 4.1 `reading.recommend.plan_v1`

角色：推荐规划员。

调用位置：

```text
profile_context + RecommendationHistoryContext
-> plan_v1
-> themes/search query/candidate criteria/risk controls
```

输出 artifact：

```text
artifact_type = recommendation_plan
library/recommendation-plans/YYYY/MM/
```

边界：

- 只作为 ARC search/generate hint。
- 不直接生成正式推荐。
- 不写库、不投递、不更新 memory。

### 4.2 `reading.recommend.intent`

角色：主题生成器。

调用位置：

```text
如果 plan_v1 不可用或无有效 slots
-> intent route 生成 2 profile_fit + 1 exploration themes
```

边界：

- 只生成主题。
- 不决定最终书籍。

### 4.3 `reading.recommend.candidate_research_v1`

角色：候选研究员。

调用位置：

```text
ARC 搜索公开信息后
-> candidate_research_v1 整理 candidate_dossiers
-> 写 artifact
-> 摘要进入 ARC run-local explicit payload context
-> 后续 generate route 可参考
```

输出 artifact：

```text
artifact_type = recommendation_candidate_research
library/candidate-research/YYYY/MM/
```

输出核心字段：

- `candidate_dossiers[]`
- `title`
- `author`
- `slot_type`
- `theme`
- `source_url`
- `evidence`
- `profile_fit`
- `novelty`
- `start_path`
- `risks`
- `confidence`

边界：

- 默认关闭：`ARC_ENABLE_CANDIDATE_RESEARCH=false`
- 只研究候选，不写 `recommendations`
- 不替代 hard exclusion
- 不替代 source-aware ranking
- 失败只写 run warning，不影响 daily 主流程

### 4.4 `reading.recommend.generate`

角色：候选推荐生成器。

调用位置：

```text
profile_context
+ RecommendationHistoryContext
+ themes
+ search_results
+ explicit_payload_context_turns
-> generate route
-> RecommendationDraft candidates
```

输出进入内存中的 `RecommendationDraft`，随后由 ARC 过滤和排序。

边界：

- Hermes 生成候选，但不落库。
- ARC 后续执行 hard exclusion、source-aware ranking 和正式写库。

### 4.5 `reading.recommend.fact_check_v1`

角色：事实核验员。

调用位置：

```text
ARC hard exclusion / source-aware ranking 后
-> fact_check_v1 核验 selected recommendations
-> 写 artifact
-> gating 后续读取
```

输出 artifact：

```text
artifact_type = recommendation_fact_check
library/fact-checks/YYYY/MM/
```

输出核心字段：

- `checks[]`
- `status = verified|uncertain|unverified`
- `identity_confidence`
- `source_validity = book_page|publisher_page|review_page|article_like|unknown`
- `evidence`
- `risks`
- `recommended_action = keep|needs_source_check|replace`

边界：

- 默认关闭：`ARC_ENABLE_RECOMMEND_FACT_CHECK=false`
- 不直接 block 推荐
- 不直接 replace 推荐
- 不写库、不投递、不更新 memory
- 高风险结果只进入 gating observe-only 建议

### 4.6 `reading.recommend.review_v1`

角色：审稿人。

调用位置：

```text
ARC 选出候选后
-> review_v1 审查 generated_candidates 和 selected_recommendations
-> 写 recommendation_review artifact
```

输出 artifact：

```text
artifact_type = recommendation_review
library/recommendation-reviews/YYYY/MM/
```

输出核心字段：

- `verdict = accept|warn|reject`
- `candidate_reviews[]`
- `global_warnings`
- `revision_instructions`
- `confidence`

边界：

- 默认关闭：`ARC_ENABLE_RECOMMEND_REVIEW_SHADOW=false`
- shadow-only
- 不改变正式推荐
- reject 只进入 gating 建议

### 4.7 `reading.recommend.agentic_shadow_v1`

角色：影子评估员。

调用位置：

```text
ARC 已有 baseline selected recommendations
-> agentic_shadow_v1 做影子对比
-> 写 agentic shadow artifact
-> 写 shadow comparison artifact
```

输出 artifacts：

```text
artifact_type = recommendation_agentic_shadow
library/agentic-shadows/YYYY/MM/

artifact_type = recommendation_shadow_comparison
library/shadow-comparisons/YYYY/MM/
```

边界：

- 默认关闭：`ARC_ENABLE_AGENTIC_SHADOW=false`
- 当前是 `simulated_trace`
- `bounded_delegation_allowed=false`
- `tool_permissions.default=read_only`
- 不写库、不投递、不更新 memory

## 5. ARC 确定性处理

### 5.1 Hard Exclusion

ARC 在 Hermes generate 后执行：

```text
_filter_hard_excluded_drafts()
```

如果候选命中 hard exclusion：

- 从候选中移除
- 写 run warning
- 如果全部候选都被排除，run failed

这是规则，不是 Hermes 建议。

### 5.2 Source-Aware Ranking

如果启用 `source_aware_recommendations`：

```text
ARC upsert book
-> collect public sources if needed
-> calculate source_quality
-> combine user_fit_score + source_score
-> select top N
-> write recommendation_candidates audit rows
```

source-aware ranking 是 ARC 执行，Hermes 只能提供候选和解释。

### 5.3 Candidate Explainability

ARC 每次 daily 都写：

```text
artifact_type = recommendation_candidate_explainability
library/recommendation-decisions/YYYY/MM/
```

记录每本候选：

- selected/rejected
- `excluded_by`
- source score
- source reject reason
- candidate metadata

## 6. Gating

当前 gating 是 observe-only。

调用位置：

```text
fact_check
review_shadow
agentic_shadow
-> recommendation_gating_decision
-> ARC 继续正式落库和投递
```

读取 artifacts：

- `recommendation_review`
- `recommendation_agentic_shadow`
- `recommendation_fact_check`

输出 artifact：

```text
artifact_type = recommendation_gating_decision
library/gating-decisions/YYYY/MM/
```

决策字段：

- `suggested_action = allow_delivery|warn_delivery|request_regenerate_slot|suggest_block_delivery`
- `enforced_action = observe_only|block_delivery`
- `review`
- `agentic_shadow`
- `fact_check`
- `requested_actions`
- `local_confirmations`
- `selected_recommendations`

当前规则：

```text
review verdict=reject
-> suggested_action=suggest_block_delivery
-> enforced_action=observe_only

review requested regenerate
-> suggested_action=request_regenerate_slot
-> enforced_action=observe_only

fact-check unverified / replace
-> suggested_action=request_regenerate_slot
-> enforced_action=observe_only

fact-check article_like / needs_source_check
-> suggested_action=warn_delivery
-> enforced_action=observe_only
```

强制 block 当前不会因 Hermes 判断单独触发。未来如果启用：

```env
ARC_REVIEW_GATING_ENFORCE_BLOCK=true
```

也必须有 ARC local block confirmation，例如：

```text
no_selected_recommendations
```

## 7. 正式落库和投递

Gating 当前不拦截后，ARC 继续：

```text
repo.add_recommendation()
-> optional reading pack generation
-> send recommendation to Lark / Telegram
-> if send failed, enqueue delivery_outbox
-> set message_id if send success
```

正式写入：

- `recommendations`
- `books`
- `reading_packs`
- `artifacts`
- `delivery_outbox`
- `cost_logs`
- `run_logs`

## 8. Artifacts 总表

| 阶段 | Artifact Type | 路径 | 是否影响正式推荐 |
| --- | --- | --- | --- |
| Plan | `recommendation_plan` | `library/recommendation-plans/YYYY/MM/` | 作为 hint |
| Candidate Research | `recommendation_candidate_research` | `library/candidate-research/YYYY/MM/` | 作为 hint/audit |
| Candidate Explainability | `recommendation_candidate_explainability` | `library/recommendation-decisions/YYYY/MM/` | ARC 审计 |
| Fact Check | `recommendation_fact_check` | `library/fact-checks/YYYY/MM/` | 只进入 gating 建议 |
| Review | `recommendation_review` | `library/recommendation-reviews/YYYY/MM/` | 只进入 gating 建议 |
| Agentic Shadow | `recommendation_agentic_shadow` | `library/agentic-shadows/YYYY/MM/` | 不影响正式推荐 |
| Shadow Comparison | `recommendation_shadow_comparison` | `library/shadow-comparisons/YYYY/MM/` | 后验评估 |
| Gating | `recommendation_gating_decision` | `library/gating-decisions/YYYY/MM/` | 当前 observe-only |
| Reading Pack | `reading_pack` | `library/reading-packs/YYYY/MM/` | 投递内容 |

## 9. 开关矩阵

| 开关 | 默认值 | 作用 |
| --- | --- | --- |
| `ARC_ENABLE_CANDIDATE_RESEARCH` | `false` | 启用候选研究员 |
| `ARC_ENABLE_RECOMMEND_FACT_CHECK` | `false` | 启用事实核验员 |
| `ARC_ENABLE_RECOMMEND_REVIEW_SHADOW` | `false` | 启用推荐审稿人 |
| `ARC_ENABLE_AGENTIC_SHADOW` | `false` | 启用影子评估 |
| `ARC_ENABLE_REVIEW_GATING` | `false` | 写 gating decision |
| `ARC_REVIEW_GATING_ENFORCE_BLOCK` | `false` | 允许 ARC 本地确认后强制 block |
| `ARC_AGENTIC_SHADOW_MAX_SUBAGENTS` | `2` | 影子评估最大子角色数 |
| `ARC_AGENTIC_SHADOW_TIMEOUT_SECONDS` | `90` | 影子评估预算 |
| `ARC_AGENTIC_SHADOW_MAX_MODEL_CALLS` | `1` | 影子评估模型调用预算 |
| `ARC_AGENTIC_SHADOW_MAX_SEARCH_CALLS` | `0` | 影子评估搜索预算 |

## 10. 推荐的真实验证命令

只开 observe-only 小流程：

```bash
ARC_ENABLE_CANDIDATE_RESEARCH=true \
ARC_ENABLE_RECOMMEND_FACT_CHECK=true \
ARC_ENABLE_RECOMMEND_REVIEW_SHADOW=true \
ARC_ENABLE_AGENTIC_SHADOW=true \
ARC_ENABLE_REVIEW_GATING=true \
python3 -m app.cli run-daily
```

验证重点：

- `run_logs.status` 是否 success。
- 正式 `recommendations` 是否仍写入。
- `recommendation_candidate_research` 是否产生有价值 dossier。
- `recommendation_fact_check` 是否能识别伪书、错作者或 article-like source。
- `recommendation_review` 是否能指出用户画像/历史疲劳问题。
- `recommendation_agentic_shadow` 是否提出比 baseline 更好的替代。
- `recommendation_gating_decision` 是否正确汇总 review、fact-check、shadow，并保持 `enforced_action=observe_only`。

## 11. 后续演进

建议顺序：

1. 跑真实 dry run，观察 artifact 质量。
2. 把 fact-check 的高风险结果做成 dashboard。
3. 用后续用户反馈评估 shadow / research 是否比 baseline 更好。
4. 如果长期收益明确，再考虑 `hermes-agentic-json`。
5. 即使启用真实 bounded delegation，也保持 ARC 独占 SQLite、memory application、delivery 和 run state。
