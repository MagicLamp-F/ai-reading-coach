# Hermes 记忆 Agent 与阅读中台设计

## 1. 本文背景

本文整理一次关于 `ai-reading-coach`、Hermes、OpenClaw、飞书和长期个人画像的架构讨论，目的是把当前零散判断沉淀成后续实现依据。

本项目的目标不是单纯做一个每天推书的机器人，而是通过“书籍推荐、快速读完、反馈、画像更新、复盘”形成一个长期个人阅读与认知建模系统。

当前用户的核心诉求是：

- 利用 Hermes 逐步丰富个人画像，让推荐的书更贴近真实想法。
- 不只是拿到书名，而是用系统帮助快速理解、吸收一本书。
- `ai-reading-coach` 作为应用层项目，负责定时推荐、飞书消息、反馈收集、推荐记录和后续业务页面。
- 后续可能接入 OpenClaw，用于获取更多图书候选、执行更复杂的工具调用或多渠道 gateway。
- 每天的书籍记录、总结、精炼文本需要沉淀下来，后续可以像书库一样按时间查看阅读历程、总结和画像变化。

## 2. 当前 Hermes 集成状态与边界

当前云服务器侧状态：

- `/home/ubuntu/projects/hermes-agent` 已存在。
- `hermes-agent==0.14.0` 已安装在 `/home/ubuntu/projects/hermes-agent/.venv`。
- CLI 可用：`hermes`、`hermes-agent`、`hermes-acp`。
- 主项目测试已通过，当前记录为 55 个测试 OK。
- 已补 `/home/ubuntu/projects/hermes-agent/bin/reflect-json`，作为 `ai-reading-coach` 调用 Hermes 的 wrapper。
- wrapper 能看到 API key、model、base_url 已设置，但不能打印密钥。
- Hermes 已通过交互式模型配置完成 provider/model/API 配置。
- `reflect-json --debug-smoke` 已能通过 Hermes 返回可见模型输出。
- `generate-reflection --days 7 --no-lark` 已通过 hermes-agent provider 生成 `draft` reflection。

因此当前结论是：

```text
Hermes 已安装。
CLI 已可运行。
ai-reading-coach 的调用入口已准备。
Hermes -> 模型推理 -> JSON 返回 已验证成功。
```

当前可以说 `hermes-agent` 的 reflection 基础链路已经接通；失败时仍应 fallback 到当前 custom reflection。

建议配置仍是：

```bash
HERMES_REFLECTION_PROVIDER=hermes-agent
HERMES_AGENT_COMMAND=/home/ubuntu/projects/hermes-agent/bin/reflect-json
```

当前 smoke test 已证明 Hermes 能完成真实模型调用并返回业务可消费的 JSON。下一步重点是连续运行和质量验证。

## 3. Hermes 是什么，不是什么

Hermes 可以理解为一个带会话、工具、技能、记忆和多入口能力的 Agent runtime。它可以通过 CLI 直接使用，也支持 ACP、MCP、gateway、cron 等能力。

它适合承担：

- 长期记忆和用户画像整理。
- 会话总结和跨会话回忆。
- 根据用户画像做推荐判断。
- 分析反馈并提炼偏好、盲点和认知模式。
- 生成飞书消息文案、阅读导读、复盘问题。
- 后期作为主对话 Agent，调用外部工具。

它不应该直接替代：

- SQLite 或其他事实数据库。
- 定时任务调度。
- 飞书消息可靠投递。
- 推荐记录和反馈记录的 source of truth。
- 业务页面的数据查询和展示。
- 幂等、重试、审计、日志脱敏、权限控制。

一句话：

```text
Hermes 适合做智能大脑和长期语义记忆。
ai-reading-coach 仍应保留为业务中枢和事实系统。
```

## 4. 为什么需要 wrapper，而不是直接用 Hermes

Hermes 的 CLI、ACP、MCP 都是可用入口，但它们不一定等于 `ai-reading-coach` 当前需要的接口。

