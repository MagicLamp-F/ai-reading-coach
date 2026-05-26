# 7 天试运行 Runbook

本 Runbook 用于把当前飞书推荐 + 反馈 + 画像更新 + 7 天复盘 MVP 放到服务器上稳定试运行 7 天。

边界：

- 不接 Hermes/OpenClaw。
- 不修改 SSH、防火墙、用户权限。
- 真实密钥只放 `.env`，不要写进文档、日志或命令输出。

## 1. systemd 文件

项目内已生成：

```text
deploy/systemd/ai-reading-coach-server.service
deploy/systemd/ai-reading-coach-daily.service
deploy/systemd/ai-reading-coach-daily.timer
deploy/systemd/ai-reading-coach-weekly.service
deploy/systemd/ai-reading-coach-weekly.timer
```

安装时手动复制：

```bash
sudo cp deploy/systemd/ai-reading-coach-*.service /etc/systemd/system/
sudo cp deploy/systemd/ai-reading-coach-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
```

不要在未确认 `.env` 和数据库状态前 enable。

`.env` 至少要确认：

- `CHANNEL=lark`
- `LARK_WEBHOOK_URL` 已填入真实飞书自定义机器人 webhook。
- `PUBLIC_BASE_URL` 是用户能打开的公网地址。
- `FEEDBACK_SECRET` 非空；默认飞书通道会用它生成反馈链接签名。

## 2. 启动和停止反馈服务

启动：

```bash
sudo systemctl start ai-reading-coach-server.service
```

停止：

```bash
sudo systemctl stop ai-reading-coach-server.service
```

查看状态：

```bash
systemctl status ai-reading-coach-server.service
```

验证 HTTP：

```bash
curl -sS http://127.0.0.1:8000/healthz
```

预期返回：

```text
ok
```

## 3. 定时任务

每日推荐：每天 08:00 执行 `python3 -m app.cli run-daily`。

周报：每周日 20:00 执行 `python3 -m app.cli run-weekly-report`。

启动 timer：

```bash
sudo systemctl start ai-reading-coach-daily.timer
sudo systemctl start ai-reading-coach-weekly.timer
```

确认 timer：

```bash
systemctl list-timers 'ai-reading-coach-*'
```

确认下一次触发时间：

```bash
systemctl status ai-reading-coach-daily.timer
systemctl status ai-reading-coach-weekly.timer
```

确认执行历史：

```bash
journalctl -u ai-reading-coach-daily.service -n 100 --no-pager
journalctl -u ai-reading-coach-weekly.service -n 100 --no-pager
```

如确认无误，再手动 enable：

```bash
sudo systemctl enable ai-reading-coach-server.service
sudo systemctl enable ai-reading-coach-daily.timer
sudo systemctl enable ai-reading-coach-weekly.timer
```

## 4. 查看日志

systemd 日志：

```bash
journalctl -u ai-reading-coach-server.service -f
journalctl -u ai-reading-coach-daily.service -n 100 --no-pager
journalctl -u ai-reading-coach-weekly.service -n 100 --no-pager
```

应用日志：

```bash
tail -n 200 logs/reading_coach.log
tail -n 200 logs/feedback_server.log
```

不要把 `.env` 内容复制到排障记录里。

## 5. 手动运行

初始化数据库：

```bash
python3 -m app.cli init-db
```

手动运行每日推荐：

```bash
python3 -m app.cli run-daily
```

手动运行周报：

```bash
python3 -m app.cli run-weekly-report
```

手动备份：

```bash
python3 scripts/backup_sqlite.py
```

## 6. 查询反馈

最近反馈：

```bash
sqlite3 data/reading_coach.db "
SELECT f.id, f.feedback_type, f.reason_code, f.processed_at, r.theme, b.title
FROM feedback_events f
JOIN recommendations r ON r.id = f.recommendation_id
JOIN books b ON b.id = r.book_id
ORDER BY f.id DESC
LIMIT 20;"
```

未处理反馈：

```bash
sqlite3 data/reading_coach.db "
SELECT COUNT(*) AS unprocessed
FROM feedback_events
WHERE processed_at IS NULL;"
```

最近运行：

```bash
sqlite3 data/reading_coach.db "
SELECT id, run_type, status, started_at, finished_at, error_message
FROM run_logs
ORDER BY id DESC
LIMIT 20;"
```

## 7. 备份和恢复 SQLite

备份脚本：

```bash
python3 scripts/backup_sqlite.py
```

输出目录：

```text
backups/
```

文件名格式：

```text
reading_coach_YYYYMMDD_HHMMSS.db
```

脚本只保留最近 14 个备份。

恢复前先停服务：

```bash
sudo systemctl stop ai-reading-coach-server.service
```

恢复示例：

```bash
cp data/reading_coach.db data/reading_coach.db.before_restore
cp backups/reading_coach_YYYYMMDD_HHMMSS.db data/reading_coach.db
python3 -m app.cli init-db
sudo systemctl start ai-reading-coach-server.service
```

恢复后验证：

```bash
curl -sS http://127.0.0.1:8000/healthz
sqlite3 data/reading_coach.db "SELECT COUNT(*) FROM recommendations;"
```

## 8. 7 天观察清单

每天 08:10 检查：

- 飞书是否收到 3 条推荐。
- 每条推荐是否包含系统假设、测试画像维度、反馈按钮。
- `run_logs` 最新 `daily_recommendation` 是否为 `success`。
- 是否出现飞书频控、HTTP 临时错误或发送失败。

每天 12:00 和 22:00 检查：

- 飞书反馈链接是否能打开原因选择页。
- 点击原因后是否返回“已记录”。
- `feedback_events.reason_code` 是否有写入。
- `feedback_events.processed_at` 是否在下一次 `run-daily` 后被填充。

每天结束前检查：

- `profile_items` 是否有合理新增或权重变化。
- `not_interested` 是否通过 `reason_code` 被分流到知识背景、阅读偏好、知识缺口或短期关注。
- 备份是否成功生成。

周日 20:10 检查：

- 飞书是否收到 7 天画像复盘。
- 报告是否包含 feedback_type 分布。
- 报告是否包含 reason_code 分布。
- 报告是否包含近期 profile_items 变化。
- 报告是否给出系统可能误解和下周建议探索方向。

## 9. 常见问题

### 飞书频控

当前飞书发送会对频控和临时错误进行最多 3 次尝试。仍失败时，任务会失败并写入 `run_logs.error_message`。

查看：

```bash
journalctl -u ai-reading-coach-daily.service -n 100 --no-pager
sqlite3 data/reading_coach.db "SELECT id, status, error_message FROM run_logs ORDER BY id DESC LIMIT 10;"
```

### 反馈页打不开

先看本机服务：

```bash
curl -sS http://127.0.0.1:8000/healthz
systemctl status ai-reading-coach-server.service
```

再看公网入口和安全组。不要在项目脚本里修改防火墙。

### Timer 没执行

检查 timer：

```bash
systemctl list-timers 'ai-reading-coach-*'
journalctl -u ai-reading-coach-daily.timer -n 50 --no-pager
journalctl -u ai-reading-coach-weekly.timer -n 50 --no-pager
```
