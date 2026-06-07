# 软件需求说明

## 1. 项目定位

AI Reading Coach 是一个个人版阅读推荐、阅读包生成和反馈画像系统。它不是单纯的“每日推荐脚本”，而是一个长期阅读闭环：

```text
用户画像
-> 每日推荐
-> 深度读书包
-> 飞书/Web 触达
-> 用户反馈
-> Hermes 主画像更新
-> 下一轮推荐
```

当前项目的业务编排层叫 ARC，即 `ai-reading-coach`。Hermes 是智能生成和主画像判断层。SQLite 是事实账本和审计系统。

## 2. 当前目标

### P0 目标

- 每天推荐适合用户当前阅读阶段的书。
- 推荐必须能解释“为什么适合你”。
- 推荐后能收集反馈，而不是一次性推送。
- 反馈能进入下一轮推荐和画像更新。
- Hermes 作为主画像判断者，ARC 不再把本地 `profile_items` 当成唯一用户画像。
- 系统失败要可见，不允许用 fallback 掩盖 Hermes route 问题。

### 非目标

- 当前不是多人 SaaS。
- 当前不做复杂账号系统。
- 当前不做商业化推荐排序。
- 当前 Web 前端/API 是个人阅读页和管理入口，不是多人 SaaS 后台。
- 当前不允许 Hermes route agent 直接改 ARC SQLite、发消息或任意写文件。

## 3. 用户角色

### 个人用户

使用飞书卡片、阅读页或导读页接收推荐和读书包，提交反馈。

### 系统维护者

运行 CLI、检查 SQLite、查看 metrics、维护 `.env`、处理 Hermes route 失败。

### Hermes

负责生成推荐、读书包、reflection 和主画像更新决策。Hermes 只返回结构化结果；ARC 负责写库、写文件和发送消息。

## 4. 功能需求

### F1. 初始化和配置

系统应支持：

- 从 `.env` 读取配置。
- 初始化 SQLite schema。
- 导入初始用户说明书。
- 配置飞书 webhook、反馈签名 secret、数据库路径、Hermes command、Tavily key。

关键命令：

```bash
python3 -m app.cli init-db
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
```

验收：

- `data/reading_coach.db` 可创建。
- 缺少必要 secret 时，反馈链接不能被伪造为有效提交。

### F2. 每日推荐

系统应支持：

- 读取用户画像、历史反馈、近期推荐和 long-term memory。
- 优先读取 ARC 本地 Hermes 画像快照。
- 调用 Hermes 生成推荐主题和候选书。
- 搜索/采集公开书源。
- 基于来源质量筛选候选。
- 写入 `recommendations`、`books`、`recommendation_candidates`。
- 推送飞书卡片或进入 delivery outbox。

关键命令：

```bash
python3 -m app.cli run-daily
```

验收：

- 生成推荐记录。
- 推荐包含主题、推荐理由、画像映射、系统假设、收益、风险和建议读法。
- Hermes 严格模式下失败会让 run 失败，不生成 fallback 推荐。

### F3. 深度读书包

系统应支持：

- 对推荐书生成 deep read pack。
- 将结构化内容写入 `reading_packs`。
- 将 Markdown artifact 写入 `library/`。
- 记录引用到的 `book_sources`。
- 在飞书卡片和阅读页中展示摘要/入口。

关键命令：

```bash
python3 -m app.cli generate-reading-pack --recommendation-id <id>
```

验收：

- `reading_packs.status='generated'`。
- `generator_provider='hermes-agent'`。
- 有 artifact 记录和本地 Markdown 文件。
- Hermes reading pack 失败时严格暴露，不写 fallback pack。

### F4. 反馈采集

系统应支持：

- 推荐卡片/阅读页提供反馈入口。
- 反馈类型包括：喜欢、一般、不感兴趣、已读、想深入。
- 每类反馈有 reason_code。
- 支持最多 500 字自由文本。
- 使用 HMAC 签名防篡改。
- 写入 `feedback_events`。

入口：

```text
GET /feedback
POST /feedback/free-text
POST /feedback/inline
POST /api/reading-packs/{reading_pack_id}/feedback
```

验收：

- 篡改 recommendation_id、feedback_type、reason_code 或 token 会被拒绝。
- 反馈入库后初始 `processed_at` 为空。

### F5. Hermes 主画像更新

系统应支持：

- `run-daily` 开始时处理未处理反馈。
- 将反馈事件和推荐上下文发送给 Hermes `reading.feedback.ingest`。
- Hermes 返回是否更新 Hermes 原生 USER memory。
- ARC 写入 `hermes_profile_update_events` 审计。
- Hermes 明确要求更新时，ARC 受控 upsert Hermes 原生 `USER.md` 中 `[arc-reading-profile]` entry。
- 再按 ARC 本地规则更新 `profile_items`。
- 成功后标记 `feedback_events.processed_at`。

验收：

- 成功更新时审计 `status='applied'`。
- 跳过时审计 `status='skipped'`，不写 Hermes 原生 USER memory。
- 失败时审计 `status='failed'`，反馈保持未处理，`run-daily` 失败。
- 不允许 fallback。