`ai-reading-coach` 当前更适合消费一种简单命令协议：

```text
执行一个命令
往 stdin 写 JSON
从 stdout 读 JSON
根据 exit code 判断成功或 fallback
```

而 Hermes 的原生入口可能是：

```bash
hermes
hermes chat -q "..."
hermes chat --quiet -q "..."
hermes-acp
hermes mcp serve
```

这些入口的用途不同：

| 入口 | 适合场景 | 对 ai-reading-coach 的问题 |
| --- | --- | --- |
| `hermes` | 人类交互式终端会话 | 不是稳定机器协议 |
| `hermes chat -q` | 一次性 prompt 调用 | 输出可能是自然语言，不是严格 JSON |
| `hermes chat --quiet -q` | 脚本式调用 | 仍需校验和包装输出 |
| `hermes-acp` | ACP stdio JSON-RPC server | 需要实现 ACP client，复杂度更高 |
| `hermes mcp serve` | 把 Hermes 暴露给其他 agent 或工具生态 | MCP 不是当前业务所需的简单 reflection provider 协议 |

因此 wrapper 的职责不是“重新开发 Hermes”，而是协议适配：

```text
ai-reading-coach 的 JSON 命令协议
  -> reflect-json
      -> 安全调用 Hermes
      -> 捕获 stdout/stderr/exit code
      -> 校验和包装输出
  -> 返回 ai-reading-coach 需要的 JSON
```

wrapper 还需要负责：

- 不打印或泄露 API key。
- 设置安全 cwd，避免 Hermes 在主项目目录内以工具模式误读写文件。
- 禁止或限制 yolo/工具模式。
- 超时控制。
- 输出 schema 校验。
- 失败时明确 stderr 和非 0 exit code，以便 fallback。

## 5. MCP、ACP 与当前项目的关系

当前不建议让 `ai-reading-coach` 直接复杂接入 MCP 或 ACP。

MCP 更适合：

```text
Hermes 作为主 Agent
  -> 调用 ai-reading-coach、OpenClaw、书库、笔记、飞书等工具
```

也就是说，如果未来用户主要和 Hermes 对话，Hermes 需要主动查询推荐历史、写反馈、拉书、发消息，那么可以把 `ai-reading-coach` 或 OpenClaw 暴露为 MCP 工具。

ACP 更适合：

```text
编辑器或客户端
  -> 通过 JSON-RPC 与 Hermes 维持会话
```

它比一次性命令调用更强，但也更复杂。

当前阶段最务实路线是：

```text
ai-reading-coach -> reflect-json -> Hermes
```

后期再演进为：

```text
Hermes -> MCP -> ai-reading-coach / OpenClaw / 飞书 / 书库
```

## 6. Hermes 是否适合做主 Agent

Hermes 可以做主 Agent，但不建议它做主后端。

合理分工：

| 组件 | 职责 |
| --- | --- |
| Hermes | 智能大脑、记忆、画像、推荐判断、反馈分析、对话式解释 |
| ai-reading-coach | 业务流程、定时任务、推荐记录、反馈记录、飞书投递、总览页面 |
| OpenClaw | 外部图书候选、搜索、工具执行、多渠道 gateway 的后续候选 |
| SQLite/数据库 | 事实层、推荐历史、反馈、画像证据、状态 |
| 文件系统 | 长文本阅读包、总结、导读、复盘、版本化产物 |
| 飞书 | 第一交互通道，负责消息触达和轻量反馈 |

推荐架构：

```text
定时任务
  -> ai-reading-coach 生成推荐任务
  -> OpenClaw / 书库 / 历史记录 获取候选书
  -> Hermes 根据画像筛选、排序、解释
  -> ai-reading-coach 记录推荐结果
  -> ai-reading-coach 发送飞书消息
  -> 用户在飞书反馈
  -> ai-reading-coach 接收反馈
  -> Hermes 分析反馈，更新画像/记忆
```

