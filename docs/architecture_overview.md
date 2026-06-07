# 概要设计

## 1. 总体架构

AI Reading Coach 由三层组成：

```text
用户入口层
  飞书卡片 / HTML 阅读页 / JSON API / React Web

业务编排层 ARC
  CLI / workflow / repository / SQLite / delivery / artifact

智能生成层 Hermes
  recommendation routes / reading pack routes / reflection routes / profile ingest routes
```

核心原则：

- SQLite 是事实账本。
- Hermes 是生成和主画像判断层。
- ARC 是唯一业务写入者：写 SQLite、写 artifact、写 native USER memory、发飞书。
- Hermes route agent 不直接写 ARC SQLite、不发消息、不任意改文件。
- 正常 Hermes provider 失败必须暴露，不用 fallback 掩盖。

## 2. 组件图

```text
                    +----------------------+
                    |      User            |
                    | Feishu / Web / API   |
                    +----------+-----------+
                               |
                               v
+------------------------------+-------------------------------+
|                         ARC / app                            |
|                                                              |
|  cli.py       -> command entry                               |
|  factory.py   -> build Settings, repo, adapters, workflow     |
|  workflow.py  -> daily recommendation orchestration           |
|  profile.py   -> feedback processing and ARC profile update   |
|  profile_ingest.py -> Hermes feedback ingest + USER upsert    |
|  reading_pack.py -> deep read pack generation and artifact    |
|  reflection.py -> reflection draft / approve / apply          |
|  memory.py     -> ARC memory + Hermes native profile snapshot |
|  server.py     -> HTML feedback and reading pages             |
|  app/api/      -> FastAPI JSON API, currently in progress     |
|  repository.py -> SQLite access                              |
|  db.py         -> schema and migrations                       |
+------------------------------+-------------------------------+
                               |
              +----------------+----------------+
              |                                 |
              v                                 v
     +------------------+              +----------------------+
     | SQLite           |              | Hermes Agent          |
     | data/*.db        |              | reflect-json wrapper  |
     +------------------+              +----------------------+
              |                                 |
              v                                 v
     +------------------+              +----------------------+
     | library/         |              | ~/.hermes/memories/  |
     | memory/          |              | USER.md              |
     +------------------+              +----------------------+
```

## 3. 核心数据模型

### 用户画像和反馈

```text
profile_items
  ARC 本地阅读画像，按 category/content 聚合权重、置信度和证据。

feedback_events
  用户原始反馈事实。未处理时 processed_at 为空。

hermes_profile_update_events
  Hermes 主画像更新审计。记录 applied/skipped/failed、memory_entry、rationale、confidence、evidence_summary。
```

### 推荐和来源

```text
books
  书籍去重。

recommendations
  每日推荐结果、画像映射、系统假设、推荐理由。

recommendation_candidates
  Hermes 生成的候选书、来源质量评分、最终评分、入选/拒绝原因。

book_sources
  公开来源页面或 Tavily raw_content 清洗后的摘录。
```

### 读书包和 artifact

```text
reading_packs
  Hermes deep_read_pack 结构化 JSON、状态、provider、错误。

artifacts
  Markdown 等长文本产物的文件路径和 hash。

reading_pack_sources
  reading_pack 和 book_sources 的引用关系。
```

### 反思和长期 memory

```text
reflections
  Hermes reflection draft、审批状态和 apply 状态。

memory/USER.md
memory/MEMORY.md
  ARC applied reflection memory。

memory/HERMES_NATIVE_PROFILE.md
  ARC 可读的 Hermes native profile snapshot。

/home/ubuntu/.hermes/memories/USER.md
  Hermes native USER memory。ARC 只维护 [arc-reading-profile] 这一条 entry。
```

### Guided Reading

```text
reading_source_files
  用户上传或导入的 Markdown/TXT/EPUB 书源。

reading_plans
  分日导读计划。

reading_plan_days
  每一天的阅读片段和状态。

reading_day_packs
  每日导读内容。

reading_progress_events
  打开、继续、完成、不感兴趣等进度事件。
```

## 4. 正常日推流程

入口：

```bash
python3 -m app.cli run-daily
```

流程：

```text
1. Settings.from_env()
2. build_context()
   - connect SQLite
   - init_db()
   - build Hermes adapters
   - build workflow

3. ReadingCoachWorkflow.run_daily_recommendations()

4. process_feedback()
   - 读取 feedback_events where processed_at is null
   - 调用 Hermes reading.feedback.ingest
   - 写 hermes_profile_update_events
   - 如 applied，upsert Hermes native USER.md
   - 按 ARC 规则更新 profile_items
   - mark_feedback_processed()

5. 构造画像上下文
   - Priority 1: Hermes native profile snapshot
   - Priority 2: explicit ARC feedback
   - Priority 3: ARC inferred reading profile
   - Priority 4: ARC applied reflection memory
   - Priority 5: single-run weak signals

6. Hermes 推荐
   - reading.recommend.intent 生成主题
   - Tavily/公开页面采集来源
   - reading.recommend.generate 生成候选书
   - source-aware ranking 选书

7. 写推荐结果
   - books
   - recommendations
   - recommendation_candidates

8. Hermes 生成 deep read pack
   - reading.deep_read_pack
   - reading_packs
   - artifacts
   - reading_pack_sources

9. 触达
   - 飞书卡片
   - delivery_outbox

10. 可选 reflection
   - DAILY_REFLECTION_ENABLED=true 时运行
   - 生成 reflection draft
   - HERMES_REFLECTION_AUTO_APPLY=true 时自动 apply
```

## 5. 反馈到主画像流程

