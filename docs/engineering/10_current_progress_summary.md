# 当前进展总结

更新时间：2026-05-26

## 一句话状态

AI 读书私教系统已经从早期 Telegram MVP 推进到“飞书优先 MVP”的 7 天试运行准备阶段。当前核心闭环是：

```text
用户说明书 / SQLite 画像
-> 每日生成 3 本假设驱动推荐
-> 飞书卡片推送
-> 反馈链接收集反馈类型、原因和自由文本
-> SQLite 保存事实
-> 下一次 daily run 回写画像
-> 每周生成 7 天画像复盘
```

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

## 尚未完成

- 尚未升级为飞书应用机器人，当前反馈仍会打开浏览器页面。
- 反馈去重和用户身份识别尚未实现；当前适合个人试运行。
- Hermes 长期记忆和 `USER.md` / `MEMORY.md` patch 尚未接入。
- OpenClaw Gateway / Skill 执行层尚未接入。
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
7. 试运行稳定后，再进入飞书应用机器人、Hermes 和 Skill 化改造。
