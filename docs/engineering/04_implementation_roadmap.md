# 实施路线

## 当前状态快照

截至 2026-05-29，项目已经从早期 Telegram MVP 推进到“飞书优先 MVP + hermes-agent 接入边界”的试运行准备状态：

- 阶段 0 基本完成：项目包含 Docker、systemd service/timer、备份脚本和服务器 Runbook。
- 阶段 1 完成：SQLite、用户说明书导入、每日推荐、反馈回写画像、7 天复盘和基础测试已具备。
- 阶段 2 完成初版：飞书自定义机器人卡片、反馈链接、签名校验、原因选择页和反馈 HTTP 服务已实现。
- 阶段 3 完成初版：推荐记录和飞书卡片已包含 `system_hypothesis` 与 `profile_dimensions`。
- 阶段 4 部分完成：`reason_code`、原因选择页、自由文本补充和部分画像更新规则已实现；仍需用真实 7 天反馈验证原因体系是否足够。
- 阶段 7 已完成接入边界初版：新增 reflection agent adapter，`hermes-agent` 已安装到 `/home/ubuntu/projects/hermes-agent`，通过外部 `reflect-json` wrapper 接入；当前 custom reflection 保留为 fallback，仍需用 7 天数据验证输出质量。
- 阶段 8 以后尚未开始：OpenClaw、Skill 化和 30 天报告仍是后续方向。

## 阶段 0：基础设施准备

目标：先把国内服务器和基础运行环境搭好。

状态：基本完成，代码仓库已包含 Dockerfile、docker-compose、systemd 单元文件、备份脚本和 7 天试运行 Runbook；仍需在真实服务器上完成公网域名、HTTPS 和 `.env` 配置。

建议环境：

```text
腾讯云轻量应用服务器
Ubuntu 24.04 LTS
2 核 4G
70GB SSD
国内地域
```

要做：

- 创建服务器。
- 配置 SSH 登录。
- 创建普通用户。
- 开启防火墙，只放行 SSH 和必要 HTTP/HTTPS。
- 安装 Git、Docker、Docker Compose。
- 拉取项目代码。
- 配置 `.env`。

验收：

- 能 SSH 登录。
- 能运行 `docker version`。
- 能运行当前 Python 项目。
- 不暴露数据库、Docker daemon 等危险端口。

## 阶段 1：当前 Python MVP 冻结

目标：确认当前 Python MVP 能跑通基础链路。

状态：完成。

已完成：

- SQLite 初始化。
- 用户说明书导入。
- 每日推荐 workflow。
- Telegram 推送和按钮反馈框架。
- 飞书优先通道接入前的核心 workflow。
- 反馈回写画像。
- 7 天复盘基础。
- 基础测试。

验收：

- `run-daily` 能生成 3 条推荐。
- 反馈能写入 `feedback_events`。
- `profile_items` 能更新。

## 阶段 2：新增飞书初版通道

目标：把第一交互入口从 Telegram 转为飞书。

状态：完成初版，可进入真实服务器试运行。

初版策略：

```text
飞书自定义机器人推送推荐
+ 每本书附带反馈链接
+ 后端接收反馈链接并写入 SQLite
```

改动：

- 新增 `app/lark.py`，支持飞书自定义机器人文本消息和交互式卡片。
- 新增 `LARK_WEBHOOK_URL` 配置。
- 新增 `LARK_WEBHOOK_SECRET` 配置。
- 新增 `PUBLIC_BASE_URL` 配置。
- 新增 `FEEDBACK_SECRET` 配置。
- 新增 HTTP feedback endpoint：`GET /feedback` 与 `POST /feedback/free-text`。
- 推荐消息已改为飞书交互式卡片，并保留 Telegram 兼容分支。
- 新增飞书发送重试，覆盖频控和临时 5xx。

验收：

- 飞书能收到每日推荐。
- 每本书至少有 5 个反馈入口：喜欢、一般、不感兴趣、已读、想深入。
- 点击反馈链接能进入原因选择页。
- 选择原因后能写入 SQLite。
- 后端返回“已记录”。
- 自由文本补充能更新同一条反馈事件。

## 阶段 3：把推荐改成“假设驱动”

目标：每本推荐都明确说明它在测试哪个用户假设。

状态：完成初版。

改动：

- `recommendations` 增加 `system_hypothesis`。
- `recommendations` 增加 `profile_dimensions`。
- 推荐 prompt 要求输出系统假设。
- 飞书消息展示系统假设和画像维度。
- 每日 3 本推荐后额外发送“今日画像测试”汇总卡片。

