# AI Reading Coach

AI Reading Coach 是一个个人阅读推荐与反馈闭环系统。它每天根据 Hermes 主画像、推荐历史和用户反馈生成书籍推荐，通过飞书、传统 HTML 页面或 React Web 触达用户，再把反馈沉淀为可审计的阅读画像。

核心边界：

```text
Hermes 原生 USER.md [arc-reading-profile] 作为主画像
-> ARC 从 SQLite 构造 RecommendationHistoryContext
-> Hermes 生成主题、推荐、读书包和画像更新决策
-> ARC 负责写库、发飞书、归档 artifact、硬校验和审计
```

## 功能

- SQLite 保存画像、书籍、推荐历史、反馈事件、运行日志、读书包和调用日志。
- 飞书自定义机器人推送推荐卡片，每本书包含系统假设、画像维度、推荐理由、收益、风险和建议读法。
- 反馈链接支持 `喜欢 / 一般 / 不感兴趣 / 已读 / 想深入`，点击后进入原因选择页。
- 原因反馈支持 HMAC 签名校验，并可补充最多 500 字自由文本。
- 每天按 `.env` 的 `DAILY_PUSH_TIME` 推送。
- 每周日 20:00 推送 7 天画像复盘。
- 日推会优先读取 Hermes 原生用户画像（默认 `/home/ubuntu/.hermes/memories/USER.md` 中的 `[arc-reading-profile]`）；`memory/HERMES_NATIVE_PROFILE.md` 仅作为 ARC 本地兼容/诊断快照。
- ARC 会从 SQLite 推荐和反馈历史生成增强版 `RecommendationHistoryContext`，包含 hard exclusions、近期 exact-title cooldown、反馈分布、重复标题/主题、正反馈锚点、负反馈/中性弱匹配信号和 Hermes selection instruction。
- 当前 Hermes wrapper 仍是 `--oneshot` 非交互调用，不提供可控 session/thread id；同一次 `run-daily` 内的短局部链路通过 ARC 显式 `local_session` context 串联，跨天状态只落 Hermes 原生 memory 或 ARC SQLite。
- 未处理反馈会在下一次 `run-daily` 开始时交给 Hermes `reading.feedback.ingest` 判断是否更新主画像；ARC 记录 `hermes_profile_update_events` 审计，并只受控写入 Hermes 原生 `USER.md` 的 `[arc-reading-profile]` entry。
- 管理页提供 `/admin/profile-evidence` 画像证据链，可查看 ARC 本地画像条目的来源证据，并对不贴切画像执行确认、不准确或降权纠偏。
- Hermes provider 默认严格失败：配置 `hermes-agent` 后，如果 Hermes route 无输出或无效 JSON，任务会失败并记录错误，不再静默生成 fallback 内容。
- 深度读书包会写入 `reading_packs`、`artifacts` 和 `library/`，并可在 Web 前端阅读。
- React Web 前端根路径提供移动端兼容的个人阅读门面，入口包括阅读包、分日导读、导读计划和书源管理。
- Hermes reflection 支持可插拔 adapter：默认可用 custom reflection；切换到外部 `hermes-agent` 后走严格模式，失败会记录 failed run，不再静默回退。只有显式配置 `hermes-agent-fallback` 才允许回退到 custom。
- `/metrics` 暴露基础 Prometheus 指标，默认端口 `9108`。
- 提供 systemd service/timer 和 SQLite 备份脚本，支持 7 天服务器试运行。

## 快速开始

```bash
cp .env.example .env
```

至少先填写 `FEEDBACK_SECRET`。如果要真实推送到飞书，还需要填写 `LARK_WEBHOOK_URL` 和 `PUBLIC_BASE_URL`。

```bash
python3 -m app.cli init-db
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
python3 -m app.cli run-daily
```

填写 `.env` 后启用飞书和反馈服务：

```env
CHANNEL=lark
LARK_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
LARK_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://your-domain.example
FEEDBACK_SECRET=change-me
OPENAI_API_KEY=sk-xxx
TAVILY_API_KEY=tvly-xxx
DAILY_RECOMMENDATION_PROVIDER=hermes-agent
READING_PACK_PROVIDER=hermes-agent
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_NATIVE_PROFILE_PATH=memory/HERMES_NATIVE_PROFILE.md
HERMES_NATIVE_USER_MEMORY_PATH=/home/ubuntu/.hermes/memories/USER.md
HERMES_SOUL_PATH=/home/ubuntu/.hermes/SOUL.md
HERMES_NATIVE_PROFILE_MAX_CHARS=6000
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180
```

启动传统 HTML 反馈服务（只保留旧飞书反馈入口，避免和 FastAPI 抢端口）：

```bash
python3 -m app.cli run-server --host 127.0.0.1 --port 8002
```

启动 JSON API：

```bash
python3 -m app.cli run-api --host 127.0.0.1 --port 8000
```

启动 React Web 前端：

```bash
cd web
npm install
npm run dev
```

默认前端网页：

```text
http://localhost:8010/
```

