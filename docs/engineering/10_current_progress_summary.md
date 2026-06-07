# 当前进展总结

更新时间：2026-06-07

## 一句话状态

AI 读书私教系统已经从早期 Telegram MVP 推进到“飞书优先 MVP + Hermes 默认生成 + ARC 用户端阅读页”的阶段。当前核心闭环是：

```text
用户说明书 / SQLite 画像
-> Hermes 每日生成假设驱动推荐
-> Hermes 生成长快读包
-> ARC 保存 DB 记录、Markdown artifact 和模块文件
-> 飞书卡片推送预览与 ARC 业务 URL
-> 用户在 ARC 阅读页阅读、分页和反馈
-> 反馈链接收集反馈类型、原因和自由文本
-> SQLite 保存事实
-> 下一次 daily run 回写画像
-> 每周生成 7 天画像复盘
```

2026-06-05 新增 Hermes native profile Phase 1：`run-daily` 会优先读取 `memory/HERMES_NATIVE_PROFILE.md`，缺失或仅含“缺少个人阅读事实”占位时，通过 Hermes `reading.profile.sync_snapshot` 生成 snapshot。snapshot 的主证据来自 ARC SQLite reading profile 和 ARC applied memory；SOUL 只作为低优先级背景。daily prompt 现在按 Priority 1-5 显式分层：Hermes native profile、明确 ARC 反馈、ARC reading profile、ARC applied memory、单次弱信号。

同日追加 Hermes native USER memory 同步：ARC 会把 Hermes 生成的阅读画像 upsert 到 `/home/ubuntu/.hermes/memories/USER.md` 的 `[arc-reading-profile]` entry，让 Hermes UI/CLI 新会话能读到同一条用户阅读画像。该同步只替换 ARC 管理的这一条 memory，保留 Hermes 已有 USER memories；写入超限或路径异常会让流程失败，不走 fallback。

同日将 Hermes provider 改为严格模式：`DAILY_RECOMMENDATION_PROVIDER=hermes-agent`、`READING_PACK_PROVIDER=hermes-agent`、`HERMES_REFLECTION_PROVIDER=hermes-agent` 下，Hermes 失败会让对应 run 失败，不再静默 fallback。真实正常流程已验证：`daily run_id=48` 成功生成《活着》推荐和 Hermes deep read pack，`reflection run_id=49` 成功生成并自动应用 `reflection_id=4`。

Hermes native USER memory 同步后的真实正常流程也已验证：`daily run_id=50` 成功推荐《额尔古纳河右岸》，`reading_pack id=37` 由 `hermes-agent` 生成，`reflection run_id=51` 成功生成并自动应用 `reflection_id=5`；`/home/ubuntu/.hermes/memories/USER.md` 出现 596 字符的 `[arc-reading-profile]` entry。

2026-06-07 继续完成 Hermes 主画像反馈 ingest：`run-daily` 开始处理未处理反馈时，会调用 Hermes `reading.feedback.ingest`，由 Hermes 判断是否更新主画像；ARC 记录 `hermes_profile_update_events` 审计，并只受控 upsert Hermes native `USER.md` 的 `[arc-reading-profile]` entry。失败会记录 `failed` 审计并让本次 run 失败，不走 fallback，也不会把反馈标记 processed。真实正常流程已验证：通过正常 HTTP 反馈入口写入 `feedback_events.id=27` 后，`daily run_id=56` 成功处理 `processed_feedback=1`，Hermes 审计 `hermes_profile_update_events.id=1 status=applied confidence=0.91`，生成推荐《围城》，`reading_pack id=40` 由 `hermes-agent` 生成，`reflection run_id=57` 自动应用 `reflection_id=8`。

技术骨架、运行流程、配置和验证命令见：

```text
docs/engineering/21_technical_project_skeleton.md
```

2026-06-02 已完成 Feishu `11232` 频控修复方向、delivery outbox、默认 Hermes provider、长快读包分段生成、ARC signed reading-pack URL、移动端阅读体验修复和线上 `reading_pack_id=31` 验证。详细总结见：

```text
docs/engineering/development_history/2026-06-02_hermes_arc_delivery_and_reading_ui_summary.md
```

Hermes 侧已经完成安装、调用入口准备和真实模型推理 smoke test。当前已经可以通过 `HERMES_REFLECTION_PROVIDER=hermes-agent` 生成 reflection draft。长期记忆写入支持两种模式：默认人工 approve/apply；开启 `HERMES_REFLECTION_AUTO_APPLY=true` 后自动写入 `USER.md` / `MEMORY.md`，并生成 `memory/change_logs` 修改记录。开启 `DAILY_REFLECTION_ENABLED=true` 后可在 `run-daily` 后自动执行。

