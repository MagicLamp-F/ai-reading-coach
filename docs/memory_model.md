# Memory Model

AI Reading Coach 同时使用 Hermes 原生 memory、ARC SQLite 事实账本，以及 ARC 本地 memory/artifact。三者名字相近，但职责不同。

## 1. Hermes 原生 memory

真实 Hermes 用户记忆位于当前 `HERMES_HOME/memories/` 下。当前部署默认是：

```text
/home/ubuntu/.hermes/memories/USER.md
```

这是 Hermes UI、CLI 或 Hermes-agent 新会话会读取的 built-in user memory。`/home/ubuntu/projects/hermes-agent` 是 Hermes-agent 的代码或安装目录，不等同于 `HERMES_HOME`。除非显式把 `HERMES_HOME` 配到 Hermes-agent 项目目录，否则原生 memory 不会写到 `/home/ubuntu/projects/hermes-agent`。

ARC 当前只维护 Hermes 原生 `USER.md` 中一条受控 entry：

```text
[arc-reading-profile] User reading profile: ...
```

这是当前主画像事实源。`run-daily` 会优先读取这条 entry 作为 Priority 1 用户画像上下文。Hermes 负责判断画像应该如何更新，ARC 负责可审计写入。Hermes route agent 不直接任意改 SQLite、发消息或写文件。

## 2. ARC 本地 memory

ARC 仓库内的这些文件属于 ai-reading-coach 自己的阅读系统记忆：

```text
memory/USER.md
memory/MEMORY.md
memory/change_logs/
```

它们由 reflection apply 流程维护，用于记录已应用的阅读反思和长期偏好。它们不是 Hermes 原生 memory，所以 Hermes UI 不会因为这些文件变化而自动显示用户画像。

## 3. ARC 本地 Hermes 画像快照

这个文件在 ARC 仓库内：

```text
memory/HERMES_NATIVE_PROFILE.md
```

它的历史命名容易误解。它不是 Hermes 自己的原生 memory 存储，而是 ARC 本地缓存的 Hermes 生成画像快照。当前它只作为兼容/诊断 artifact：当 Hermes 原生 `USER.md` 还没有 `[arc-reading-profile]` 时，ARC 可以用它生成并同步一条 compact entry 到 Hermes 原生 memory；一旦原生 entry 存在，`run-daily` 的 Priority 1 读源就是 Hermes 原生 `USER.md`。

快照生成和使用流程：

```text
ARC 收集 SQLite reading profile + ARC applied memory
-> Hermes reading.profile.sync_snapshot 生成画像快照
-> ARC 写 memory/HERMES_NATIVE_PROFILE.md
-> ARC 同步 compact entry 到 /home/ubuntu/.hermes/memories/USER.md
-> 下一次 run-daily 优先读取 Hermes 原生 USER.md 中的 [arc-reading-profile]
```

因此：

- `/home/ubuntu/.hermes/memories/USER.md` 是 Hermes 原生用户 memory，也是主画像事实源。
- `memory/HERMES_NATIVE_PROFILE.md` 是 ARC 本地兼容/诊断 cache，不是主画像。
- `/home/ubuntu/projects/hermes-agent` 是 Hermes-agent 代码目录，不是默认 memory 目录。

## 4. 推荐历史上下文

推荐历史不是用户画像，不写入 Hermes 原生 `USER.md`。ARC 使用 SQLite 维护事实账本，并在每次日推时生成短上下文交给 Hermes：

```text
RecommendationHistoryContext
  Hard exclusions        已读、近期明确不应重复推荐的书
  Negative feedback      不感兴趣和原因
  Positive anchors       喜欢/想深入的书和主题
  History fatigue        最近重复过多的主题
  Recent recommendations 最近推荐记录
```

这个上下文由 ARC 从 `recommendations`、`feedback_events` 等表生成。Hermes 用它做语义选书和避让，ARC 仍负责写库、审计和硬校验。

## 5. 反馈如何进入画像

正常反馈链路如下：

```text
用户提交反馈
-> ARC 写 feedback_events
-> 下一次 run-daily 处理未处理反馈
-> ARC 读取当前 Hermes 原生 [arc-reading-profile]
-> Hermes reading.feedback.ingest 基于旧画像 + 新反馈判断是否更新主画像
-> ARC 写 hermes_profile_update_events 审计
-> 如果 Hermes 返回 applied，ARC upsert [arc-reading-profile] 到 Hermes 原生 USER.md
-> ARC 按本地规则更新 profile_items
-> feedback_events 标记 processed
```

这条链路不走 fallback。Hermes ingest 失败、返回无效 JSON、超时或要求更新但没有 memory entry，都会让本次 `run-daily` 失败，并保留反馈为未处理，方便修复后重跑。

## 6. Hermes 对话/session 边界

ARC 到 Hermes 的 route 调用默认是可复现的非交互调用：每次调用都显式传入用户画像、推荐历史、反馈和来源上下文，而不是依赖一个无限增长的长对话。

局部短链路可以作为后续优化方向，例如一次 `run-daily` 内的“生成意图 -> 生成候选 -> 语义筛选”可以在 Hermes 支持可控 session/thread id 后放进同一个临时会话。但跨天、跨反馈、跨 reflection 的状态必须落到 Hermes 原生 memory 和 ARC SQLite，不依赖长对话自然记忆。

## 7. 诊断命令

查看 ARC 快照和 Hermes 原生 memory 是否同步：

```bash
python3 -m app.cli show-hermes-profile-sync --json
```

重点字段：

```text
snapshot_path
snapshot_exists
native_user_memory_path
native_user_memory_exists
arc_entry_present
arc_entry_chars
arc_entry_preview
```

当前默认预期：

```text
snapshot_path=memory/HERMES_NATIVE_PROFILE.md
native_user_memory_path=/home/ubuntu/.hermes/memories/USER.md
arc_entry_present=true
```
