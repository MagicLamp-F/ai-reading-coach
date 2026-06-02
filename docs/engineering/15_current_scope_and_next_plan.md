# 当前已有能力与待做方案总览

更新时间：2026-05-31

## 一句话判断

项目已经不是“单纯推荐 3 本书”的脚本，而是进入了“飞书入口 + SQLite 事实层 + Hermes 智能路由 + 快速读完包 + 初步来源采集”的基础平台阶段。

现在真正的短板不是 Hermes 是否能接模型，也不是 Feishu 是否能推送，而是：

```text
书源材料还不够深
-> 快速读完包只能基于推荐上下文、Hermes 模型知识和少量公开页面摘录生成
-> 还不能稳定达到“10 分钟像粗读完整本书”的效果
```

## 已有能力

### 1. 每日推荐闭环

已有：

- `run-daily` 每次生成 3 本书。
- 推荐写入 SQLite。
- 推荐卡片发送到飞书。
- 每条推荐包含书名、作者、主题、推荐理由、收益、风险、建议读法。
- 推荐已升级为假设驱动：包含 `system_hypothesis` 和 `profile_dimensions`。
- 搜索或模型失败时有 fallback，不会直接中断 daily run。
- source-aware candidate ranking v1 已接入：可先生成候选书，逐本检查来源质量，再选择最终推荐。

当前位置：

```text
可用；开启严格来源模式后，系统会宁可少发，也不会把来源不足的候选伪装成高质量推荐。
```

### 2. 飞书交互与反馈

已有：

- 飞书自定义机器人推送。
- 每本书有反馈入口：喜欢、一般、不感兴趣、已读、想深入。
- 反馈链接支持原因选择。
- 支持自由文本补充。
- 反馈事件写入 `feedback_events`。
- 后续 daily run 会处理未回写反馈并更新画像。

当前位置：

```text
个人使用可用；还不是完整飞书应用机器人。
```

待验证：

- 真实连续 7 天反馈后，原因选项是否够用。
- 是否需要反馈去重、用户身份识别和卡片状态更新。

### 3. SQLite 事实层

已有表包括：

- `profile_items`
- `books`
- `recommendations`
- `feedback_events`
- `run_logs`
- `cost_logs`
- `reflections`
- `artifacts`
- `reading_packs`
- `book_sources`
- `reading_pack_sources`

当前位置：

```text
已具备后续业务页面的数据基础。
```

原则：

- SQLite 存事实。
- Hermes/模型只生成解释或候选内容。
- 业务代码负责入库、发送、回滚和降级。

### 4. Hermes 接入

已有：

- `hermes-agent==0.14.0` 安装在 `/home/ubuntu/projects/hermes-agent`。
- Hermes CLI 可用。
- 外部 wrapper：`/home/ubuntu/projects/hermes-agent/bin/reflect-json`。
- 主项目通过 adapter 调用 wrapper。
- 已有路线：
  - `reflection.generate`
  - `reading.recommend.intent`
  - `reading.recommend.generate`
  - `reading.fast_read_pack`
- 已验证 Hermes 能真实调用模型。
- 已验证 daily 推荐和 reading pack 都可走 Hermes。

当前位置：

```text
Hermes 已可作为智能生成层使用；ai-reading-coach 仍是业务编排层。
```

关键边界：

- Hermes 不直接写 SQLite。
- Hermes 不直接发飞书。
- Hermes 不直接修改 `memory/USER.md` / `memory/MEMORY.md`。
- Hermes 失败时，主项目负责 fallback。

### 5. Reflection 与长期记忆

已有：

- `generate-reflection` 可生成 reflection draft。
- 默认保留人工 `approve-reflection` / `apply-reflection`。
- 可开启自动 apply：

```env
HERMES_REFLECTION_AUTO_APPLY=true
DAILY_REFLECTION_ENABLED=true
DAILY_REFLECTION_DAYS=1
```

- 自动 apply 会写 `memory/change_logs`。

当前位置：

```text
能力已接通，但需要真实多天数据验证反思质量。
```

### 6. 快速读完包

已有：

- `run-daily` 默认为每条推荐生成 reading pack。
- reading pack 结构化内容写入 `reading_packs.content_json`。
- 长 Markdown 写入：

```text
library/YYYY/MM/YYYY-MM-DD__book-title/reading-pack.md
```

- 飞书卡片展示快速读完包预览：
  - 一句话主张
  - 10 分钟路径
  - 核心概念
  - 核心脉络
  - 章节/结构地图
  - 例子/案例
  - 局限