### F6. ARC 本地 Hermes 画像快照和 Hermes 原生 memory 同步

系统应支持：

- 读取 `memory/HERMES_NATIVE_PROFILE.md` 作为最高优先级画像上下文。
- 明确该文件是 ARC 仓库内的 Hermes 生成画像快照/cache，不是 Hermes 原生 memory。
- 文件缺失或占位时，调用 Hermes `reading.profile.sync_snapshot` 生成。
- 同步 compact entry 到 Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md`。
- 明确 Hermes-agent 项目目录只是代码/安装目录；真实原生 memory 目录由 `HERMES_HOME` 决定。
- 提供诊断命令查看同步状态。

关键命令：

```bash
python3 -m app.cli show-hermes-profile-sync --json
```

验收：

- 输出 ARC 本地 snapshot 是否存在、Hermes 原生 USER memory 路径、是否存在 `[arc-reading-profile]` entry。

### F7. Reflection

系统应支持：

- 生成 7 天阅读反思。
- 支持人工 approve/apply。
- 支持自动 apply。
- 写入 ARC `memory/USER.md` 和 `memory/MEMORY.md`。
- 生成 change log。

关键命令：

```bash
python3 -m app.cli generate-reflection --days 7
python3 -m app.cli approve-reflection --id <id>
python3 -m app.cli apply-reflection --id <id>
```

验收：

- reflection run 成功写入 `reflections`。
- apply 后 memory 文件追加对应条目。

### F8. Guided Reading

系统应支持：

- 从 Markdown/TXT/EPUB 书源创建分日阅读计划。
- 保存书源、计划、计划天和进度事件。
- 推送或展示每日导读。
- 记录完成、继续、太长、不感兴趣等进度反馈。

关键命令：

```bash
python3 -m app.cli create-guided-reading-plan --source-file book.md --title 书名
python3 -m app.cli send-guided-reading-pushes
```

验收：

- 写入 `reading_plans`、`reading_plan_days`。
- 用户打开导读页会记录进度事件。

### F9. Web/API

系统应支持：

- JSON API 读取 reading pack 和 guided reading day。
- JSON API 提交反馈。
- 管理端上传书源、创建阅读计划。
- React Web 前端展示阅读体验。

验收：

- `GET /api/healthz` 返回 ok。
- `GET /api/metrics` 输出 API metrics。
- 阅读包和导读页 API 需要有效签名。

### F10. 运维和观测

系统应支持：

- Prometheus 文本 metrics。
- run_logs 记录任务状态。
- delivery_outbox 重试飞书发送。
- SQLite 备份。
- systemd/nginx 部署文件。

关键命令：

```bash
python3 -m app.cli run-scheduler --no-poller
python3 scripts/backup_sqlite.py
```

验收：

- `run_logs.status` 能区分 running/success/failed。
- Hermes profile update metrics 能按 `applied/skipped/failed` 统计。

## 5. 非功能需求

### 可审计

关键业务动作必须落库：

- 推荐生成：`run_logs`、`recommendations`、`recommendation_candidates`。
- 用户反馈：`feedback_events`。
- Hermes 主画像决策：`hermes_profile_update_events`。
- 读书包：`reading_packs`、`artifacts`。
- Reflection：`reflections`、memory change logs。

### 失败可见

正常 Hermes provider 不允许静默 fallback：

- Hermes daily 失败 -> run failed。
- Hermes reading pack 失败 -> run failed。
- Hermes reflection 失败 -> reflection run failed。
- Hermes feedback ingest 失败 -> audit failed，feedback 未处理，run failed。

### 数据安全

- 反馈 URL 使用 HMAC token。
- Hermes route agent 不直接写 SQLite、不发消息、不任意改 memory。
- ARC 只 upsert Hermes 原生 `USER.md` 的 `[arc-reading-profile]` entry。

### 可维护

- 大改后必须维护 `docs/README.md`、`docs/software_requirements.md`、`docs/architecture_overview.md` 或对应工程文档。
- 大改后必须记录真实验证命令和结果。
- 大改后必须提交代码和文档。

## 6. 当前已验证

最近一次真实正常流程：

```text
feedback_events.id=27
daily run_id=56 success
processed_feedback=1
hermes_profile_update_events.id=1 status=applied confidence=0.91
recommendation_id=69: 围城 / 钱锺书
reading_pack id=40 status=generated generator_provider=hermes-agent
reflection run_id=57 success
```

自动化测试：

```text
python3 -m unittest discover
130 tests OK
```

## 7. 待完成和风险

- API/Web 当前是个人使用界面，仍缺少完整权限、账号和生产级前端测试。
- `.env.example` 已补齐当前 Hermes、source-aware、reading pack 和 reflection 关键配置；真实密钥和公网地址仍需本机 `.env` 配置。
- 多用户身份和反馈去重尚未实现。
- Web 前端部署、HTTPS、公网域名和飞书应用机器人还未完全产品化。
- Hermes 原生 USER memory 写入后，已有 Hermes UI 会话可能不会立刻加载；通常需要新会话。
