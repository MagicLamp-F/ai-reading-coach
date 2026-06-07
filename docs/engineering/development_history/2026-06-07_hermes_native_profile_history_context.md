# 2026-06-07 Hermes 原生主画像与推荐历史上下文

## 背景

此前 `run-daily` 的 Priority 1 画像读源是 ARC 本地 `memory/HERMES_NATIVE_PROFILE.md`。这会让 ARC 本地快照看起来像主画像，而 Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md` 只是被同步的副本，不符合“依靠 Hermes 原生 memory 逐步丰富个人画像”的目标。

## 决策

- Hermes 原生 `/home/ubuntu/.hermes/memories/USER.md` 中的 `[arc-reading-profile]` 是主画像事实源。
- `memory/HERMES_NATIVE_PROFILE.md` 降级为 ARC 本地兼容/诊断快照。
- 推荐历史不写入 Hermes 原生 USER memory，而是由 ARC 从 SQLite 生成 `RecommendationHistoryContext` 后显式传给 Hermes。
- Hermes 负责基于主画像和推荐历史做语义选书；ARC 负责写库、审计、来源质量和 hard-exclusion 校验。
- ARC 到 Hermes 的跨天/跨反馈状态不依赖长对话。短局部链路后续可在 Hermes 支持可控 session/thread id 后再接入。

## 实现

- `HermesNativeProfileProvider.load_context()` 优先读取 Hermes 原生 USER memory 的 `[arc-reading-profile]`。
- `build_recommendation_history_context()` 从 `recommendations` 和 `feedback_events` 生成 hard exclusions、negative feedback、positive anchors、history fatigue 和 recent recommendations。
- `reading.recommend.intent` 和 `reading.recommend.generate` payload 均包含 `recommendation_history_context`。
- `reading.feedback.ingest` payload 包含当前 Hermes 原生 `[arc-reading-profile]`，让 Hermes 基于旧画像增量更新。
- `run-daily` 在生成候选后执行 hard-exclusion 过滤；如果候选全被过滤，run 失败，不 fallback。
- `generate-reading-pack` CLI 复用 workflow 中同一个 Hermes native profile provider。
- `agent.md` 记录当前架构决策，避免新 Codex 会话丢失关键上下文。

## 验证

```bash
python3 -m unittest tests.test_workflow tests.test_metrics tests.test_memory tests.test_daily_agent_adapter tests.test_profile_ingest tests.test_reading_pack
```

结果：43 tests OK。

待本次提交前继续执行：

```bash
python3 -m unittest discover
python3 -m app.cli show-hermes-profile-sync --json
python3 -m app.cli run-daily
```