当前位置：

```text
链路可用，但内容深度还不稳定。
```

原因：

- 现在没有完整书源。
- 当前来源主要是推荐上下文、Hermes 模型知识和公开 `source_url` 摘录。
- 对于只有营销页或 HTTP 403 的书，内容会变浅。

### 7. 轻量来源采集

已有：

- `BookSourceCollector` 会抓取推荐记录里的公开 `source_url`。
- 清洗 HTML，去掉 script/style。
- 摘录写入 `book_sources`。
- reading pack 生成时会把来源摘录传给 Hermes。
- `reading_pack_sources` 记录阅读包使用了哪些来源。
- 抓取失败不影响日推。

当前位置：

```text
这是 source-grounded fast read 的第一版，不是完整书源系统。
```

已知限制：

- 只抓一个推荐 URL。
- 不主动搜索更多来源。
- 不抓内网页面。
- 不抓付费/受保护全文。
- 不做浏览器自动化。
- 不处理复杂反爬。

## 已验证结果

自动化测试：

```text
python3 -m unittest discover -q
Ran 70 tests ... OK
```

真实 Hermes daily 测试：

```text
run_id=29
status=success
recommendations_count=3
reading_packs_count=3
reading_pack_status=generated
generator_provider=hermes-agent
api_calls=0
reading_pack_source_links=2
```

说明：

- daily 推荐走 Hermes。
- reading pack 走 Hermes。
- 项目自己的 OpenAI client 未参与这次 daily 生成。
- 3 本书里 2 本成功关联公开来源摘录。
- 1 本来源 URL 返回 HTTP 403，但没有影响 daily run。

## 还没做的事

### P0：部署与试运行稳定性

待做：

- 确认 `.env` 在服务器上持久配置。
- 确认 feedback server 可公网访问。
- 启用或验证 systemd daily/weekly timer。
- 跑 7 天真实 daily。
- 检查备份和日志。

为什么重要：

```text
没有连续数据，就无法判断推荐、反馈、reflection 和 reading pack 是否真的有效。
```

### P0：来源收集 v2

待做：

- 对每本书收集多个合法公开来源：
  - 官方页
  - 出版社页
  - 作者页
  - 目录页
  - 样章页
  - 作者访谈
  - 公开视频文字稿
  - 高质量公开书评
- 为来源做类型、可信度和新鲜度评分。
- 给 reading pack 标注哪些观点来自哪些来源。
- 把来源采集失败原因写入 DB，方便页面复盘。

为什么重要：

```text
快速读完包的质量上限主要取决于来源材料，而不是 Hermes 本身。
```

## 书源获取方案

书源不要只理解成“整本书全文”。对这个项目来说，书源应分成四层：

```text
L1 元数据：书名、作者、ISBN、出版社、简介、分类、封面
L2 结构材料：目录、章节标题、样章、官方介绍、作者访谈
L3 内容材料：合法全文、用户上传文件、开放版权电子书、开放获取 PDF
L4 二次材料：书评、访谈、课程笔记、公开视频文字稿、播客文字稿
```

当前最应该先做 L1 + L2 + L4，不要一开始就追求所有书都有全文。

### 方案 A：公开 API 和开放目录

适合做自动化基础数据和合法公开来源。

优先级：

1. Open Library：用于查书籍元数据、作者、ISBN、可读版本线索。
2. Google Books API：用于补简介、目录线索、预览状态和外部链接。
3. Internet Archive / Open Library readable links：用于找可公开阅读或借阅的版本线索。
4. Project Gutenberg：适合公共领域经典书全文。
5. Standard Ebooks / GITenberg：适合质量更好的公共领域 EPUB。
6. DOAB / OAPEN：适合开放获取学术书。

注意：

- API 返回“可搜索/可预览”不等于可以下载全文。
- 对版权书，只保存元数据、摘录和链接，不把受保护全文长期入库。
- 对公共领域或明确开放许可书，可以保存全文或解析后的章节。

### 方案 B：网页来源采集

适合大多数现代商业书。

可采集：

- 官方书页。
- 出版社页。
- 作者个人网站。
- 目录页。
- 样章页。
- 作者访谈。
- 公开视频/播客文字稿。
- 高质量公开书评。

当前 `BookSourceCollector` 只做了最小版本：

```text
recommendation.source_url
-> HTTP GET
-> HTML 清洗
-> 保存 excerpt 到 book_sources
```

当前已推进到 Tavily source grounding v1.1：

