# Memory Model

AI Reading Coach 同时使用 ARC 本地 memory、ARC 本地 Hermes 画像快照，以及 Hermes 原生 memory。三者名字相近，但职责不同。

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

这样做的原因是：Hermes 负责判断画像应该如何更新，ARC 负责可审计写入。Hermes route agent 不直接任意改 SQLite、发消息或写文件。

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

它的历史命名容易误解。它不是 Hermes 自己的原生 memory 存储，而是 ARC 本地缓存的 Hermes 生成画像快照。用途是让 `run-daily` 能稳定、紧凑地把主画像放进推荐 prompt 的最高优先级上下文，而不是每次都让 Hermes 重新读取所有历史证据。

快照生成和使用流程：

```text
ARC 收集 SQLite reading profile + ARC applied memory
-> Hermes reading.profile.sync_snapshot 生成画像快照
-> ARC 写 memory/HERMES_NATIVE_PROFILE.md
-> ARC 同步 compact entry 到 /home/ubuntu/.hermes/memories/USER.md
-> 下一次 run-daily 优先读取这份快照作为画像上下文
```

因此：

- `memory/HERMES_NATIVE_PROFILE.md` 是 ARC 本地 cache。
- `/home/ubuntu/.hermes/memories/USER.md` 是 Hermes 原生用户 memory。
- `/home/ubuntu/projects/hermes-agent` 是 Hermes-agent 代码目录，不是默认 memory 目录。

## 4. 反馈如何进入画像

正常反馈链路如下：

```text
用户提交反馈
-> ARC 写 feedback_events
-> 下一次 run-daily 处理未处理反馈
-> Hermes reading.feedback.ingest 判断是否更新主画像
-> ARC 写 hermes_profile_update_events 审计
-> 如果 Hermes 返回 applied，ARC upsert [arc-reading-profile] 到 Hermes 原生 USER.md
-> ARC 按本地规则更新 profile_items
-> feedback_events 标记 processed
```

这条链路不走 fallback。Hermes ingest 失败、返回无效 JSON、超时或要求更新但没有 memory entry，都会让本次 `run-daily` 失败，并保留反馈为未处理，方便修复后重跑。

## 5. 诊断命令

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
