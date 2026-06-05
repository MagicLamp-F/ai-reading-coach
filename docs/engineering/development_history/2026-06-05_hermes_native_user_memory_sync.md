# 2026-06-05 Hermes Native USER Memory 同步

## 背景

此前 `memory/HERMES_NATIVE_PROFILE.md` 已经能由 Hermes 基于 ARC evidence 生成，但这是 ARC 仓库内的 snapshot。Hermes UI/CLI 的原生用户画像不会读取这个文件，因此 UI 中看不到用户画像。

排查确认：

- Hermes state DB 没有独立 memory/profile 表。
- Hermes Web UI 的 `user_profiles` 表只管理 UI/profile 元数据，不保存画像内容。
- Hermes built-in memory 实际读取当前 `HERMES_HOME/memories/USER.md` 和 `HERMES_HOME/memories/MEMORY.md`。
- 默认环境下真实路径为 `/home/ubuntu/.hermes/memories/USER.md`。

## 改动

- `HermesNativeProfileProvider` 增加 native USER memory upsert。
- `reading.profile.sync_snapshot` 输出契约增加 `hermes_user_memory_entry`。
- 如果 Hermes 未返回 compact entry，ARC 会从 snapshot 派生一条 compact entry。
- ARC 只维护一条带标记的 entry：

```text
[arc-reading-profile] User reading profile: ...
```

- 重复运行会替换该 entry，保留 Hermes 已有 USER memories。
- 写入超限、路径不可写或内容含注入风险时直接失败，不 fallback。

## 配置

```env
HERMES_NATIVE_USER_MEMORY_PATH=/home/ubuntu/.hermes/memories/USER.md
HERMES_NATIVE_USER_MEMORY_CHAR_LIMIT=1375
```

将 `HERMES_NATIVE_USER_MEMORY_PATH` 设为空可禁用同步，主要用于测试或临时排障。

## 验证

自动化：

```bash
python3 -m unittest tests.test_memory tests.test_config tests.test_metrics
python3 -m unittest discover -s tests
```

结果：

```text
19 tests OK
119 tests OK
```

真实流程：

```bash
python3 -m app.cli run-daily
```

结果：

```text
daily run_id=50 success
recommendation_id=66: 额尔古纳河右岸 / 迟子建
reading_pack id=37 status=generated generator_provider=hermes-agent
artifact: library/2026/06/2026-06-05__额尔古纳河右岸/reading-pack.md
reflection run_id=51 success
reflection_id=5 applied
```

Hermes native USER memory 检查：

```bash
python3 - <<'PY'
from pathlib import Path
path = Path('/home/ubuntu/.hermes/memories/USER.md')
print(path.read_text(encoding='utf-8'))
PY
```

结果：

```text
path: /home/ubuntu/.hermes/memories/USER.md
chars: 596
entry marker: [arc-reading-profile]
```

新 Hermes UI/CLI 会话应能读取该文件中的 `[arc-reading-profile]` entry。已经打开的旧会话不会保证实时注入，因为 Hermes built-in memory 在会话启动时冻结读取。