```text
recommendation.title + recommendation.author
-> Tavily advanced search
-> 优先使用 Tavily raw_content
-> raw_content 不存在时才抓取公开结果页
-> 清洗正文
-> 简单分类 source_type
-> 计算 source_quality
-> reading pack / 飞书显式展示来源质量
```

Tavily key 默认读取：

```text
TAVILY_API_KEY
或
TAVILY_API_KEY_FILE=/home/ubuntu/.config/tavily/api_key
```

默认消耗策略：

```text
SOURCE_SEARCH_MAX_RESULTS=3
SOURCE_SEARCH_DEPTH=advanced
SOURCE_SEARCH_QUERIES_PER_BOOK=3
SOURCE_SEARCH_INCLUDE_RAW_CONTENT=true
每本推荐书约 3 次 Tavily search
每天 3 本约 9 次 source search
SOURCE_FETCH_TIMEOUT_SECONDS=6
SOURCE_FETCH_RETRIES=0
```

如果 daily 推荐阶段本身也使用 Tavily 搜主题，每天可能额外增加 2-3 次 basic search。

下一版应该继续做：

```text
book title + author
-> search API 获取候选来源
-> source scorer 判断来源类型和可信度
-> fetch + clean + excerpt
-> source dedupe
-> book_sources 入库
```

### 方案 C：用户本地文件

这是最可靠的深度来源，尤其适合你已经购买或自己拥有的材料。

建议支持格式：

- `.epub`
- `.pdf`
- `.txt`
- `.md`
- `.html`
- `.docx`

推荐做法：

```text
用户把文件放到 server 本地 inbox
-> import-book-source CLI
-> 解析章节/目录/文本
-> 保存为 book_sources
-> 生成 reading pack
```

建议目录：

```text
data/source_inbox/
data/source_archive/
```

不要直接把原始文件提交到 Git。Git 只保存代码和文档，原始书源留在服务器数据目录或对象存储。

本地文件方案的优势：

- 内容最深。
- 不受网页反爬影响。
- 能做章节级 reading pack。
- 可以生成真正接近“粗读完整本书”的导读。

风险：

- 版权边界要自己负责。
- 不应把受版权保护的全文发给外部不可信服务或公开展示。
- reading pack 应做变换和总结，不复刻大段原文。

### 方案 D：OpenClaw 后期增强

OpenClaw 的作用不是“提供书源”，而是“执行更复杂的找书源流程”。

适合 OpenClaw 的场景：

- 某些网页必须浏览器渲染。
- 需要多步骤搜索、打开、筛选、抽取。
- 需要把来源采集过程沉淀成可审计 skill。
- 需要人工可读的采集轨迹和失败原因。

不适合现在立刻上 OpenClaw 的原因：

- 当前 HTTP/search/source DB 还没做完。
- OpenClaw 增加工具权限和安全边界复杂度。
- 它不会绕过版权问题。
- 它不会天然拥有合法全文。

推荐顺序：

```text
1. 做 source collector v2
2. 做本地文件导入
3. 做 reading pack 质量评分
4. 只有当普通 HTTP/search 不够时，再接 OpenClaw
```

### 推荐技术组件

网页抽取：

- `trafilatura`
- `readability-lxml`
- `beautifulsoup4`

EPUB：

- `ebooklib`
- Calibre 的 `ebook-convert` / `ebook-meta`

PDF：

- `pypdf`
- `PyMuPDF`

DOCX：

- `python-docx`

元数据：

- Open Library API
- Google Books API
- ISBN 查询源
- Crossref / OpenAlex，主要用于学术书和论文关联

### 本项目建议落地顺序

第一阶段：

- 给 `book_sources` 增加 `source_quality`、`source_origin`、`license_hint`、`failure_reason`。
- 接入 Open Library 和 Google Books metadata。
- 对每本书自动找 3-5 条公开来源。

第二阶段：

- 增加 `import-book-source --file <path> --book-id <id>`。
- 支持本地 EPUB/PDF/TXT/MD。
- 把章节结构和文本片段写入 `book_sources`。

第三阶段：

- 给 reading pack 增加来源覆盖率和章节置信度。
- 如果来源不足，飞书里明确提示“这本书目前缺目录/缺案例/缺章节文本”。

第四阶段：

- 再评估是否接 OpenClaw 做复杂网页和 skill 化采集。

### P1：快速读完包质量升级

待做：

