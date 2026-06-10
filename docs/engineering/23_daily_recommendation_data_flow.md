# Daily Recommendation Data Flow

更新时间：2026-06-10

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

2026-06-10 可靠性更新：

- 如果 Hermes reading pack agent 超时或失败，ARC 现在只记录 `run_logs.warning_message`，不再把整次 daily 标记为 failed。
- 推荐仍会落库并投递，飞书卡片会保留快读包入口字段；若快读包缺失，则卡片只提示无法打开完整包。
- 服务器 systemd 入口统一到 `0.0.0.0:8010`，与 `PUBLIC_BASE_URL=http://120.53.247.229:8010` 保持一致，避免快读包 URL 指向拒绝连接的端口。

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

飞书卡片投递时，reading pack 只作为入口出现：

```text
reading_pack_url present
-> card shows "快读包" + "打开完整快读包" URL

reading_pack_url missing
-> card shows "快读包已生成，当前没有可打开链接。"
```

卡片不再内联 reading pack 的 summary、论证脉络、核心概念、章节 walkthrough、例子、局限或机器归档路径。原因是 reading pack 正文较长，内联到飞书推荐卡片会挤占主推荐信息；完整内容以 reading pack URL 为准。

正式写入：

- `recommendations`
- `books`
- `reading_packs`
- `reading_quotes`
- `artifacts`
- `delivery_outbox`
- `cost_logs`
- `run_logs`

## 8. 摘抄数据链路

2026-06-10 新增快读包摘抄能力。目标是让用户在阅读快读包时，把其中想反复回味的原著句子保存下来，并让这类句子偏好进入后续画像上下文。

### 8.1 页面入口

快读包页面新增“摘抄 / 我的摘抄”面板：

```text
用户在快读包正文选中一句话
-> 点击“填入选中文本”
-> 可补充来自哪一节、为什么喜欢
-> 点击“保存摘抄”
```

支持两个页面形态：

- 传统服务端 HTML 快读包页：POST `/reading-pack/quote`
- React 快读包页：POST `/api/reading-packs/{reading_pack_id}/quotes`

保存后，快读包页面会显示最近摘抄；管理页 `/admin/quotes` 会按时间展示所有摘抄，并关联作品、作者、模块和小节。

### 8.2 数据写入

摘抄落库到：

```text
reading_quotes
```

核心字段：

- `reading_pack_id`
- `recommendation_id`
- `book_id`
- `selected_text`
- `note`
- `module`
- `section_title`
- `source_surface`
- `metadata_json`

索引：

- `idx_reading_quotes_pack_created`
- `idx_reading_quotes_book_created`

这保证后续可以从快读包、作品、管理后台三个角度回看摘抄。

### 8.3 画像信号

保存摘抄后，ARC 会同步写入：

```text
profile_items.category = reading_preference
evidence.source = reading_quote
```

证据里包含：

- `quote_id`
- `reading_pack_id`
- `recommendation_id`
- `book`
- `quote`
- `note`

这一步让后续 daily workflow 构造 `profile_context` 时，Hermes 能看到“用户反复保存什么类型的句子”。当前实现是 ARC structured profile 可见，不是 Hermes native memory 的直接写入。

### 8.4 Hermes 当前参与边界

当前边界：

```text
quote submission
-> ARC writes reading_quotes
-> ARC writes profile_items evidence
-> next daily profile_context includes reading_preference
-> Hermes recommendation/generation routes can use it
```

Hermes 目前不会在摘抄提交当下启动独立 native 子 agent，也不会直接改写 Hermes USER memory。这样做的原因是摘抄属于高频小信号，先进入 ARC 事实账本和结构化画像，避免把未聚合的碎片直接写入长期主画像。

### 8.5 后续可扩展方式

建议按这个顺序演进：

1. `quote.ingest` 小流程：定期把最近摘抄交给 Hermes，总结句式、主题、情绪和审美偏好，再写回 Hermes native USER memory。
2. 作品级摘抄页：在书籍详情或推荐历史里展示“这本书我摘抄过什么”。
3. 摘抄复习队列：按时间间隔或主题，把旧摘抄推回飞书，形成复读和回味机制。
4. 相似句偏好推荐：推荐时不仅看主题和类型，也看语言风格、叙事密度、抽象程度和情绪温度。
5. Hermes 子角色拆分：让候选研究员关注“作品是否有可摘抄密度”，让审稿人检查推荐理由是否匹配用户保存过的句子偏好，让事实核验员确认摘抄是否来自原著或可靠来源。

### 8.6 布局修复

传统服务端快读包页修复了桌面端“下一节”分页和反馈区重叠问题：

- `.feedbacks` 从底部 sticky 行为改为普通页面内反馈区。
- `.pager` 和 `.feedbacks` 现在按文档流排列，避免反馈区压住下一节。
- 移动端仍保持横向/折叠友好的反馈按钮布局。

## 9. Artifacts 总表

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

## 10. 开关矩阵

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

## 11. 推荐的真实验证命令

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

2026-06-10 本轮代码验证：

```bash
python3 -m py_compile app/api/main.py app/api/serializers.py app/server.py app/repository.py app/db.py app/workflow.py
python3 -m unittest tests.test_db tests.test_server tests.test_api -q
python3 -m unittest tests.test_lark tests.test_workflow -q
cd web && npm run build
```

测试覆盖：

- `tests.test_workflow` 验证 Hermes reading pack agent 失败时 daily 仍 success，并写 warning。
- `tests.test_server` 验证服务端快读包页含摘抄面板、POST 后写入 `reading_quotes` 和 `profile_items`。
- `tests.test_api` 验证 React API 保存摘抄、快读包查询摘抄、管理页查询摘抄。
- `tests.test_db` 验证 `reading_quotes` 表和索引创建。
- `npm run build` 验证 React 快读包摘抄面板、管理页和类型定义可通过生产构建。

## 12. 后续演进

建议顺序：

1. 跑真实 dry run，观察 artifact 质量。
2. 把 fact-check 的高风险结果做成 dashboard。
3. 用后续用户反馈评估 shadow / research 是否比 baseline 更好。
4. 如果长期收益明确，再考虑 `hermes-agentic-json`。
5. 即使启用真实 bounded delegation，也保持 ARC 独占 SQLite、memory application、delivery 和 run state。
6. 为摘抄增加 `quote.ingest`，让 Hermes 把多条摘抄聚合成稳定的语言/审美偏好，而不是逐条碎片化写入长期画像。
