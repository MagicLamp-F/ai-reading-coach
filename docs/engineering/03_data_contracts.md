# 数据契约

## 1. 设计原则

数据层要服务两个目标：

1. 保留可审计事实。
2. 支持 Hermes 生成可解释的长期记忆。

因此数据分为三类：

```text
事件数据：发生了什么
画像数据：系统当前怎么理解用户
反思数据：Hermes 如何解释这些变化
```

## 2. 核心实体

### Recommendation

一次书籍推荐。

关键字段：

```text
id
run_id
book_id
recommendation_date
slot_type
theme
system_hypothesis
recommendation_reason
profile_dimensions
expected_benefit
risk
reading_suggestion
message_id
created_at
```

`slot_type` 建议枚举：

```text
profile_fit
knowledge_gap
exploration
```

### FeedbackEvent

用户对推荐的反馈。

关键字段：

```text
id
recommendation_id
feedback_type
reason_code
free_text
created_at
processed_at
```

`feedback_type`：

```text
like
neutral
not_interested
already_read
go_deeper
```

`reason_code` 示例：

```text
topic_matches
solves_current_problem
too_shallow
too_hard
already_know
wrong_timing
too_theoretical
too_marketing
```

### ProfileItem

结构化画像条目。

关键字段：

```text
id
category
content
weight
confidence
evidence_count
evidence_json
created_at
updated_at
last_seen_at
```

`category`：

```text
long_term_interest
short_term_interest
knowledge_background
knowledge_gap
reading_preference
disliked_topic
action_stage
energy_state
exploration_tendency
self_narrative
```

当前已落地的类别是 `long_term_interest`、`short_term_interest`、`knowledge_background`、`reading_preference`、`disliked_topic`、`life_context`、`knowledge_gap`、`action_stage`。`energy_state`、`exploration_tendency`、`self_narrative` 仍是后续扩展目标。

### Reflection

Hermes 周期性反思结果。

建议字段：

```text
id
period_start
period_end
summary
accurate_observations_json
misunderstandings_json
profile_updates_json
next_week_questions_json
memory_patch
created_at
approved_at
```

`memory_patch` 可以是 Hermes 建议写入 `USER.md` / `MEMORY.md` 的内容。初期建议人审后再落盘。

## 3. 事件流契约

### 推荐生成事件

输入：

```text
当前结构化画像
Hermes USER.md
Hermes MEMORY.md
最近 7 天推荐
最近 7 天反馈
搜索结果
```

输出：

```json
{
  "recommendations": [
    {
      "title": "string",
      "author": "string",
      "slot_type": "profile_fit",
      "theme": "string",
      "system_hypothesis": "string",
      "profile_dimensions": ["knowledge_gap", "action_stage"],
      "recommendation_reason": "string",
      "expected_benefit": "string",
      "risk": "string",
      "reading_suggestion": "string"
    }
  ]
}
```

### 反馈处理事件

输入：

```text
recommendation_id
feedback_type
reason_code
free_text
recommendation context
```

输出：

```json
{
  "profile_updates": [
    {
      "category": "knowledge_gap",
      "content": "系统设计基础仍需补齐",
      "weight_delta": 0.08,
      "confidence_delta": 0.05,
      "evidence": {
        "source": "feedback_event",
        "feedback_id": 123
      }
    }
  ]
}
```

### 周期性反思事件

输入：

```text
周期内所有推荐
周期内所有反馈
原因反馈
自由文本
当前 USER.md
当前 MEMORY.md
```

输出：

```json
{
  "summary": "string",
  "accurate_observations": ["string"],
  "misunderstandings": ["string"],
  "profile_updates": ["string"],
  "next_questions": ["string"],
  "memory_patch": "markdown string"
}
```

## 4. 数据保留策略

- 原始推荐和反馈长期保留。
- 画像条目可更新，但证据列表保留最近 N 条。
- Hermes 生成的 memory patch 应版本化。
- 删除或覆盖长期记忆需要人工确认。

## 5. 当前代码差距

当前已具备：

- `profile_items`
- `recommendations`
- `feedback_events`
- `books`
- `run_logs`
- `cost_logs`

下一步需要补充：

- `reason_code`
- `system_hypothesis`
- `profile_dimensions`
- `reflections`
- `memory_versions`
