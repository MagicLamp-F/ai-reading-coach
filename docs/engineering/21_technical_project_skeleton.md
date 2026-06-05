# 技术项目骨架与运行流程

更新时间：2026-06-05

## 1. 项目一句话

`ai-reading-coach` 是阅读业务编排层：

```text
SQLite 保存事实
-> Hermes 生成推荐/读书包/反思
-> ARC 写库、归档 artifact、发飞书、收反馈
-> 反馈再进入下一轮画像与推荐
```

Hermes 是智能生成层，不直接写 ARC SQLite，不直接发飞书。ARC 是业务账本、投递和审计系统。当前 Hermes native profile snapshot 由 Hermes 生成，但输入证据以 ARC SQLite reading profile 和 ARC applied memory 为主，SOUL 只作为低优先级背景。ARC 会把这份阅读画像同步到 Hermes built-in `USER.md`，让 Hermes UI/CLI 的新会话也能看到同一条阅读画像 memory。

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
  reading_pack.py         deep_read_pack 生成、artifact、Markdown、阅读包预览
  reflection.py           反思草稿、审批、应用、memory change log
  reflection_adapter.py   Hermes/custom reflection adapter
  memory.py               ARC memory 文件读取、Hermes native profile snapshot
  source_collector.py     Tavily/公开来源采集与来源质量评分
  lark.py                 飞书卡片和 webhook
  server.py               传统 HTML 反馈/阅读页面
  api/                    前后端分离 JSON API

web/                      Vite/React 前端
memory/                   ARC 已应用 memory 与 Hermes native profile snapshot
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
   -> HermesNativeProfileProvider.load_context()
      -> 读 memory/HERMES_NATIVE_PROFILE.md
      -> 缺失或仅含“缺少个人阅读事实”占位时，调用 reading.profile.sync_snapshot
      -> Hermes 基于 ARC reading profile + ARC applied memory + 低优先级 SOUL 生成 snapshot
      -> upsert 到 /home/ubuntu/.hermes/memories/USER.md 的 [arc-reading-profile] entry
   -> build_profile_context(repo)
   -> load_long_term_memory_context(memory/USER.md, memory/MEMORY.md)
   -> build_daily_profile_context(Priority 1-5)
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
Priority 1: Hermes native profile snapshot
Priority 2: User explicit ARC feedback
Priority 3: ARC inferred reading profile
Priority 4: ARC applied reflection memory
Priority 5: Single-run weak signals
```

注意：当前 `/home/ubuntu/.hermes/SOUL.md` 是 Hermes Agent 身份说明，不是用户画像。因此 native snapshot 不能只依赖 SOUL。2026-06-05 已调整为由 ARC reading profile 和 ARC applied memory 提供主证据，Hermes 负责把这些证据整理成 `memory/HERMES_NATIVE_PROFILE.md`。

Hermes native memory 的真实位置是当前 `HERMES_HOME/memories/USER.md`。默认部署中为：

```text
/home/ubuntu/.hermes/memories/USER.md
```

ARC 只管理其中一条 entry：

```text
[arc-reading-profile] User reading profile: ...
```

重复运行会替换这条 entry，不会清空 Hermes UI/CLI 里已有的其它 USER memories。Hermes Agent 会在新会话启动时冻结读取 built-in memory，因此 UI 旧会话不会保证实时注入刚写入的画像。

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
- Hermes native snapshot 已由 Hermes 基于 ARC 证据刷新，当前包含用户对经典名著、高口碑文学、科幻作品、个人知识管理、软件工程实践和 AI Agent 商业化降频的画像判断。
- ARC 已支持把该 snapshot/upsert entry 写入 Hermes native `/home/ubuntu/.hermes/memories/USER.md`。这解决了“ARC 侧有画像但 Hermes UI 看不到”的问题；反馈事件自动驱动 Hermes 主画像增量更新仍属于下一阶段。

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

## 9. 文档维护规则

每次大改后必须做三件事：

1. 更新本技术骨架或相关工程文档，说明新流程、新配置、新失败边界。
2. 记录真实验证命令和结果，尤其是 run_id、状态、是否使用 Hermes、是否 fallback。
3. 提交代码和文档；如果有外部仓库文件改动，例如 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`，需要单独说明它不在本仓库 commit 内。
