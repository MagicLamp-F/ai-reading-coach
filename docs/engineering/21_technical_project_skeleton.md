# 技术项目骨架与运行流程

更新时间：2026-06-07

## 1. 项目一句话

`ai-reading-coach` 是阅读业务编排层：

```text
SQLite 保存事实
-> Hermes 生成推荐/读书包/反思
-> ARC 写库、归档 artifact、发飞书、收反馈
-> 反馈再进入下一轮画像与推荐
```

Hermes 是智能生成层，不直接写 ARC SQLite，不直接发飞书。ARC 是业务账本、投递和审计系统。Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md` 中的 `[arc-reading-profile]` 是当前主画像事实源；`memory/HERMES_NATIVE_PROFILE.md` 只作为 ARC 本地兼容/诊断快照。反馈画像更新采用同一安全边界：Hermes `reading.feedback.ingest` 基于当前原生 USER 画像和新反馈返回是否更新主画像的决策，ARC 负责写审计表和受控 upsert native `USER.md`。

## 2. 核心目录

```text
app/
  cli.py                  命令入口：init-db、run-daily、run-server、run-api、reflection 等
  factory.py              从 Settings 构造 repo/search/llm/lark/hermes adapters/workflow
  config.py               .env 配置读取
  db.py                   SQLite schema 与迁移
  repository.py           SQLite 读写封装
  workflow.py             每日推荐、飞书投递、delivery outbox、周报主流程
  daily_agent_adapter.py  Hermes daily 推荐 route 调用
  profile_ingest.py       Hermes reading.feedback.ingest 调用与受控 USER memory 写入
  reading_pack.py         deep_read_pack 生成、artifact、Markdown、阅读包预览
  reflection.py           反思草稿、审批、应用、memory change log
  reflection_adapter.py   Hermes/custom reflection adapter
  memory.py               Hermes 原生 USER 主画像读取、ARC memory 与兼容快照
  source_collector.py     Tavily/公开来源采集与来源质量评分
  lark.py                 飞书卡片和 webhook
  server.py               传统 HTML 反馈/阅读页面
  api/                    前后端分离 JSON API

web/                      Vite/React 前端
memory/                   ARC 已应用 memory、change logs 与兼容/诊断快照
library/                  reading pack / guided reading artifact
data/                     SQLite 数据库
deploy/                   systemd/nginx 部署文件
docs/engineering/         工程文档
```

## 3. 正常日推流程

命令：

```bash
python3 -m app.cli run-daily
```

流程：

```text
Settings.from_env()
-> build_context()
-> ReadingCoachWorkflow.run_daily_recommendations()
   -> process_feedback()
      -> 对未处理 feedback_events 调用 Hermes reading.feedback.ingest
      -> payload 包含当前 /home/ubuntu/.hermes/memories/USER.md 的 [arc-reading-profile]
      -> 写 hermes_profile_update_events 审计
      -> 如果 Hermes 明确要求更新，ARC upsert /home/ubuntu/.hermes/memories/USER.md 的 [arc-reading-profile] entry
      -> 再按 ARC 规则更新 profile_items 并标记 feedback processed
   -> HermesNativeProfileProvider.load_context()
      -> 优先读 /home/ubuntu/.hermes/memories/USER.md 的 [arc-reading-profile]
      -> 如果原生 entry 缺失，才读 memory/HERMES_NATIVE_PROFILE.md 作为兼容来源
      -> 如果兼容快照缺失或占位，调用 reading.profile.sync_snapshot
      -> 同步 compact entry 到 /home/ubuntu/.hermes/memories/USER.md
   -> build_profile_context(repo)
   -> load_long_term_memory_context(memory/USER.md, memory/MEMORY.md)
   -> build_daily_profile_context(Priority 1-5)
   -> build_recommendation_history_context(repo)
      -> Hard exclusions / Negative feedback / Positive anchors / History fatigue / Recent recommendations
   -> Hermes reading.recommend.intent 生成主题
   -> Tavily 搜索书源
   -> Hermes reading.recommend.generate 生成候选书
   -> source-aware ranking
   -> 写 recommendations / books / candidates
   -> Hermes reading.deep_read_pack 生成读书包
   -> 写 reading_packs / artifacts / reading_pack_sources
   -> 飞书推荐卡片
   -> 如果 DAILY_REFLECTION_ENABLED=true，继续生成 reflection