```text
User clicks feedback
-> server.py / app/api/main.py verifies HMAC token
-> feedback_events inserted
-> next run-daily
-> profile.process_feedback()
-> HermesFeedbackProfileIngestor.ingest_feedback()
-> reflect-json route reading.feedback.ingest
-> profile_update_v1 response
-> hermes_profile_update_events audit
-> optional upsert /home/ubuntu/.hermes/memories/USER.md
-> ARC profile_items update
-> feedback_events.processed_at set
```

关键失败边界：

- Hermes command not found -> failed audit -> run failed.
- Hermes timeout -> failed audit -> run failed.
- Hermes invalid JSON -> failed audit -> run failed.
- Hermes says update but memory_entry empty -> failed audit -> run failed.
- Native USER memory path disabled while update required -> failed audit -> run failed.

这条链路不 fallback。原因是 fallback 会把主画像错误隐藏起来，后续推荐会继续被污染。

## 6. Hermes native profile 读取流程

```text
HermesNativeProfileProvider.load_context()
-> read memory/HERMES_NATIVE_PROFILE.md
-> if missing/placeholder:
     call reading.profile.sync_snapshot
     write memory/HERMES_NATIVE_PROFILE.md
     upsert native USER.md
-> return snapshot as Priority 1 context
```

诊断命令：

```bash
python3 -m app.cli show-hermes-profile-sync --json
```

输出重点：

```text
snapshot_exists
native_user_memory_path
native_user_memory_exists
arc_entry_present
arc_entry_chars
arc_entry_preview
```

## 7. 阅读包流程

```text
recommendation_id
-> FastReadPackService.generate_for_recommendation()
-> load recommendation and book
-> collect/reuse book_sources
-> build prioritized profile context
-> HermesReadingPackAdapter.generate_pack()
-> parse deep_read_pack_v2
-> write reading_packs
-> write artifact markdown under library/
-> link reading_pack_sources
```

当前严格模式下，如果 Hermes reading pack 失败，daily run 失败，不写 fallback reading pack。

## 8. Reflection 流程

```text
generate-reflection / run-daily auto reflection
-> collect recent recommendations, feedback, profile, weekly summary
-> Hermes reflection route
-> write reflections status=draft
-> approve/apply or auto-apply
-> append memory/USER.md and memory/MEMORY.md
-> write memory/change_logs
```

Reflection 写的是 ARC memory，不等同于 Hermes native USER memory。Hermes native USER memory 的 ARC 管理 entry 由 `memory.py` 和 `profile_ingest.py` 受控更新。

## 9. API 和 Web 设计状态

当前工作区已有前后端分离改动：

```text
app/api/main.py
app/api/serializers.py
web/
docker-compose.yml
deploy/
```

设计意图：

- `run-api` 启动 FastAPI。
- Web 前端通过 `/api/reading-packs/{id}` 展示阅读包。
- Web 前端通过 `/api/guided-reading/days/{id}` 展示分日导读。
- 管理端 API 支持上传书源、创建阅读计划、查看计划。

注意：这些改动当前仍未提交，属于进行中状态。接手时先看 `git status --short`，确认是否要继续整理、测试和提交。

## 10. 关键配置

```env
DATABASE_URL=sqlite:///data/reading_coach.db
CHANNEL=lark
PUBLIC_BASE_URL=http://localhost:8000
FEEDBACK_SECRET=change-me

DAILY_RECOMMENDATION_PROVIDER=hermes-agent
READING_PACK_PROVIDER=hermes-agent
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180

HERMES_NATIVE_PROFILE_PATH=memory/HERMES_NATIVE_PROFILE.md
HERMES_NATIVE_USER_MEMORY_PATH=/home/ubuntu/.hermes/memories/USER.md

SOURCE_AWARE_RECOMMENDATIONS=true
SOURCE_AWARE_STRICT_MODE=true
DAILY_READING_PACKS_ENABLED=true
DAILY_REFLECTION_ENABLED=true
HERMES_REFLECTION_AUTO_APPLY=true
```

## 11. 关键节点清单

接手项目时优先看这些节点：

1. `app/cli.py`
   CLI 命令入口。

2. `app/factory.py`
   所有依赖和 adapters 的构造位置。

3. `app/workflow.py`
   日推主流程，最重要的业务编排。

4. `app/profile.py`
   反馈如何变成 ARC profile_items。

5. `app/profile_ingest.py`
   反馈如何交给 Hermes 构造主画像。

6. `app/memory.py`
   Hermes native profile snapshot 和 native USER memory 同步。

7. `app/reading_pack.py`
   深度读书包生成、artifact 和来源链接。

8. `app/reflection.py`
   Reflection 生成、审批、应用。

9. `app/db.py`
   SQLite schema。

10. `app/repository.py`
    SQLite 读写封装。

11. `app/server.py`
    传统 HTML 反馈和阅读页。

12. `app/api/main.py`
    JSON API，当前进行中。

13. `web/src/main.tsx`
    React Web 入口，当前进行中。

## 12. 验证策略

自动化：

```bash
python3 -m unittest discover
```

关键真实流程：

```bash
python3 -m app.cli show-hermes-profile-sync --json
python3 -m app.cli run-daily
```

查数据库：

```sql
select * from run_logs order by id desc limit 5;
select * from feedback_events order by id desc limit 5;
select * from hermes_profile_update_events order by id desc limit 5;
select * from reading_packs order by id desc limit 5;
```

验收重点：

- run 成功还是失败必须和 Hermes route 状态一致。
- 不允许出现 provider 是 `hermes-agent` 但结果来自 fallback 的情况。
- 主画像更新必须有 `hermes_profile_update_events` 审计。
- 用户反馈处理成功后才允许写 `processed_at`。