这能避免系统变成不可追踪的 Agent 黑箱。

## 7. 统一 Agent 接口的方向

后续可以把 `reflect-json` 扩展成更通用的 Hermes 调用入口，但第一版不应过度设计。

推荐的结构化请求：

```json
{
  "route": "reading_coach.reflection",
  "user_id": "default",
  "domain": "reading",
  "memory_scope": ["user_profile", "reading_profile"],
  "tool_policy": "none",
  "output_schema": "reflection_v1",
  "input": {
    "book": "...",
    "session_notes": "...",
    "question": "..."
  }
}
```

不要只靠 prompt 里的文本标记做路由。应该把 route、domain、memory_scope、tool_policy、output_schema 放进结构化协议里。

建议长期 route：

```text
reading.recommend.intent       根据记忆生成本次检索意图
reading.recommend.rank         对候选书排序和解释
reading.fast_read_pack         生成快速读完包
reading.message.compose        生成飞书推荐消息
reading.feedback.analyze       分析用户反馈
reading.profile.update         更新阅读画像
reading.reflection.generate    生成阶段性反思
```

## 8. 记忆与画像分域

Hermes 的长期记忆不应混成一个大文本。需要分领域和来源。

建议 memory scope：

| Scope | 内容 | 说明 |
| --- | --- | --- |
| `user_profile` | 稳定个人偏好、表达习惯、长期目标 | 跨业务共享，但需谨慎写入 |
| `reading_profile` | 阅读口味、主题偏好、难度偏好、反感模式 | 本项目核心画像 |
| `thinking_profile` | 思维方式、判断习惯、认知盲点、偏好的解释结构 | 用于自我剖析 |
| `book_history` | 已推荐、已读、跳过、想深读 | 应由数据库事实记录支撑 |
| `session_memory` | 当前会话短期上下文 | 不一定进入长期记忆 |
| `project_profile` | 代码项目、工程习惯、技术栈约定 | 不应污染阅读画像 |
| `private_sensitive` | 敏感信息 | 默认不自动写入长期记忆 |

画像条目必须区分：

```text
事实：用户明确表达过
偏好：多次行为体现出来
推断：模型根据证据推理出来
假设：需要后续验证
```

每条画像建议保留：

```text
category
content
confidence
source
evidence_ids
created_at
last_seen_at
user_confirmed
scope
```

单次反馈不应直接覆盖长期画像。Hermes 可以生成画像增量，但数据库应保留证据链，允许后续重算。

## 9. OpenClaw 拉书与 Hermes 筛选顺序

推荐采用混合流程，而不是二选一。

正确顺序：

```text
Hermes 读取用户画像
  -> 生成本次检索意图
  -> OpenClaw 拉取候选书
  -> Hermes 基于画像粗筛和排序
  -> OpenClaw / 合法来源拉取深度材料
  -> Hermes 生成快速读完包
  -> ai-reading-coach 发送飞书
  -> 用户反馈
  -> Hermes 更新画像
```

不要一开始让 Hermes 只凭记忆直接推荐书，这会造成过滤泡泡和推荐越来越窄。

也不要让 OpenClaw 随机拉大量候选后全部丢给 Hermes，这会增加噪音和成本。

Hermes 在检索前负责生成搜索策略：

```text
最近关注什么
长期偏好是什么
当前应补什么能力
应避免什么类型
需要理论、案例、实操还是轻量读物
需要贴合当前画像还是探索边界
```

OpenClaw 负责多方向获取候选：

```text
精准匹配
相邻主题
反向观点
经典书
新书
用户未意识到但相关的书
```

Hermes 负责筛选：

```text
相关性
新鲜度
与历史推荐是否重复
当前阅读收益
难度匹配
时间匹配
是否符合用户表达偏好
是否能帮助用户自我理解
```

