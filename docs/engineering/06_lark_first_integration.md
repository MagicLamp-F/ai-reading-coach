# 飞书优先接入方案

## 1. 为什么先接飞书

当前约束：

- 用户主要使用国内模型/API。
- 服务器计划买腾讯云国内轻量服务器。
- Telegram 在国内服务器上直连不稳定。
- 微信个人号机器人不建议使用，存在封号和失效风险。
- 企业微信群机器人交互能力偏弱。

因此第一阶段推荐飞书：

- 国内服务器访问飞书更稳定。
- 飞书消息卡片适合推荐、按钮反馈和原因选择。
- 飞书文档可用于后续沉淀复盘报告。
- 可以先用简单 webhook，再升级到正式应用机器人。

## 2. 两阶段接入策略

### 阶段 A：飞书自定义机器人 + 反馈链接

目标：最快跑通“推送 + 反馈入库”。

状态：已完成初版。

流程：

```text
Python 后端生成推荐
-> 飞书自定义机器人推送消息
-> 每本书附带反馈链接
-> 用户点击链接
-> 后端 feedback endpoint 校验 secret
-> 展示原因选择页
-> 用户选择原因，可选补充自由文本
-> 写入 SQLite
-> 返回“已记录”
```

优点：

- 实现简单。
- 不需要先配置复杂事件回调。
- 能快速验证体验。

缺点：

- 点击反馈会打开浏览器。
- 不如卡片按钮自然。
- 原因选择需要额外页面或二级链接。

### 阶段 B：飞书应用机器人 + 交互式卡片

目标：获得更顺滑的按钮反馈体验。

流程：

```text
Python 后端生成推荐
-> 飞书应用机器人发送交互式卡片
-> 用户点击按钮
-> 飞书回调后端
-> 后端校验 token/signature
-> 写入 SQLite
-> 更新卡片或返回 toast
```

优点：

- 不需要打开浏览器。
- 支持按钮和二级原因选择。
- 支持卡片状态更新。
- 更适合长期使用。

缺点：

- 需要创建飞书开放平台应用。
- 需要公网 HTTPS 回调地址。
- 需要处理验签和事件订阅。

## 3. 初版消息形态

每日推送 3 条或 1 条聚合消息。

当前实现为 3 条推荐卡片 + 1 条“今日画像测试”汇总卡片。

推荐单条消息结构：

```text
今日推荐 1/3：《书名》

系统假设：
我推荐这本书，是因为我假设你现在真正缺的是 X。

测试画像维度：
- 知识缺口：系统设计
- 行动阶段：MVP 搭建期
- 阅读偏好：偏实战

推荐理由：
...

可能不适合：
...

建议读法：
...

反馈：
[喜欢] [一般] [不感兴趣] [已读] [想深入]
```

如果使用反馈链接，按钮可以先变成链接：

```text
喜欢：https://domain/fb?id=123&type=like&token=...
一般：https://domain/fb?id=123&type=neutral&token=...
不感兴趣：https://domain/fb?id=123&type=not_interested&token=...
已读：https://domain/fb?id=123&type=already_read&token=...
想深入：https://domain/fb?id=123&type=go_deeper&token=...
```

## 4. 必要配置

初版自定义机器人：

```env
CHANNEL=lark
LARK_WEBHOOK_URL=
PUBLIC_BASE_URL=https://your-domain.example
FEEDBACK_SECRET=
```

进阶应用机器人：

```env
LARK_APP_ID=
LARK_APP_SECRET=
LARK_VERIFICATION_TOKEN=
LARK_ENCRYPT_KEY=
```

## 5. 后端接口建议

当前初版反馈接口：

```text
GET /feedback?recommendation_id={recommendation_id}&feedback_type={feedback_type}&token={signature}
```

如果未携带 `reason_code`，服务端返回原因选择页；选择原因后访问带 `reason_code` 的签名链接并写入 `feedback_events`。

自由文本补充接口：

```text
POST /feedback/free-text
feedback_id={feedback_id}&token={signature}&free_text={text}
```

服务端必须校验：

- `recommendation_id` 是否存在。
- `feedback_type` 是否为枚举值。
- `reason_code` 是否属于该反馈类型允许的原因枚举。
- token/signature 是否有效。
- 是否重复反馈：当前尚未强制幂等，7 天试运行后再决定是否以 `recommendation_id + feedback_type + reason_code` 或用户身份做去重。

## 6. 数据库改动

建议在飞书初版同步补充：

```text
recommendations.system_hypothesis
recommendations.profile_dimensions
feedback_events.reason_code
feedback_events.free_text
```

以上字段已落地。

仍未落地但后续可补：

```text
feedback_events.channel
feedback_events.raw_payload_json
feedback_events.user_agent
feedback_events.ip_hash
```

后续飞书应用机器人可以补：

```text
recommendations.card_id
recommendations.card_message_id
feedback_events.lark_event_id
```

## 7. 安全要求

初版反馈链接不要裸奔。

最低要求：

- 每个反馈链接带签名。
- 签名使用 `FEEDBACK_SECRET`。
- 只允许有限反馈类型。
- 反馈接口记录日志。
- `.env` 不提交 Git。

正式飞书应用机器人：

- 校验飞书回调 token/signature。
- 使用 HTTPS。
- 不把 app secret 打进日志。
- 回调失败要可重试。

## 8. 与 Hermes / OpenClaw 的关系

飞书只负责交互入口，不负责用户建模。

职责边界：

```text
飞书：触达和反馈
Python：接收事件、写库、编排流程
SQLite：保存事实
Hermes：解释事实，生成长期记忆和复盘
OpenClaw：后续统一 Gateway 和 Skill 执行
```

因此第一阶段先接飞书不会破坏后续 Hermes/OpenClaw 架构。飞书只是当前最合适的 channel。