```

## 4. 画像上下文层级

daily prompt 使用固定优先级：

```text
Priority 1: Hermes native USER memory reading profile
Priority 2: User explicit ARC feedback
Priority 3: ARC inferred reading profile
Priority 4: ARC applied reflection memory
Priority 5: Single-run weak signals
```

注意：当前 `/home/ubuntu/.hermes/SOUL.md` 是 Hermes Agent 身份说明，不是用户画像。因此主画像必须来自 Hermes 原生 `USER.md` 中的 `[arc-reading-profile]`。`memory/HERMES_NATIVE_PROFILE.md` 只在原生 entry 缺失时作为兼容/诊断快照使用。

Hermes native memory 的真实位置是当前 `HERMES_HOME/memories/USER.md`。默认部署中为：

```text
/home/ubuntu/.hermes/memories/USER.md
```

ARC 只管理其中一条 entry：

```text
[arc-reading-profile] User reading profile: ...
```

重复运行会替换这条 entry，不会清空 Hermes UI/CLI 里已有的其它 USER memories。Hermes Agent 会在新会话启动时冻结读取 built-in memory，因此 UI 旧会话不会保证实时注入刚写入的画像。

反馈驱动的主画像更新链路：

```text
feedback_events(processed_at IS NULL)
-> read native USER.md [arc-reading-profile]
-> Hermes route: reading.feedback.ingest
   output_schema: profile_update_v1
   output: should_update_native_memory / memory_entry / rationale / confidence / evidence_summary
-> hermes_profile_update_events
   status: applied / skipped / failed
-> optional upsert native USER.md [arc-reading-profile]
-> ARC profile_items
-> feedback_events.processed_at
```

推荐历史上下文链路：

```text
recommendations + feedback_events
-> build_recommendation_history_context()
-> RecommendationHistoryContext:
   Hard exclusions / Negative feedback / Positive anchors / History fatigue / Recent recommendations
-> reading.recommend.intent
-> reading.recommend.generate
```

推荐历史不写入 Hermes 原生 USER memory。Hermes 用它做语义选书和避让，ARC 仍负责写库、审计和硬校验。

失败边界：

- Hermes feedback ingest 超时、退出非 0、返回非法 JSON 或要求写空 memory entry 时，写 `hermes_profile_update_events.status='failed'`。
- 失败后本次 `run-daily` 失败，`feedback_events.processed_at` 保持空，不走 fallback。
- 单次弱信号可以被 Hermes 判定 `skipped`，此时仍保留审计，但不写 native USER memory。

## 5. Hermes 严格模式

正常 provider 配置下不允许 fallback：

```env
DAILY_RECOMMENDATION_PROVIDER=hermes-agent
READING_PACK_PROVIDER=hermes-agent
HERMES_REFLECTION_PROVIDER=hermes-agent
```

行为：

- Hermes daily 失败：`run-daily` 失败，不生成 fallback 书单。
- Hermes reading pack 失败：`run-daily` 失败，不写 `fallback` reading pack。
- Hermes reflection 失败：reflection run 失败，不 fallback 到 custom。
- 只有显式设置 `HERMES_REFLECTION_PROVIDER=hermes-agent-fallback` 才允许 reflection fallback。

## 6. 关键配置

```env
DATABASE_URL=sqlite:///data/reading_coach.db
CHANNEL=lark
LARK_WEBHOOK_URL=...
FEEDBACK_SECRET=...

DAILY_RECOMMENDATION_PROVIDER=hermes-agent
READING_PACK_PROVIDER=hermes-agent
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180

HERMES_NATIVE_PROFILE_PATH=memory/HERMES_NATIVE_PROFILE.md
HERMES_SOUL_PATH=/home/ubuntu/.hermes/SOUL.md
HERMES_NATIVE_PROFILE_MAX_CHARS=6000
HERMES_NATIVE_USER_MEMORY_PATH=/home/ubuntu/.hermes/memories/USER.md
HERMES_NATIVE_USER_MEMORY_CHAR_LIMIT=1375
```

不要设置无效的 Hermes model override。2026-06-05 发现：

```env
HERMES_INFERENCE_PROVIDER=custom
HERMES_INFERENCE_MODEL=gpt-5.5
```

在没有 `CUSTOM_BASE_URL` 时会导致 Hermes stdout 为空。已在 `.env` 注释掉这两个覆盖项，让 Hermes 使用自身已验证模型配置。

## 7. 常用验证

自动化：

```bash
python3 -m unittest discover -s tests
```

Hermes smoke：

```bash
set -a
. ./.env
set +a
/home/ubuntu/projects/hermes-agent/bin/reflect-json --check-env
/home/ubuntu/projects/hermes-agent/bin/reflect-json --debug-smoke
```

正常流程：

```bash
python3 -m app.cli run-daily
```

查看 Hermes snapshot 与 native USER memory 同步状态：

```bash
python3 -m app.cli show-hermes-profile-sync
python3 -m app.cli show-hermes-profile-sync --json
```

验证 Hermes native USER memory：

```bash
python3 - <<'PY'
from pathlib import Path
path = Path('/home/ubuntu/.hermes/memories/USER.md')
print(path)
print(path.read_text(encoding='utf-8'))
PY
```

查最新 run：

```bash
python3 - <<'PY'
from app.config import Settings
from app.db import connect
s = Settings.from_env()
conn = connect(s.database_path)
for row in conn.execute("select * from run_logs order by id desc limit 5"):
    print(dict(row))