## 10. “快速读完一本书”的产品定义

用户不希望只是拿到书名后自己去看，而是希望有简便方法快速吸收一本书。

因此系统产物不应只是“推荐理由”，而应包含“快速读完包”。

快速读完包建议包括：

```text
为什么推荐给你
这本书一句话讲什么
这本书解决什么问题
作者的核心论点
核心概念和模型
章节地图
必读章节
可跳过章节
10 分钟版
30 分钟版
2 小时阅读路线
关键卡片
反对意见和局限
和你当前目标的关系
和你已有认知的冲突点
读完后应该问自己的 5 个问题
```

版权边界：

- 公版书或用户自有材料，可以做更深的章节级处理。
- 受版权保护的新书，不应抓取或复刻完整正文。
- 可基于目录、简介、合法样章、公开书评、作者访谈、用户提供摘录和已有笔记生成导读。

目标不是盗版复刻一本书，而是帮助用户判断是否值得读、怎么读、先读什么、从中吸收什么。

当前 MVP 已先落地为自动 `reading.fast_read_pack` 链路：

```text
recommendation_id
  -> ai-reading-coach 读取推荐、书籍、画像和 Hermes memory 上下文
  -> 生成 fast_read_pack_v1
  -> 写入 reading_packs
  -> 写入 artifacts
  -> 保存 library/YYYY/MM/YYYY-MM-DD__book-title/reading-pack.md
  -> 飞书推荐卡片展示快速读完预览
```

这一步暂时不要求 Hermes fast-read route 化。目的是先把“内容产物、可维护数据结构、自动触达”跑通，再决定是否加业务页面和 Hermes route adapter。

## 11. 飞书闭环

飞书是第一交互通道，负责低摩擦触达和反馈。

每日消息建议包含：

```text
今日推荐主题
推荐书 1-3 本
每本书的推荐假设
为什么适合你
可能不适合你的原因
快速读完入口
反馈按钮
```

反馈按钮建议：

```text
喜欢
一般
不感兴趣
已读
想深入
```

关键反馈后追加原因：

```text
主题正好
太浅
太难
我已经懂了
现在不是时候
推荐理由没说服我
营销感太强
需要更实操
```

飞书消息发送由 `ai-reading-coach` 负责，Hermes 只负责生成内容和解释，不直接控制投递状态。

## 12. 数据库存储与文件存储

每天的书籍记录、总结、精炼文本应同时沉淀到数据库和文件。

数据库负责结构化事实：

```text
books
  书籍基础信息：书名、作者、ISBN、主题、来源、封面、简介

recommendations
  每次推荐记录：日期、推荐原因、分数、状态、是否采纳

reading_sessions
  每天/每次阅读记录：阅读目标、耗时、状态、反馈

summaries
  每本书/每次阅读的摘要版本：10 分钟版、30 分钟版、2 小时版

feedback
  用户反馈：喜欢/不喜欢、太浅/太深、命中点、反感点

profile_insights
  从反馈里提炼出的画像增量：偏好、盲点、兴趣变化

artifacts
  长文本文件路径、hash、版本、生成时间、来源
```

文件负责长文本和可读产物：

```text
library/
  2026/
    05/
      2026-05-29__book-title/
        reading-pack.md
        summary-10min.md
        summary-30min.md
        summary-2h.md
        reflection.md
        profile-insights.md
        sources.json
```

原则：

```text
数据库负责查找、排序、状态、关联、页面列表。
文件负责长文本、导读、总结、复盘、可版本化阅读。
数据库保存文件路径和元数据。
```

后期业务页面可以基于这些数据做：

```text
时间线
书库
推荐记录
阅读总结
快速读完包
个人画像变化
主题地图
年度阅读复盘
```

## 13. 业务总览页面方向

后期业务端页面不应只是后台表格，而应支持用户回看自己的阅读历程。

建议页面：

