# 运行与验收

## 1. 服务器建议

当前推荐：

```text
腾讯云轻量应用服务器
2 核 4G
70GB SSD
Ubuntu 24.04 LTS
国内地域
```

原因：

- 国内模型/API 访问更稳定。
- 飞书/企业微信等国内应用接入更顺。
- 2 核 4G 足够运行 Python 后端、SQLite、Docker、Hermes/OpenClaw 实验。
- 70GB SSD 足够第一阶段长期试验。

## 2. 基础安全

初期只开放必要端口：

```text
22/tcp SSH
80/tcp HTTP，仅当需要反馈链接或证书申请时开放
443/tcp HTTPS，建议正式反馈入口使用
```

不要开放：

```text
Docker daemon
SQLite
Redis
未鉴权后台
任意调试端口
```

基本要求：

- SSH 使用强密码或密钥。
- `.env` 不提交 Git。
- `FEEDBACK_SECRET` 必须配置。
- 飞书 webhook、app secret、模型 API key 只放环境变量。
- 服务器安全组只开放必要端口。
- 定期备份 SQLite。

## 3. 本地或服务器运行

初始化：

```bash
cp .env.example .env
```

先填写 `.env` 中的 `FEEDBACK_SECRET`。默认 `CHANNEL=lark` 时，系统会为每条推荐生成签名反馈链接，即使暂时不配置飞书 webhook，也需要这个 secret。

```bash
python3 -m app.cli init-db
python3 -m app.cli seed-profile --file prompts/user_manual.example.md
```

单次运行：

```bash
python3 -m app.cli run-daily
python3 -m app.cli run-weekly-report
```

反馈 HTTP 服务：

```bash
python3 -m app.cli run-server --host 0.0.0.0 --port 8000
```

常驻运行：

```bash
python3 -m app.cli run-scheduler --no-poller
```

Docker：

```bash
docker compose up --build -d
```

## 4. 配置项

当前已有：

```env
CHANNEL=lark
LARK_WEBHOOK_URL=
LARK_WEBHOOK_SECRET=
PUBLIC_BASE_URL=https://your-domain.example
FEEDBACK_SECRET=
DATABASE_URL=sqlite:///data/reading_coach.db
DAILY_PUSH_TIME=08:00
TIMEZONE=Asia/Shanghai
MAX_DAILY_SEARCH_CALLS=6
MAX_DAILY_MODEL_CALLS=4
HTTP_TIMEOUT_SECONDS=20
```

飞书应用机器人进阶版需要新增：

```env
LARK_APP_ID=
LARK_APP_SECRET=
LARK_VERIFICATION_TOKEN=
LARK_ENCRYPT_KEY=
```

模型/API 配置按实际国内服务商补充。

## 5. 可观测性

当前系统提供：

- `logs/reading_coach.log`
- `run_logs`
- `cost_logs`
- `/metrics`

需要重点观察：

- 每日任务是否成功。
- 飞书推送是否成功。
- 反馈是否入库。
- 未处理反馈是否堆积。
- API 调用次数是否超预期。
- 画像条目是否有证据。

基础指标：

```text
reading_coach_profile_items
reading_coach_runs_total
reading_coach_feedback_total
```

## 6. 7 天验收

目标：验证基础闭环是否成立。

检查项：

- 每天是否生成 3 本推荐。
- 飞书是否能稳定收到推荐。
- 每本推荐是否包含系统假设。
- 用户是否完成按钮反馈。
- 是否至少 30% 的反馈包含原因。
- 反馈是否写入 SQLite。
- 画像是否发生可解释变化。
- 7 天复盘是否包含准确观察和系统误解。

通过标准：

```text
推荐完成率 >= 85%
反馈率 >= 60%
原因反馈率 >= 30%
复盘准确观察 >= 3 条
系统误解 >= 1 条
画像条目均有证据来源
```

## 7. 30 天验收

目标：验证系统是否真的帮助用户更了解自己。

检查项：

- 长期兴趣是否有变化曲线。
- 短期关注是否能与实际阶段对应。
- 是否识别出重复出现的知识缺口。
- 是否区分不喜欢主题、已掌握、时机不对和表达不喜欢。
- 是否能总结阅读偏好。
- 是否能指出用户反复回避但可能重要的主题。

通过标准：

```text
用户认为 30 天画像报告明显优于初始说明书
至少 3 条观察让用户觉得“我之前没明确说，但确实如此”
至少 2 条系统误解被记录并修正
推荐策略能基于复盘做一次人审后的调整
```

## 8. 风险与控制

### 画像漂移

风险：单次反馈错误改变长期画像。

控制：

- 单次反馈只做小幅更新。
- 画像区分待验证和稳定。
- 至少 3 条证据后再进入稳定状态。

### 过度打扰

风险：原因反馈和反思问题太多，用户不愿继续使用。

控制：

- 按钮反馈始终最低成本。
- 原因反馈可跳过。
- 每周反思只需回答 1-2 个问题。

### Agent 黑箱总结

风险：Hermes 总结看似合理但缺乏证据。

控制：

- 每条画像必须关联证据。
- SQLite 保留原始事件。
- memory patch 初期人审。

### 成本失控

风险：搜索和模型调用过多。

控制：

- 每日调用上限。
- 成本日志。
- 失败降级。

### 反馈链接被滥用

风险：别人伪造反馈链接写入数据库。

控制：

- 反馈链接必须带签名或 secret。
- 反馈接口只接受有限枚举值。
- 记录来源 IP 和 user agent。
- 后续升级为飞书卡片回调签名校验。