验收：

- 每条推荐都能回答“为什么推荐这本书测试用户的哪个维度”。

## 阶段 4：增加原因反馈

目标：让按钮反馈变成可解释信号。

状态：部分完成，待 7 天真实反馈验证。

改动：

- `feedback_events` 增加 `reason_code`。
- 反馈链接支持二级原因选择。
- `feedback_events` 增加自由文本补充能力。
- 不同按钮展示不同原因选项。
- 画像更新规则根据部分 `feedback_type + reason_code` 共同判断。

验收：

- 至少 30% 的反馈包含原因。
- 不感兴趣能区分主题不相关、已掌握、太难、时机不对等情况。
- 真实试运行后复核原因选项是否过细或缺项。

## 阶段 5：升级飞书应用机器人

目标：从反馈链接升级到飞书交互式卡片。

状态：未开始。

改动：

- 创建飞书开放平台应用。
- 配置事件订阅或卡片回调。
- 支持按钮点击直接回调后端。
- 支持卡片状态更新。
- 支持点击后展示原因选择。

验收：

- 不需要打开浏览器即可完成反馈。
- 卡片能显示用户已选择的反馈。
- 回调签名和 token 校验通过。

## 阶段 6：扩展多维画像

目标：从兴趣模型升级成多维用户模型。

状态：部分完成。当前已有长期兴趣、短期关注、知识背景、阅读偏好、反感主题、生活状态、知识缺口、行动阶段；能量状态、探索倾向、自我叙事等仍未落地。

改动：

- 扩展 `ProfileItem.category`。
- 增加知识缺口、行动阶段、能量状态、探索倾向、自我叙事等维度。
- 更新 `build_profile_context()`，按维度分组输出画像。
- 每条画像保留证据来源。

验收：

- 7 天复盘至少覆盖 5 个画像维度。
- 每条画像能追溯到推荐或反馈证据。

## 阶段 7：接入 Hermes 记忆反思

目标：让 Hermes 负责长期记忆和周期性反思。

状态：接入边界初版完成，`hermes-agent==0.14.0` 已在同级目录独立 venv 安装；质量验证待完成。

改动：

- 从 SQLite 导出周期摘要。
- 生成 Hermes 可读上下文。
- Hermes 输出 `USER.md` / `MEMORY.md` patch 草稿。
- 新增 `reflections` 表保存反思结果。
- 新增 `ReflectionAgentAdapter` 抽象。
- 保留当前 custom LLM reflection 作为默认实现和 fallback。
- 新增 `hermes-agent` CLI adapter，使用 stdin/stdout JSON 契约接入外部 `reflect-json` wrapper。
- 初期 memory patch 需要人工确认。

验收：

- 每 7 天能生成一份 Hermes 反思草稿。
- 反思能输出准确观察、系统误解和下周问题。
- `USER.md` / `MEMORY.md` 只在人工 approve/apply 后版本化更新。
- hermes-agent 不存在或失败时，会 fallback 到 custom reflection，不影响 `run-daily`。
- draft reflection 不进入每日推荐上下文。

## 阶段 8：沉淀 Skill 与接入 OpenClaw

目标：把推荐、反馈解释和复盘规范沉淀成可复用 Skill，并逐步引入 OpenClaw。

状态：未开始。

Skill 初版包括：

- 书籍推荐筛选规则。
- 推荐假设生成规则。
- 反馈原因解释规则。
- 多维画像更新规则。
- 每周复盘问题生成规则。

OpenClaw 后续承担：

- 多渠道 Gateway。
- session 管理。
- Skill/tool 权限管理。
- 搜索、总结、推送、反馈处理等执行能力。

验收：

- prompt 硬编码减少。
- 推荐行为能通过 Skill 文件审查和迭代。
- Hermes 可提出 Skill 改进建议，但不自动上线。

## 阶段 9：30 天用户模型报告

目标：验证系统是否真正帮助用户更了解自己。

状态：未开始，需要先完成 7 天试运行并积累稳定反馈数据。

输出：

- 长期兴趣变化。
- 短期关注变化。
- 知识缺口地图。
- 阅读偏好画像。
- 反感模式。
- 行动阶段变化。
- 系统误解清单。
- 下月探索建议。

验收：

- 用户认为报告比初始用户说明书更准确。
- 报告能指出至少 3 个用户此前没有明确表达但认可的观察。