快速读完包侧已经完成 Hermes 自动飞书初版，并开始补来源层：`run-daily` 可基于每条推荐生成 `reading.fast_read_pack`，把结构化内容写入 SQLite，把长 Markdown 保存为 library artifact，并在飞书推荐卡片里展示快速读完预览。设置 `READING_PACK_PROVIDER=hermes-agent` 后，快速读完包由 Hermes 生成，不再走 fallback 占位内容。当前新增轻量 `BookSourceCollector`，会抓取推荐里的公开 `source_url`、清洗网页文本、写入 `book_sources`，并把来源摘录传入阅读包生成。

Daily 推荐也已增加 Hermes 分支：设置 `DAILY_RECOMMENDATION_PROVIDER=hermes-agent` 后，主题生成和书单筛选走 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`，由 Hermes 使用自己的模型配置完成，`ai-reading-coach` 只负责入库、生成 reading pack 和发飞书。

Source-aware 推荐筛选已完成 v1：开启 `SOURCE_AWARE_RECOMMENDATIONS=true` 后，daily 会先生成候选书、逐本采集 Tavily/public 来源、计算 `source_coverage_score`，只把达到阈值的候选写成最终推荐。严格模式下如果不足 3 本，不会偷偷补低来源质量书，而是记录 warning 并少发。

完整的“已有能力 / 待验证 / 待做路线 / OpenClaw 位置”总览见：

```text
docs/engineering/15_current_scope_and_next_plan.md
```

## 已完成

### 核心业务闭环

- SQLite schema 已包含 `profile_items`、`books`、`recommendations`、`feedback_events`、`run_logs`、`cost_logs`。
- 用户说明书可通过 `seed-profile` 导入为初始画像。
- `run-daily` 会先处理未回写反馈，再生成主题、搜索资料、生成 3 本推荐、写入推荐记录并推送。
- 正常 Hermes provider 严格失败，不再用 fallback 掩盖 Hermes route 错误；旧 fallback 行为只保留在显式 fallback 或局部单元测试场景。
- 反馈会按 `feedback_type + reason_code` 更新画像条目，保留证据来源。
- 反馈还会先送入 Hermes `reading.feedback.ingest`，由 Hermes 对 native USER memory 更新做决策，并写 `hermes_profile_update_events` 审计。

### 飞书优先通道

- 默认 `CHANNEL=lark`。
- `app/lark.py` 支持飞书自定义机器人文本消息和交互式卡片。
- 推荐卡片包含书名、作者、主题、系统假设、测试画像维度、推荐理由、可能收益、可能不适合原因、建议读法和来源链接。
- 每本书提供 5 个反馈入口：喜欢、一般、不感兴趣、已读、想深入。
- 每日 3 本推荐后，会额外推送“今日画像测试”汇总卡片，集中展示 3 个 `system_hypothesis` 和涉及的 `profile_dimensions`。
- 飞书发送对频控和临时错误有最多 3 次重试。

### 反馈服务

- `run-server` 启动 HTTP 反馈服务。
- `GET /healthz` 返回健康状态。
- `GET /feedback` 校验签名并展示原因选择页或记录反馈。
- `POST /feedback/free-text` 支持对已记录反馈补充最多 500 字自由文本。
- 反馈链接使用 `FEEDBACK_SECRET` 做 HMAC 签名，篡改反馈类型或原因会被拒绝。
- 页面输出对自由文本做 HTML 转义。

### 画像与复盘

- 当前已落地画像类别：长期兴趣、短期关注、知识背景、阅读偏好、反感主题、生活状态、知识缺口、行动阶段。
- 7 天复盘会统计推荐总数、反馈总数、正反馈、命中率、反馈类型分布、原因分布、探索/画像贴合/知识缺口反馈分布。
- 复盘会按证据数量和置信度划分稳定画像、待验证画像、新出现信号和可能误解。
- 复盘会摘要近期自由文本，并给出下周建议探索方向和 3 个反思问题。

### 运维与试运行

- 已提供 Dockerfile 和 docker-compose。
- 已提供 systemd 单元：
  - `ai-reading-coach-server.service`
  - `ai-reading-coach-daily.service`
  - `ai-reading-coach-daily.timer`
  - `ai-reading-coach-weekly.service`
  - `ai-reading-coach-weekly.timer`
- 已提供 SQLite 备份脚本 `scripts/backup_sqlite.py`，默认保留最近 14 个备份。
- 已提供 7 天试运行 Runbook：`docs/engineering/09_trial_run_runbook.md`。

### Hermes 接入边界

- `hermes-agent==0.14.0` 已安装到 `/home/ubuntu/projects/hermes-agent/.venv`。
- Hermes CLI 可用：`hermes`、`hermes-agent`、`hermes-acp`。
- 已在主项目中抽象 `ReflectionAgentAdapter`。
- 已保留 `CustomLLMReflectionAdapter` 作为默认实现；只有显式配置 `HERMES_REFLECTION_PROVIDER=hermes-agent-fallback` 才作为 fallback。
- 已新增 `HermesAgentCliAdapter`，通过外部命令接入 Hermes。
- 当前推荐命令为 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`。
- `reflect-json` 负责 stdin JSON 到 Hermes oneshot 调用的协议适配，并在失败时以非 0 退出；正常 Hermes provider 会让 ARC run 失败。
- `reflect-json --debug-smoke` 已能通过 Hermes 返回可见模型输出。
- 主项目已通过 hermes-agent provider 生成 reflection draft：`id=3`，状态为 `draft`。
- 默认模式下，`generate-reflection` 只生成 draft；`approve-reflection` 和 `apply-reflection` 保留为人工审查入口。
- 自动化模式已支持：