```text
每日阅读时间线
书籍详情页
推荐记录页
反馈记录页
快速读完包页面
画像变化页
主题趋势页
复盘页
来源与证据页
```

关键查询：

```text
某天推荐了什么，为什么推荐
我反馈了什么
系统从反馈里学到了什么
某个主题出现了多少次
哪些书被跳过，原因是什么
哪些推荐被认为命中
我的阅读偏好如何变化
哪些画像条目有证据支撑
```

## 14. 推荐执行链路

每日任务完整链路：

```text
1. Scheduler 触发每日推荐任务
2. ai-reading-coach 读取近期历史、画像摘要、反馈记录
3. Hermes 生成本次检索意图
4. OpenClaw 按多个方向拉候选书
5. ai-reading-coach 去重、过滤已读/已推荐
6. Hermes 对候选书评分、排序、解释
7. 对 Top N 书籍拉取更深材料
8. Hermes 生成快速读完包和飞书文案
9. ai-reading-coach 写入数据库
10. ai-reading-coach 保存 Markdown 文件
11. ai-reading-coach 发送飞书消息
12. 用户反馈
13. ai-reading-coach 写入反馈事实
14. Hermes 分析反馈并生成画像增量
15. 数据库记录画像增量和证据
16. 周期性生成用户画像复盘
```

## 15. 当前实施优先级

建议按以下顺序推进：

```text
1. 先把 reflect-json smoke test 打通，确认 Hermes 可真实推理并返回合法 JSON。
2. 保持 ai-reading-coach 作为业务编排层，不把 Hermes 放进主项目。
3. 增加 route 化协议，但第一版只实现 reading_coach.reflection。
4. 增加 reading.recommend.rank 和 reading.fast_read_pack 的 schema 草案。
5. 数据库保留推荐记录、反馈、画像证据、文件 artifact 元数据。
6. 文件系统保存每日 reading-pack 和 summary。
7. 飞书继续作为第一交互入口。
8. OpenClaw 先作为候选书来源接入，不一开始承担完整主 Agent。
9. 后期需要 Hermes 主动调用工具时，再考虑 MCP。
10. 后期需要对话式主入口时，再考虑 Hermes 作为用户直接交互入口。
```

## 16. 非目标和风险

当前不做：

- 重新安装 Hermes。
- 把 Hermes 复制进 `ai-reading-coach`。
- 修改 SSH、防火墙、系统用户、OpenClaw 或 Docker。
- 让 Hermes 以 yolo/工具模式直接读写主项目。
- 用 Agent 自然记忆替代数据库事实记录。
- 直接抓取受版权保护书籍全文来替代阅读。
- 一开始实现完整 MCP/ACP 客户端。
- 一开始做复杂商业化后台。

主要风险：

| 风险 | 应对 |
| --- | --- |
| Hermes 调用失败后静默 fallback | wrapper 必须记录脱敏错误、stdout/stderr 长度和 exit code |
| 输出不是 JSON | wrapper 做严格 schema 校验，不合格则失败 |
| 记忆污染 | 使用 domain、scope、evidence、confidence 隔离 |
| 推荐过滤泡泡 | OpenClaw 拉候选时保留探索型候选 |
| 画像过度推断 | 区分事实、偏好、推断、假设 |
| 长文本不可追溯 | 数据库存 artifact 路径、hash、来源 |
| 业务状态丢失 | SQLite/数据库作为 source of truth |
| 版权风险 | 只处理合法来源、公版书、用户自有材料和公开摘要 |

## 17. 最终一句话

```text
ai-reading-coach 是业务中枢，
Hermes 是长期记忆和智能判断层，
OpenClaw 是外部候选与工具来源，
飞书是第一交互通道，
数据库和文件系统共同沉淀个人阅读历程。

系统的目标不是每天推几本书，
而是通过推荐、快速读完、反馈和复盘，
长期形成一个可解释、可回看、可修正的个人阅读画像与认知历程。
```
