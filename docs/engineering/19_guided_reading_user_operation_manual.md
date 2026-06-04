# 渐进式导读伴读操作手册

日期：2026-06-03

## 入口

当前演示服务：

```text
http://127.0.0.1:8010
```

书源管理页：

```text
http://127.0.0.1:8010/guided-reading/sources?admin_token=aA5eUV3rUVJMaNIhvvjFL5qGtb-1mr1Pqr8aiHomcLA
```

阅读计划配置页：

```text
http://127.0.0.1:8010/guided-reading/plans?admin_token=aA5eUV3rUVJMaNIhvvjFL5qGtb-1mr1Pqr8aiHomcLA
```

正式部署后，把 `127.0.0.1:8010` 换成正式域名或正式服务端口。

## 支持的书源格式

当前支持：

- `.epub`
- `.md`
- `.txt`

限制：

- 单文件 10MB 以内。
- `.md` / `.txt` 需要 UTF-8 编码。
- EPUB 会按 OPF spine 顺序提取 XHTML/HTML 正文。
- 暂不支持 PDF、DOCX、MOBI、AZW3、扫描版 OCR。

## 推荐操作流程

### 1. 打开书源管理页

进入：

```text
/guided-reading/sources?admin_token=...
```

页面分为两块：

- 左侧：已导入书源列表。
- 右侧：上传书源表单。

### 2. 上传书源

在“上传书源”区域填写：

```text
书名
作者
文件
```

文件选择 `.epub`、`.md` 或 `.txt`。

然后点击：

```text
导入书源
```

导入成功后，系统会保存书源，并生成一条书源记录。

你会看到：

```text
书源已导入
查看书源 #id
```

### 3. 查看书源详情

点击“查看书源”，或在书源管理列表里点击书名。

书源详情页会显示：

```text
书名
原始文件名
格式
字数
内容预览
```

右侧会有“基于此书源创建计划”的表单。

### 4. 创建阅读计划

在书源详情页右侧设置：

```text
计划天数
每天分钟
模式
口吻
剧透策略
是否飞书推送每日导读
```

推荐第一组配置：

```text
计划天数：5
每天分钟：8
模式：渐进导读
口吻：短导读
剧透策略：不剧透
飞书推送：先不开
```

如果是小说或传记：

```text
计划天数：7
每天分钟：10
模式：追剧式
口吻：追剧式
剧透策略：不剧透
飞书推送：按需开启
```

点击：

```text
创建阅读计划
```

创建成功后，系统会显示：

```text
阅读计划已创建
打开第一天导读
```

### 5. 阅读第一天导读

点击：

```text
打开第一天导读
```

导读页包含：

```text
今日钩子
今天只抓一个问题
今日原文
白话拆解
关键点
现实连接
明天预告
反馈按钮
```

建议阅读顺序：

1. 先看“今日钩子”。
2. 再看“今天只抓一个问题”。
3. 然后读“今日原文”。
4. 如果读不进去，再看“白话拆解”。
5. 最后点一个反馈按钮。

### 6. 提交反馈

导读页反馈按钮包括：

```text
读完了
想继续
刚刚好
太长了
没兴趣
```

你也可以补一句原因。

反馈会写入 `reading_progress_events`，用于后续判断这本书是否适合继续、每天长度是否合适、口吻是否需要调整。

## 飞书推送

创建阅读计划时，如果勾选：

```text
飞书推送每日导读
```

系统会在到期推送时发送“今日导读”飞书卡片。

卡片包含：

```text
书名
Day 进度
预计阅读分钟
导读模式
是否不剧透
今日钩子
今天只抓一个问题
明天预告
打开导读按钮
```

手动触发飞书推送：

```bash
python3 -m app.cli send-guided-reading-pushes --limit 10
```

已提供 systemd 单元：

```text
deploy/systemd/ai-reading-coach-guided-reading.service
deploy/systemd/ai-reading-coach-guided-reading.timer
```

默认每天 08:30 触发。

## 页面说明

### 书源管理页

用途：

```text
上传书源
查看已导入书源
进入书源详情
```

列表字段：

```text
ID
书名
文件名
格式
字数
导入时间
```

### 书源详情页

用途：

```text
预览书源内容
基于书源创建阅读计划
删除书源
```

删除是软删除，记录会标记为 `deleted`，不会直接删除磁盘文件。

### 阅读计划配置页

用途：

```text
查看已有计划
直接粘贴文本创建计划
进入书源管理
```

如果已经上传了 EPUB，建议从“书源详情页”创建计划，而不是在这里粘贴文本。

### 每日导读页

用途：

```text
每天读一小段
看导读
看白话拆解
提交反馈
```

这是核心阅读页面。

## 命令行用法

从本地文件直接创建计划：

```bash
python3 -m app.cli create-guided-reading-plan \
  --source-file /path/to/book.epub \
  --title "书名" \
  --days 5 \
  --daily-minutes 8 \
  --mode guided \
  --tone short_video
```

开启飞书推送：

```bash
python3 -m app.cli create-guided-reading-plan \
  --source-file /path/to/book.epub \
  --title "书名" \
  --days 5 \
  --daily-minutes 8 \
  --mode guided \
  --tone short_video \
  --lark-push
```

追剧式：

```bash
python3 -m app.cli create-guided-reading-plan \
  --source-file /path/to/novel.epub \
  --title "小说名" \
  --days 7 \
  --daily-minutes 10 \
  --mode drama \
  --tone drama \
  --spoiler-policy avoid \
  --lark-push
```

手动发送到期导读飞书卡片：

```bash
python3 -m app.cli send-guided-reading-pushes --limit 10
```

## 你会得到什么结果

完成一次配置后，你会获得：

```text
一个已保存的书源
一套阅读计划
按天切好的阅读片段
每天一页导读
每天一小段原文
白话拆解和关键点
明天预告
阅读反馈记录
可选飞书提醒
```

这个功能的目标不是替你读完整本书，而是降低启动成本，让你每天更容易打开、读一点、继续下去。

## 当前限制

当前还没有实现：

- 根据反馈自动重排后续天数。
- EPUB 章节标题层级精细保留。
- 图片、脚注、表格、公式解析。
- 全书读完后的最终复盘报告。
- PDF / DOCX / MOBI / AZW3。

下一步优先方向：

```text
根据反馈自动调整第二天长度和口吻
EPUB 章节结构识别
全书读完复盘
```