```env
HERMES_REFLECTION_AUTO_APPLY=true
DAILY_REFLECTION_ENABLED=true
DAILY_REFLECTION_DAYS=1
```

- 自动 apply 会写入 `memory/change_logs/YYYY-MM-DD_reflection_<id>_auto.md`。

### Hermes Daily 推荐分支

- 新增 `app/daily_agent_adapter.py`。
- 新增配置：

```env
DAILY_RECOMMENDATION_PROVIDER=hermes-agent
```

- 该分支下，`run-daily` 的主题和书单生成走 Hermes wrapper。
- wrapper route：
  - `reading.recommend.intent`
  - `reading.recommend.generate`
- 已完成真实测试：`run_id=27`，生成 3 本书并走飞书发送路径。
- 测试 run 的 `api_calls=0`，说明没有使用项目自己的 OpenAI client 生成 daily 推荐。
- 已完成完整 Hermes 测试：`run_id=28`，推荐和快速读完包都走 Hermes，3 个 reading pack 状态均为 `generated`。
- 已新增 source-aware candidate ranking：候选书写入 `recommendation_candidates`，最终推荐前先检查来源质量。
- 2026-06-05 后正常 Hermes provider 为严格模式：Hermes daily route 返回空 stdout、无效 JSON 或无可用书籍时，`run-daily` 标记失败，不再写 fallback 推荐。

### Hermes Native USER Primary Profile

- Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md` 中的 `[arc-reading-profile]` 是当前主画像读源。
- `memory/HERMES_NATIVE_PROFILE.md` 现在只作为 ARC 兼容/诊断快照；原生 USER entry 缺失时才用它生成并同步 compact entry。
- 新增 `HermesNativeProfileProvider`：
  - 优先读取 Hermes 原生 USER memory。
  - snapshot 缺失时调用 Hermes `reading.profile.sync_snapshot` 生成。
  - 生成失败时让 daily run 失败，不再把 SOUL 原文冒充用户画像。
  - 将 snapshot 或 Hermes 返回的 compact entry 同步到 `/home/ubuntu/.hermes/memories/USER.md`。
- native USER memory 同步使用 `[arc-reading-profile]` 标记 upsert，只替换这一条 entry，不覆盖 Hermes 其它 USER memories。
- `/metrics` 暴露 `reading_coach_hermes_native_profile_loads_total`，按 `native_user_memory`、`compat_snapshot`、`generated_native_user_memory`、`soul_fallback`、`missing` 统计。
- 2026-06-05 真实测试确认：当前 `/home/ubuntu/.hermes/SOUL.md` 是 Hermes Agent 身份说明，不是用户画像；后续已改为把 ARC evidence 传给 Hermes 生成 snapshot，并刷新出包含经典名著/高口碑文学/科幻、个人知识管理、软件工程实践和 AI Agent 商业化降频判断的可用画像。

### RecommendationHistoryContext

- ARC 从 SQLite `recommendations` 和 `feedback_events` 生成 `RecommendationHistoryContext`。
- 该上下文包含 hard exclusions、negative feedback、positive anchors、history fatigue 和 recent recommendations。
- Hermes daily routes `reading.recommend.intent` 和 `reading.recommend.generate` 都会收到该上下文，用于语义选书和避让。
- 推荐历史不写入 Hermes 原生 USER memory；它是 ARC 事实账本的一部分。

### Hermes Feedback Ingest

- 新增 `app/profile_ingest.py`，通过 Hermes route `reading.feedback.ingest` 和 `profile_update_v1` 输出契约处理反馈。
- 新增 `hermes_profile_update_events` 审计表，记录 `applied/skipped/failed`、native memory path、memory entry、rationale、confidence、evidence summary、错误和原始响应。
- `process_feedback()` 在 ARC `profile_items` 更新前调用 Hermes ingest；成功后写审计，失败时写 `failed` 审计并抛错，反馈保持未处理。
- `/metrics` 暴露 `reading_coach_hermes_profile_updates_total{status=...}`。
- 新增 `show-hermes-profile-sync` CLI，查看 `memory/HERMES_NATIVE_PROFILE.md` 和 `/home/ubuntu/.hermes/memories/USER.md` 的同步状态。
- `/home/ubuntu/projects/hermes-agent/bin/reflect-json` 已补 `profile_update_v1` 标准化；该文件不在 ARC git 仓库内，需要外部环境单独维护。

### 快速读完包 MVP

- 新增 `artifacts` 表，用于保存长文本产物路径、hash、类型和元数据。
- 新增 `reading_packs` 表，用于保存 `reading.fast_read_pack` 的结构化内容、状态、route、schema version 和错误信息。
- 新增 `book_sources` 表，用于保存书籍公开来源页面的标题、URL、清洗后摘录和抓取元数据。
- 新增 `reading_pack_sources` 表，用于记录每个 reading pack 实际引用了哪些来源摘录。
- 新增 `recommendation_candidates` 表，用于保存候选书、来源评分、最终评分、入选/拒绝状态和拒绝原因。
- 新增 `app/reading_pack.py`，负责读取推荐上下文、生成 fast read pack、fallback、渲染 Markdown、写入 artifact。
- 新增 `app/source_collector.py`，当前只抓取推荐记录已有的公开 `source_url`，不安装 OpenClaw、不启用浏览器、不抓取内网/localhost。
- source collector 已支持 Tavily source grounding v1.1：可从 `TAVILY_API_KEY` 或 `/home/ubuntu/.config/tavily/api_key` 读取 key，按书名/作者做 3 类 advanced search，优先使用 Tavily `raw_content`，再计算来源质量。
- 新增 CLI：

```bash
python3 -m app.cli generate-reading-pack --recommendation-id <id>
```

- 当前版本已接入 `run-daily`：默认每条推荐自动生成 reading pack，并把一句话主张、10 分钟路径、核心概念、核心脉络、章节/结构地图、例子/案例、局限和 artifact 归档路径随飞书卡片一起发送。
- 生成 reading pack 前会优先复用已有 `book_sources`；没有来源且 `source_url` 可安全访问时，会抓取公开网页摘录并传给 Hermes。
- reading pack 和飞书预览会显示来源质量，例如 `source_rich`、`source_usable`、`source_limited`、`source_missing`，避免把来源不足的包伪装成深度快读包。
- Hermes 生成开关：

```env
READING_PACK_PROVIDER=hermes-agent
```

- 手动 CLI 仍保留，用于对历史 recommendation 重新生成。
- 回滚开关：

```env
DAILY_READING_PACKS_ENABLED=false
```

- 2026-06-05 后，如果配置 `READING_PACK_PROVIDER=hermes-agent`，Hermes reading pack 失败会让 daily run 失败，不再写 `fallback` reading pack。

## 已验证

自动化测试覆盖了以下关键点：

- 飞书签名生成。
- 飞书 webhook 禁用时不发 HTTP。
- 推荐卡片展示系统假设、画像维度和 5 个反馈按钮。
- “今日画像测试”汇总卡片展示 3 个假设和去重后的画像维度。
- 飞书频控和临时错误重试。
- 外部模型和搜索失败时仍能生成 3 条降级推荐。
- 反馈原因选择页不会提前写入反馈。
- 带原因反馈会写入 `feedback_events.reason_code`。
- 自由文本补充会更新同一条反馈，并限制长度、转义 HTML。
- 篡改签名会被拒绝。
- reflection adapter 能向外部命令发送结构化契约；严格 Hermes provider 失败时记录 failed run，显式 fallback provider 仍有单元测试覆盖。
- 当前主项目测试记录为 55 tests OK；Hermes/快速读完包改造后的记录为 67 tests OK；Tavily raw-content source grounding 接入后完整测试为 75 tests OK。
- 快速读完包测试已覆盖新表、来源表、成功生成、fallback、推荐不存在、来源摘录进入 prompt、来源链接关系、飞书预览渲染和 daily 自动生成。
- Hermes daily adapter 测试已覆盖 route payload 和 JSON 解析。
- Tavily key 文件读取和 source collector search enrichment 已有单元测试；真实 Tavily smoke 已确认 key 文件可读取、advanced raw-content search 返回结果，并能把 `Monetizing Innovation` 的来源质量提升到 `source_usable`。
- Source-aware candidate ranking 已完成受控 smoke：临时数据库、禁用飞书、禁用 reading pack，Hermes 生成 3 个候选，其中 2 个达到 `source_usable` 并被推荐，1 个 `source_limited` 被拒绝。
- 真实 daily run `run_id=32` 已完成 source-aware 全链路：3 个候选全部 `source_rich` 并入选，3 个 reading pack 均由 `hermes-agent` 生成，无 run warning。后续修正了 reading pack 只取 3 条来源的问题，重生成推荐 `54` 后 source quality 为 `source_rich`。
- 2026-06-07 完整测试为 `130 tests OK`。
- 真实正常流程确认 Hermes 会构造主画像更新：`feedback_events.id=27` 通过 HTTP `/feedback/inline` 写入；`run-daily` 中 Hermes `reading.feedback.ingest` 返回 `applied`，审计 `hermes_profile_update_events.id=1`，并同步 native USER memory。

## 尚未完成

- 尚未升级为飞书应用机器人，当前反馈仍会打开浏览器页面。
- 反馈去重和用户身份识别尚未实现；当前适合个人试运行。
- Hermes reflection 链路已经接通；daily 推荐 Hermes 分支已完成真实正常流程测试，但还未连续观察推荐质量。
- OpenClaw Gateway / Skill 执行层尚未接入。
- 快速读完包尚未接入公开业务页面；飞书里目前只展示预览和服务器 artifact 路径，不是可公网打开的阅读页面。
- 画像类别还未覆盖能量状态、探索倾向、自我叙事等维度。
- 30 天用户模型报告尚未实现。
- 真实服务器上的域名、HTTPS、飞书 webhook、`.env` 和 systemd enable 仍需人工配置。

## 下一步

### P0：跑稳当前闭环

1. 确认服务器 `.env`、飞书 webhook、反馈服务公网入口和 systemd timer。
2. 连续运行 7 天 daily/weekly，观察 run log、飞书推送、反馈写入和 SQLite 备份。
3. 每天检查 reading pack 是否阻断日推；严格 Hermes provider 下失败应及时暴露并修复，不应静默 fallback。
4. 7 天后复盘真实反馈，决定是否调整原因选项、画像更新规则和推荐 prompt。

### P0：来源收集 v2

1. 每本书从单个 `source_url` 扩展到 3-5 条合法公开来源。
2. 增加来源类型：官方页、出版社页、目录页、样章页、作者访谈、公开视频文字稿、高质量公开书评。
3. 增加来源评分、去重、失败原因入库。
4. reading pack 明确区分“来源支持内容”和“模型推断内容”。

### P1：快速读完包质量升级

1. 把 pack 从“结构化总结”升级为“粗读完整本书体验”。
2. 增加章节/部分地图、具体例子、核心论证链、反对意见、用户应用题。
3. 增加质量字段：`source_coverage`、`chapter_confidence`、`example_density`、`user_fit_score`。
4. 增加 reading pack 反馈按钮，用反馈判断下次应该补目录、补案例还是补章节结构。

### P1：业务页面

1. 做 reading pack 详情页和历史书库页。
2. 飞书卡片只做提醒和预览，完整阅读与复盘放到页面。
3. 页面展示推荐、来源、阅读包、反馈和画像变化。

### P2：OpenClaw / Skill

OpenClaw 暂不作为当前 blocker。建议先做 source collector v2；只有当普通 HTTP/search 无法处理复杂网页、浏览器流程或多步骤资料收集时，再把 OpenClaw 作为隔离的工具编排层接入。

OpenClaw 接入原则：

- 独立目录 `/home/ubuntu/projects/openclaw`。
- 白名单 skill。
- 不给 shell/SSH/系统权限。
- 不读取 `.env`。
- 只输出 source JSON，由 `ai-reading-coach` 审核入库。
