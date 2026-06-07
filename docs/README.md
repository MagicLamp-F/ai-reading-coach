# AI Reading Coach

AI Reading Coach 是一个个人阅读推荐与反馈闭环系统。它每天根据用户画像、历史反馈和公开书源生成书籍推荐，通过飞书或 Web 阅读页触达用户，再把用户反馈沉淀为可审计的阅读画像。

当前项目已经从早期 Telegram MVP 演进为：

```text
SQLite 事实账本
-> Hermes 生成推荐、读书包、反思和主画像更新决策
-> ARC 负责写库、归档 artifact、发飞书、收反馈
-> 下一次 run-daily 处理反馈并更新画像
```

## 当前能力

- 每日推荐：`run-daily` 生成书籍推荐，写入 SQLite，并推送飞书卡片。
- Hermes 推荐：主题、候选书、深度读书包和 reflection 可走 Hermes route。
- 严格模式：配置 `hermes-agent` 后，Hermes route 失败会让任务失败，不静默 fallback。
- Hermes 主画像：优先读取 `memory/HERMES_NATIVE_PROFILE.md`，并同步到 Hermes native `USER.md` 的 `[arc-reading-profile]` entry。
- 反馈画像 ingest：未处理反馈会进入 Hermes `reading.feedback.ingest`，Hermes 判断是否更新主画像；ARC 写 `hermes_profile_update_events` 审计。
- 深度读书包：为推荐书生成结构化 deep read pack，并保存到 `reading_packs`、`artifacts` 和 `library/`。
- 来源增强：可通过 Tavily 和公开页面采集书源摘录，给推荐和读书包提供来源上下文。
- 飞书反馈：推荐卡片提供喜欢、一般、不感兴趣、已读、想深入等反馈入口。
- HTML 反馈/阅读页：`run-server` 提供传统反馈页和阅读包页面。
- JSON API + React Web：`run-api`、`app/api/` 和 `web/` 提供前后端分离阅读体验、导读页和管理入口。
- Guided Reading：支持从 Markdown/TXT/EPUB 书源创建分日导读计划。
- Reflection：支持生成、审批、应用 7 天阅读反思，并写入 ARC memory。
- Metrics：提供基础 Prometheus 文本指标。

## 快速启动

### 1. 准备环境

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

至少需要配置：

```env
DATABASE_URL=sqlite:///data/reading_coach.db
FEEDBACK_SECRET=change-me
PUBLIC_BASE_URL=http://localhost:8000
```

如果要真实推送飞书，还需要：

```env
CHANNEL=lark
LARK_WEBHOOK_URL=...
LARK_WEBHOOK_SECRET=...
```

如果要走当前真实 Hermes 流程，建议配置：

```env
DAILY_RECOMMENDATION_PROVIDER=hermes-agent
READING_PACK_PROVIDER=hermes-agent
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180
HERMES_NATIVE_USER_MEMORY_PATH=/home/ubuntu/.hermes/memories/USER.md
```

### 2. 初始化数据库

```bash
python3 -m app.cli init-db
```

可选：导入初始用户说明书。

```bash
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
```

### 3. 跑一次正常日推

```bash
python3 -m app.cli run-daily
```

这会按正常流程执行：

```text
处理未处理反馈
-> 调用 Hermes feedback ingest
-> 更新 ARC profile_items
-> 读取 Hermes native profile snapshot
-> Hermes 生成主题和推荐
-> 来源采集与排序
-> Hermes 生成 deep read pack
-> 写 SQLite 和 library artifact
-> 推送飞书或进入 delivery outbox
-> 如果启用 DAILY_REFLECTION_ENABLED，继续生成 reflection
```

### 4. 启动反馈/阅读服务

传统 HTML 服务：

```bash
python3 -m app.cli run-server --host 0.0.0.0 --port 8000
```

JSON API 服务：

```bash
python3 -m app.cli run-api --host 0.0.0.0 --port 8000
```

React Web 前端：

```bash
cd web
npm install
npm run dev
```

默认前端端口是 `8010`。

### 5. Docker Compose

当前 `docker-compose.yml` 包含后端 API 和 Web 服务：

```bash
docker compose up --build -d
```

Compose 默认启动 API 与 Vite Web 开发服务。生产部署可使用 `deploy/nginx/ai-reading-coach.conf` 指向 `web/dist`。

## 常用命令

```bash
python3 -m app.cli init-db
python3 -m app.cli run-daily
python3 -m app.cli run-server --host 0.0.0.0 --port 8000
python3 -m app.cli run-api --host 0.0.0.0 --port 8000
python3 -m app.cli show-hermes-profile-sync --json
python3 -m app.cli generate-reading-pack --recommendation-id <id>
python3 -m app.cli run-weekly-report
python3 -m app.cli generate-reflection --days 7
python3 -m app.cli list-reflections
python3 -m app.cli show-reflection --id <id>
python3 -m app.cli approve-reflection --id <id>
python3 -m app.cli apply-reflection --id <id>
python3 -m app.cli create-guided-reading-plan --source-file book.md --title 书名
python3 -m app.cli send-guided-reading-pushes
python3 -m app.cli run-scheduler --no-poller
python3 scripts/backup_sqlite.py
```

## 关键目录

```text
app/                 Python 后端、CLI、workflow、Hermes adapters、SQLite repository
app/api/             FastAPI JSON API
web/                 React/Vite 前端
data/                SQLite 数据库
memory/              ARC memory 和 Hermes native profile snapshot
library/             deep read pack / guided reading artifact
prompts/             用户说明书示例
scripts/             备份脚本
deploy/              systemd/nginx 部署文件
docs/                面向接手和使用的项目文档
docs/engineering/    历史工程设计、验证记录和开发过程文档
```

## 文档地图

- [软件需求说明](./software_requirements.md)：项目目标、用户角色、功能需求、非功能需求、验收标准。
- [概要设计](./architecture_overview.md)：系统模块、数据流、核心流程、关键表和失败边界。
- [工程文档索引](./engineering/README.md)：历史设计、开发记录、运行手册。
- [当前工程进展](./engineering/10_current_progress_summary.md)：最近一次工程状态总结。

## 当前状态

最近一次已提交的核心能力是 Hermes feedback ingest：

```text
commit 25bd85e Wire Hermes feedback profile ingest
```

真实验证结果：

```text
feedback_events.id=27
daily run_id=56 success
processed_feedback=1
hermes_profile_update_events.id=1 status=applied confidence=0.91
recommendation_id=69: 围城 / 钱锺书
reading_pack id=40 status=generated generator_provider=hermes-agent
reflection run_id=57 success
```

如果工作区有未提交改动，先用 `git status --short` 区分代码变更和运行时 memory/artifact。