PY
```

查 Hermes feedback ingest 审计：

```bash
python3 - <<'PY'
from pathlib import Path
from app.cli import _load_env_file
from app.config import Settings
from app.db import connect, init_db
_load_env_file(Path('.env'))
s = Settings.from_env()
conn = connect(s.database_path)
init_db(conn)
for row in conn.execute("select id, feedback_event_id, status, should_update_native_memory, confidence, memory_entry, error_message from hermes_profile_update_events order by id desc limit 5"):
    print(dict(row))
PY
```

## 8. 2026-06-05 真实验证结果

正常流程 run：

```text
daily run_id=48 success
reflection run_id=49 success
reflection_id=4 auto-applied
```

推荐结果：

```text
书名：活着
作者：余华
主题：高口碑当代文学与经典名著中的人性、命运与社会观察
generator: hermes-agent
reading_pack: generated
artifact: library/2026/06/2026-06-05__活着/reading-pack.md
```

判断：

- Hermes daily 确实基于现有 ARC reading profile 生成了文学/经典方向推荐。
- Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md` 已包含 `[arc-reading-profile]`，当前主画像读源是这条原生 memory entry。
- `memory/HERMES_NATIVE_PROFILE.md` 只作为 ARC 兼容/诊断快照；反馈事件已经能通过 Hermes `reading.feedback.ingest` 驱动原生主画像增量更新。

native USER memory 同步验证：

```text
path: /home/ubuntu/.hermes/memories/USER.md
chars: 596
entry: [arc-reading-profile] User reading profile: Reading Preferences...
```

追加真实正常流程 run：

```text
daily run_id=50 success
recommendation_id=66: 额尔古纳河右岸 / 迟子建
theme: 高口碑当代中文文学：从清晰叙事进入个体、族群与时代经验
reading_pack id=37 status=generated generator_provider=hermes-agent
artifact: library/2026/06/2026-06-05__额尔古纳河右岸/reading-pack.md
reflection run_id=51 success
reflection_id=5 applied
```

## 9. 2026-06-07 真实验证结果

正常反馈入口验证：

```text
python3 -m app.cli run-server --host 127.0.0.1 --port 8123
POST /feedback/inline
feedback_events.id=27
recommendation_id=68
feedback_type=like
reason_code=topic_matches
processed_at=NULL
```

正常 `run-daily` 验证：

```text
daily run_id=56 success
processed_feedback=1
recommendation_id=69: 围城 / 钱锺书
reading_pack id=40 status=generated generator_provider=hermes-agent
reflection run_id=57 success
reflection_id=8 auto-applied
```

Hermes feedback ingest 审计：

```text
hermes_profile_update_events.id=1
feedback_event_id=27
status=applied
should_update_native_memory=1
confidence=0.91
memory_entry=[arc-reading-profile] User reading profile: 用户明确反馈科幻经典很符合当前阅读兴趣，尤其可继续推荐带有文明想象、技术伦理与未来社会主题的科幻作品。
```

Hermes native USER memory 同步状态：

```text
python3 -m app.cli show-hermes-profile-sync --json
snapshot_exists=true
native_user_memory_path=/home/ubuntu/.hermes/memories/USER.md
native_user_memory_exists=true
arc_entry_present=true
arc_entry_chars=596
```

判断：

- Hermes 已作为主画像决策者处理真实反馈：`reading.feedback.ingest` 生成了明确画像更新决策。
- ARC 没有让 Hermes 黑箱写文件；写入由 ARC 编排层完成，并有 SQLite 审计。
- 没有 fallback：如果 Hermes feedback ingest 失败，本次 run 会失败，反馈不会被标记 processed。

## 10. 文档维护规则

每次大改后必须做三件事：

1. 更新本技术骨架或相关工程文档，说明新流程、新配置、新失败边界。
2. 记录真实验证命令和结果，尤其是 run_id、状态、是否使用 Hermes、是否 fallback。
3. 提交代码和文档；如果有外部仓库文件改动，例如 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`，需要单独说明它不在本仓库 commit 内。