部署到服务器时通常是：

```text
http://<server-host>:8010/
```

启动常驻调度：

```bash
python3 -m app.cli run-scheduler --no-poller
```

Docker 方式：

```bash
docker compose up --build -d
```

## 服务入口

| 服务 | 默认地址 | 说明 |
| --- | --- | --- |
| React Web 前端 | `http://localhost:8010/` | 移动端门面、阅读包、分日导读和管理入口 |
| Web 代理 API | `http://localhost:8010/api/healthz` | 通过 Vite/nginx 访问后端 |
| 后端 API | `http://localhost:8000/api/healthz` | FastAPI JSON API |
| 传统 HTML 服务 | `http://localhost:8002/healthz` | `run-server` 旧反馈入口 |

常用管理页：

```text
http://localhost:8010/admin/weekly-report
http://localhost:8010/admin/profile-evidence
```

管理入口默认账号密码：

```text
admin / 123456
```

可用 `.env` 覆盖：

```env
ARC_ADMIN_USERNAME=admin
ARC_ADMIN_PASSWORD=123456
```

## 常用命令

```bash
python3 -m app.cli init-db
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
python3 -m app.cli run-daily
python3 -m app.cli run-server --host 127.0.0.1 --port 8002
python3 -m app.cli run-api --host 127.0.0.1 --port 8000
python3 -m app.cli show-hermes-profile-sync --json
python3 -m app.cli generate-reading-pack --recommendation-id <id>
python3 -m app.cli ingest-reading-quotes --limit 12
python3 -m app.cli run-weekly-report
python3 -m app.cli generate-reflection --days 7
python3 -m app.cli list-reflections
python3 -m app.cli show-reflection --id 1
python3 -m app.cli approve-reflection --id 1
python3 -m app.cli apply-reflection --id 1
python3 -m app.cli run-scheduler --no-poller
python3 scripts/backup_sqlite.py
```

切到外部 `hermes-agent`：

```env
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
HERMES_AGENT_TIMEOUT_SECONDS=180
```

注意：不要设置无效的 `HERMES_INFERENCE_PROVIDER` / `HERMES_INFERENCE_MODEL` 覆盖项；例如 `provider=custom` 但没有 `CUSTOM_BASE_URL` 会导致 Hermes 返回空输出。

回滚到当前自研 reflection：

```env
HERMES_REFLECTION_PROVIDER=custom
```

Telegram 兼容命令仍可用：

```bash
python3 -m app.cli poll-telegram --once
python3 -m app.cli run-scheduler
```

## 数据库表

- `profile_items`：画像条目，含类别、权重、置信度、证据。
- `profile_item_review_events`：人工确认/纠偏画像条目的审计记录，保留操作前后的权重和置信度。
- `books`：书籍去重信息。
- `recommendations`：每日推荐记录。
- `feedback_events`：飞书反馈链接或 Telegram 按钮反馈，含反馈类型、原因和自由文本。
- `hermes_profile_update_events`：Hermes feedback ingest 审计，记录画像更新决策、证据摘要、状态和错误。
- `reading_packs`：深度读书包结构化内容和生成状态。
- `reading_quotes`：从快读包保存的摘抄，关联推荐、作品、模块和画像 ingest 状态。
- `hermes_quote_profile_update_events`：Hermes quote ingest 审计，记录摘抄批量画像写回决策、偏好摘要和错误。
- `artifacts`：Markdown/HTML 等生成物元数据。
- `run_logs`：任务运行日志。
- `cost_logs`：模型和搜索调用记录。

## 验收

1. `run-daily` 能写入 3 条推荐。
2. 飞书能收到每本书的推荐卡片和“今日画像测试”汇总卡片。
3. 每本书都有 5 个反馈入口。
4. 点击反馈链接后能选择原因，并写入 `feedback_events.reason_code`。
5. 可选自由文本能写入 `feedback_events.free_text`。
6. 再次 `run-daily` 前会处理未回写反馈，调用 Hermes `reading.feedback.ingest`，写入 `hermes_profile_update_events`，并更新 `profile_items`。
7. `run-weekly-report` 能发送画像复盘，包含反馈分布、原因分布、画像变化、可能误解和下周建议。
8. `/admin/profile-evidence` 能显示画像条目的证据链；点击“确认 / 不准确 / 降权”后会写入 `profile_item_review_events`，并相应调整本地画像权重和置信度。
9. `ingest-reading-quotes` 能把 pending/failed 摘抄批量交给 Hermes `reading.quote.ingest`，写入 `hermes_quote_profile_update_events`，并按 applied/skipped/failed 标记 `reading_quotes.profile_ingest_status`。

## 文档

- 项目导读：[docs/README.md](docs/README.md)
- 软件需求说明：[docs/software_requirements.md](docs/software_requirements.md)
- 概要设计：[docs/architecture_overview.md](docs/architecture_overview.md)
- Memory Model：[docs/memory_model.md](docs/memory_model.md)
- 工程文档入口：[docs/engineering/README.md](docs/engineering/README.md)
