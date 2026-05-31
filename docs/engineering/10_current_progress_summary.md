# 当前进展总结

更新时间：2026-05-31

## 一句话状态

AI 读书私教系统已经从早期 Telegram MVP 推进到“飞书优先 MVP + hermes-agent 接入边界 + 快速读完包 MVP”的基础搭建阶段。当前核心闭环是：

```text
用户说明书 / SQLite 画像
-> 每日生成 3 本假设驱动推荐
-> 飞书卡片推送
-> 反馈链接收集反馈类型、原因和自由文本
-> SQLite 保存事实
-> 下一次 daily run 回写画像
-> 每周生成 7 天画像复盘
```

Hermes 侧已经完成安装、调用入口准备和真实模型推理 smoke test。当前已经可以通过 `HERMES_REFLECTION_PROVIDER=hermes-agent` 生成 reflection draft。长期记忆写入支持两种模式：默认人工 approve/apply；开启 `HERMES_REFLECTION_AUTO_APPLY=true` 后自动写入 `USER.md` / `MEMORY.md`，并生成 `memory/change_logs` 修改记录。开启 `DAILY_REFLECTION_ENABLED=true` 后可在 `run-daily` 后自动执行。

快速读完包侧已经完成 Hermes 自动飞书初版，并开始补来源层：`run-daily` 可基于每条推荐生成 `reading.fast_read_pack`，把结构化内容写入 SQLite，把长 Markdown 保存为 library artifact，并在飞书推荐卡片里展示快速读完预览。设置 `READING_PACK_PROVIDER=hermes-agent` 后，快速读完包由 Hermes 生成，不再走 fallback 占位内容。当前新增轻量 `BookSourceCollector`，会抓取推荐里的公开 `source_url`、清洗网页文本、写入 `book_sources`，并把来源摘录传入阅读包生成。

Daily 推荐也已增加 Hermes 分支：设置 `DAILY_RECOMMENDATION_PROVIDER=hermes-agent` 后，主题生成和书单筛选走 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`，由 Hermes 使用自己的模型配置完成，`ai-reading-coach` 只负责入库、生成 reading pack 和发飞书。

## 已完成

### 核心业务闭环

- SQLite schema 已包含 `profile_items`、`books`、`recommendations`、`feedback_events`、`run_logs`、`cost_logs`。
- 用户说明书可通过 `seed-profile` 导入为初始画像。
- `run-daily` 会先处理未回写反馈，再生成主题、搜索资料、生成 3 本推荐、写入推荐记录并推送。
- 外部模型或搜索不可用时，会使用默认主题和内置降级书单，保证流程可跑通。
- 反馈会按 `feedback_type + reason_code` 更新画像条目，保留证据来源。

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
- 已保留 `CustomLLMReflectionAdapter` 作为默认实现和 fallback。
- 已新增 `HermesAgentCliAdapter`，通过外部命令接入 Hermes。
- 当前推荐命令为 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`。
- `reflect-json` 负责 stdin JSON 到 Hermes oneshot 调用的协议适配，并在失败时以非 0 退出，方便主项目 fallback。
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

### 快速读完包 MVP

- 新增 `artifacts` 表，用于保存长文本产物路径、hash、类型和元数据。
- 新增 `reading_packs` 表，用于保存 `reading.fast_read_pack` 的结构化内容、状态、route、schema version 和错误信息。
- 新增 `book_sources` 表，用于保存书籍公开来源页面的标题、URL、清洗后摘录和抓取元数据。
- 新增 `reading_pack_sources` 表，用于记录每个 reading pack 实际引用了哪些来源摘录。
- 新增 `app/reading_pack.py`，负责读取推荐上下文、生成 fast read pack、fallback、渲染 Markdown、写入 artifact。
- 新增 `app/source_collector.py`，当前只抓取推荐记录已有的公开 `source_url`，不安装 OpenClaw、不启用浏览器、不抓取内网/localhost。
- 新增 CLI：

```bash
python3 -m app.cli generate-reading-pack --recommendation-id <id>
```

- 当前版本已接入 `run-daily`：默认每条推荐自动生成 reading pack，并把一句话主张、10 分钟路径、核心概念、核心脉络、章节/结构地图、例子/案例、局限和 artifact 归档路径随飞书卡片一起发送。
- 生成 reading pack 前会优先复用已有 `book_sources`；没有来源且 `source_url` 可安全访问时，会抓取公开网页摘录并传给 Hermes。
- Hermes 生成开关：

```env
READING_PACK_PROVIDER=hermes-agent
```

- 手动 CLI 仍保留，用于对历史 recommendation 重新生成。
- 回滚开关：

```env
DAILY_READING_PACKS_ENABLED=false
```

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
- reflection adapter 能向外部命令发送结构化契约，并在外部 agent 失败时 fallback。
- 当前主项目测试记录为 55 tests OK；Hermes/快速读完包改造后的记录为 67 tests OK；来源层新增后的局部测试已通过。
- 快速读完包测试已覆盖新表、来源表、成功生成、fallback、推荐不存在、来源摘录进入 prompt、来源链接关系、飞书预览渲染和 daily 自动生成。
- Hermes daily adapter 测试已覆盖 route payload 和 JSON 解析。

## 尚未完成

- 尚未升级为飞书应用机器人，当前反馈仍会打开浏览器页面。
- 反馈去重和用户身份识别尚未实现；当前适合个人试运行。
- Hermes reflection 链路已经接通；daily 推荐 Hermes 分支已完成单次真实测试，但还未连续观察推荐质量。
- OpenClaw Gateway / Skill 执行层尚未接入。
- 快速读完包尚未接入公开业务页面；飞书里目前只展示预览和服务器 artifact 路径，不是可公网打开的阅读页面。
- 画像类别还未覆盖能量状态、探索倾向、自我叙事等维度。
- 30 天用户模型报告尚未实现。
- 真实服务器上的域名、HTTPS、飞书 webhook、`.env` 和 systemd enable 仍需人工配置。

## 下一步

1. 在服务器上完成 `.env`、公网入口和飞书 webhook 配置。
2. 启动反馈服务，验证 `GET /healthz`。
3. 手动执行一次 `python3 -m app.cli run-daily`，确认飞书收到 3 条推荐卡片和 1 条画像测试汇总卡片。
4. 点击每种反馈至少一次，确认原因选择页、入库和自由文本补充都正常。
5. 启动 daily/weekly systemd timer，按 `09_trial_run_runbook.md` 观察 7 天。
6. 7 天后复盘真实反馈，决定是否调整原因选项、画像更新规则和推荐 prompt。
7. 连续运行 1-2 次 `generate-reflection --days 7 --no-lark`，观察 Hermes 输出质量。
8. 人工审查 draft，再决定是否执行 `approve-reflection` 和 `apply-reflection`。
9. 手动执行一次 `run-daily`，检查飞书卡片里的快速读完预览是否足够有内容。
10. 对生成的 `library/.../reading-pack.md` 做内容质量复盘，重点看公开来源摘录是否显著提升“像读过一遍”的感觉。
11. 试运行稳定后，再进入飞书应用机器人、Hermes route 化、快速读完包公网页面、OpenClaw 和 Skill 化改造。