- 把当前 pack 从“结构化总结”升级为“粗读完整本书体验”。
- 目标结构：
  - 这本书要解决的问题
  - 全书路线图
  - 每一部分/章节大概讲什么
  - 核心概念
  - 关键例子
  - 作者论证链
  - 反对意见和局限
  - 对用户当前目标的使用方式
  - 10 分钟/30 分钟/2 小时三种阅读路径
  - 自测题
- 对 pack 增加质量字段：
  - source_coverage
  - chapter_confidence
  - example_density
  - user_fit_score

### P1：书库/业务页面

待做：

- 做一个本地或公网可访问的 reading pack 页面。
- 飞书卡片里不要只显示服务器本地路径。
- 页面可以查看：
  - 今日推荐
  - 历史推荐
  - reading pack 详情
  - 来源列表
  - 用户反馈
  - 画像变化

为什么重要：

```text
飞书适合推送，不适合承载长阅读包和复盘。
```

### P1：反馈驱动的内容改进

待做：

- 增加 reading pack 反馈：
  - 太浅
  - 没有书的内容
  - 缺案例
  - 缺章节结构
  - 推荐不准
  - 想要更实用
- 根据反馈决定下一次补什么来源。

### P2：飞书应用机器人

待做：

- 从自定义机器人升级到飞书应用机器人。
- 支持卡片按钮回调。
- 支持点击后卡片状态更新。
- 减少打开浏览器页面的步骤。

### P2：OpenClaw 接入

OpenClaw 暂时不是当前 blocker。

它后期有用的地方：

- 复杂网页需要浏览器才能看到内容。
- 一本书需要多步骤搜索、打开、判断、抽取、去重。
- 需要把“找资料”做成可审计 skill。
- 需要对来源采集过程做工具编排。

它不解决的问题：

- 不会凭空拥有版权书全文。
- 不会自动保证来源合法。
- 不会天然比普通 HTTP/search 更安全。
- 不应该直接给它系统 shell、SSH、`.env` 或任意文件读写权限。

建议引入方式：

```text
先不用 OpenClaw
-> 做 source collector v2
-> 明确需要浏览器/复杂工具编排后
-> 独立 /home/ubuntu/projects/openclaw
-> 白名单 skill
-> 只允许输出 source JSON
-> ai-reading-coach 再审核入库
```

### P2：Skill 化

待做：

- 把推荐规则、快速读完包规则、来源评分规则沉淀成 skill 文档。
- Hermes 可以建议修改 skill，但不自动上线。
- 每次 skill 改动都要有计划文档、进程文档和验收记录。

### P3：30 天用户模型报告

待做：

- 汇总 30 天推荐、反馈、reading pack 使用、reflection。
- 输出用户兴趣变化、知识缺口、反感模式、行动阶段、下月探索建议。

## 推荐下一阶段路线

### 第一步：跑稳当前链路

目标：

```text
确认 daily -> Hermes -> reading pack -> Feishu -> feedback -> SQLite 这条链连续可用。
```

验收：

- 连续 7 天 daily 成功。
- 每天都有 run log。
- 每天至少生成 3 个 recommendation。
- reading pack 不阻断日推。
- source-aware strict mode 不把 `source_limited` 候选补成正常推荐。
- 反馈能写入并被下一次处理。

### 第二步：做来源收集 v2

目标：

```text
让每本书至少有 3-5 条合法公开来源。
```

优先做：

- 搜索 API 接入来源候选。
- 来源去重。
- 来源类型识别。
- 来源可信度评分。
- 把失败原因入库。

### 第三步：升级 reading pack 质量

目标：

```text
让你在 10-30 分钟内真的知道这本书大概讲了什么，而不是只知道为什么推荐。
```

核心指标：

- 有章节/结构地图。
- 有具体例子。
- 有核心论证链。
- 有局限和反对意见。
- 明确哪些内容是来源支持，哪些是模型推断。

### 第四步：做业务页面

目标：

```text
把飞书从“阅读入口”降级为“提醒入口”，把完整阅读和复盘放到页面里。
```

## 当前结论

当前已经完成的是基础架构和第一条可用闭环：

```text
Hermes 可生成
Feishu 可触达
SQLite 可沉淀
reading pack 可保存
来源摘录可入库
失败可降级
测试可通过
```

接下来真正决定产品效果的是：

```text
来源收集质量
+ reading pack 结构质量
+ 连续反馈后的画像修正
+ 一个能查看和复盘的业务页面
```

OpenClaw 后期有价值，但应该作为“复杂来源采集和工具编排增强层”，不是现在的第一优先级。
