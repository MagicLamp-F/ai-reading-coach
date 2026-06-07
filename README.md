# AI 读书私教系统 MVP

这是一个个人版 AI 读书私教 MVP：每天生成 3 本书籍推荐，通过飞书卡片推送和反馈链接收集信号，持续更新 SQLite 用户画像，并支持 7 天画像复盘。

当前默认通道是飞书；Telegram 代码仍保留为兼容通道，不再是国内服务器试运行的主入口。

## 功能

- SQLite 保存画像、书籍、推荐历史、反馈事件、运行日志和调用日志。
- 飞书自定义机器人推送推荐卡片，每本书包含系统假设、画像维度、推荐理由、收益、风险和建议读法。
- 反馈链接支持 `喜欢 / 一般 / 不感兴趣 / 已读 / 想深入`，点击后进入原因选择页。
- 原因反馈支持 HMAC 签名校验，并可补充最多 500 字自由文本。
- Tavily 搜索书籍资料；无 Key 或调用失败时自动使用内置降级书单。
- OpenAI 兼容 Chat Completions 生成主题和推荐；无 Key 或调用失败时自动使用保守默认主题和降级推荐。
- 每天按 `.env` 的 `DAILY_PUSH_TIME` 推送。
- 每周日 20:00 推送 7 天画像复盘。
- 日推会优先读取 ARC 本地 Hermes 画像快照（默认 `memory/HERMES_NATIVE_PROFILE.md`）；缺失或仅含占位信息时，会让 Hermes 基于 ARC 阅读画像和已应用 memory 生成 snapshot，再进入推荐。这个文件不是 Hermes 原生 memory；Hermes 原生用户记忆默认在 `/home/ubuntu/.hermes/memories/USER.md`。
- 未处理反馈会在下一次 `run-daily` 开始时交给 Hermes `reading.feedback.ingest` 判断是否更新主画像；ARC 记录 `hermes_profile_update_events` 审计，并只受控写入 Hermes 原生 `USER.md` 的 `[arc-reading-profile]` entry。
- Hermes provider 默认严格失败：配置 `hermes-agent` 后，如果 Hermes route 无输出或无效 JSON，任务会失败并记录错误，不再静默生成 fallback 内容。
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
HERMES_REFLECTION_PROVIDER=custom
HERMES_NATIVE_PROFILE_PATH=memory/HERMES_NATIVE_PROFILE.md
HERMES_SOUL_PATH=/home/ubuntu/.hermes/SOUL.md
HERMES_NATIVE_PROFILE_MAX_CHARS=6000
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
```

启动反馈 HTTP 服务：

```bash
python3 -m app.cli run-server --host 0.0.0.0 --port 8000
```

启动常驻调度：

```bash
python3 -m app.cli run-scheduler --no-poller
```

Docker 方式：

```bash
docker compose up --build -d
```

## 常用命令

```bash
python3 -m app.cli init-db
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
python3 -m app.cli run-daily
python3 -m app.cli run-server --host 0.0.0.0 --port 8000
python3 -m app.cli show-hermes-profile-sync --json
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
- `books`：书籍去重信息。
- `recommendations`：每日推荐记录。
- `feedback_events`：飞书反馈链接或 Telegram 按钮反馈，含反馈类型、原因和自由文本。
- `hermes_profile_update_events`：Hermes feedback ingest 审计，记录画像更新决策、证据摘要、状态和错误。
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

## 文档

- 工程文档入口：[docs/engineering/README.md](docs/engineering/README.md)
- 当前进展总结：[docs/engineering/10_current_progress_summary.md](docs/engineering/10_current_progress_summary.md)
- 7 天试运行 Runbook：[docs/engineering/09_trial_run_runbook.md](docs/engineering/09_trial_run_runbook.md)
