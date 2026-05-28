# 服务器 Codex 执行 Prompt：飞书初版通道

> 用途：在云服务器上的 Codex CLI 中粘贴本 Prompt，让它在服务器本地实现飞书初版闭环。
>
> 安全要求：不要把真实 `LARK_WEBHOOK_URL`、`LARK_WEBHOOK_SECRET`、模型 API Key 写入仓库、README 或测试文件。真实值只写入服务器 `.env`。

## 前置环境

服务器已经具备：

```text
Ubuntu
Python
Docker 可选
Codex CLI
模型中转 API
飞书自定义机器人 Webhook
```

项目目录建议：

```bash
~/repos/ai-reading-coach
```

## 真实配置只写入 .env

在服务器项目目录创建 `.env`：

```bash
cat > .env <<'EOF'
CHANNEL=lark
LARK_WEBHOOK_URL=填入飞书机器人Webhook
LARK_WEBHOOK_SECRET=填入飞书机器人签名密钥
PUBLIC_BASE_URL=http://服务器公网IP:8000
FEEDBACK_SECRET=用 openssl rand -hex 32 生成
DATABASE_URL=sqlite:///data/reading_coach.db
DAILY_PUSH_TIME=08:00
TIMEZONE=Asia/Shanghai
HTTP_TIMEOUT_SECONDS=20
MAX_DAILY_SEARCH_CALLS=6
MAX_DAILY_MODEL_CALLS=4
EOF

chmod 600 .env
```

生成 `FEEDBACK_SECRET`：

```bash
openssl rand -hex 32
```

## 粘贴给 Codex 的最终 Prompt

```text
请在当前服务器本地目录实现项目。当前目录应为 ~/repos/ai-reading-coach；如果目录不存在，请创建它。

请先阅读或创建以下工程文档，并以这些文档为准：
- docs/README.md
- docs/engineering/README.md
- docs/engineering/00_project_charter.md
- docs/engineering/01_system_architecture.md
- docs/engineering/04_implementation_roadmap.md
- docs/engineering/06_lark_first_integration.md
- docs/engineering/07_server_bootstrap_codex_manual.md

当前只实现“阶段 2：新增飞书初版通道”。

核心目标：
通过飞书自定义机器人推送每日书籍推荐，每本书包含 5 个反馈链接；用户点击反馈链接后，后端写入 SQLite，并返回“已记录”。这是推荐 + 反馈 + 用户建模闭环的第一版。

范围要求：
1. 飞书初版通道不要直接依赖 Hermes；Hermes 后续通过 reflection agent adapter 独立接入，不能影响飞书推荐与反馈闭环。
2. 暂时不要接 OpenClaw。
3. 暂时不要接 Telegram。
4. 暂时不要做多用户系统。
5. 暂时不要做复杂前端。
6. 暂时不要把任何真实密钥、Webhook、API Key 写入仓库。

必须实现：
1. Python 后端项目结构。
2. SQLite 数据库初始化。
3. 保存推荐记录、反馈记录、画像条目、运行日志。
4. 飞书自定义机器人发送能力。
5. 飞书签名校验支持：使用 LARK_WEBHOOK_SECRET 对机器人消息签名。
6. 每日推荐工作流：先可以使用内置 fallback 推荐，后续再接模型。
7. 每本推荐生成反馈链接：
   - like
   - neutral
   - not_interested
   - already_read
   - go_deeper
8. HTTP feedback endpoint：
   - 校验 recommendation_id 是否存在
   - 校验 feedback_type 是否为合法枚举
   - 校验 FEEDBACK_SECRET 生成的签名或 token
   - 写入 feedback_events
   - 返回简洁页面或文本：“已记录”
9. 配置项通过 .env 读取：
   - CHANNEL
   - LARK_WEBHOOK_URL
   - LARK_WEBHOOK_SECRET
   - PUBLIC_BASE_URL
   - FEEDBACK_SECRET
   - DATABASE_URL
   - DAILY_PUSH_TIME
   - TIMEZONE
10. 提供 CLI 命令：
   - init-db
   - seed-profile
   - run-daily
   - run-server --host 0.0.0.0 --port 8000
   - run-weekly-report
11. 增加必要测试：
   - 飞书签名生成
   - 反馈链接签名生成和校验
   - feedback endpoint 写入数据库
   - 画像反馈处理
12. 更新 README，说明如何配置 .env、如何运行、如何验证飞书推送。

实现建议：
1. 使用 Python 标准库优先，避免引入不必要依赖。
2. HTTP server 可先用标准库 http.server 实现最小反馈入口。
3. 飞书发送使用 webhook JSON POST。
4. 飞书自定义机器人签名规则：timestamp + "\n" + secret 作为 HMAC-SHA256 输入，输出 base64。
5. 反馈链接签名不要使用飞书 secret，单独使用 FEEDBACK_SECRET。
6. 所有外部请求必须有 timeout。
7. 日志中不要打印完整密钥、Webhook 或 token。

验收命令：
1. 运行单元测试。
2. 初始化数据库。
3. 运行 run-server，监听 0.0.0.0:8000。
4. 运行 run-daily，飞书应收到推荐消息。
5. 点击任意反馈链接，页面显示“已记录”。
6. 查询 SQLite，确认 feedback_events 有记录。

请先输出简短实现计划，然后直接实施。实施完成后，列出：
1. 修改了哪些文件
2. 如何配置 .env
3. 如何运行测试
4. 如何启动服务
5. 如何验证飞书推送和反馈入库
```

## 服务器防火墙

初版反馈链接使用 `:8000` 时，需要在腾讯云防火墙临时开放：

```text
TCP 8000
来源：建议先限制为你的公网 IP；如需手机点击，再临时开放 0.0.0.0/0
```

长期建议改为：

```text
HTTPS 443
Nginx/Caddy 反向代理
不直接暴露 8000
```
