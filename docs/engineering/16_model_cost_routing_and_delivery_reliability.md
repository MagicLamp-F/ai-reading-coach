# Model Cost Routing and Delivery Reliability

Date: 2026-06-02

This document records the current cost-control direction for Hermes, Codex, future OpenClaw, and account-backed CLI tools such as Google Antigravity or Gemini CLI. It also records the 2026-06-02 daily Feishu delivery failure.

## Current Situation

- `ai-reading-coach` currently keeps the business workflow in this repository.
- Direct model calls go through `app/llm.py` with `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_BASE_URL`.
- Hermes is integrated through an external command configured by `HERMES_AGENT_COMMAND`.
- Daily recommendations, reflection, and reading packs already have provider switches:
  - `DAILY_RECOMMENDATION_PROVIDER`
  - `HERMES_REFLECTION_PROVIDER`
  - `READING_PACK_PROVIDER`
- When Hermes is used, this repository may record `api_calls=0`, but Hermes can still spend tokens internally if its own runtime calls the same paid API relay.

## Token Cost Hotspots

The highest-risk path is deep reading-pack generation:

```text
recommendation metadata
+ user profile context
+ Hermes long-term memory
+ public source excerpts / raw content
+ deep_read_pack_v2 schema requirements
-> Hermes/model synthesis
```

This can be expensive because each book may include multiple source excerpts and the output schema asks for a long structured result. Timeout history also shows that `reading.deep_read_pack` can run for several minutes and still fall back.

Lower-risk or non-model work should not use a premium model:

- URL safety checks.
- Source fetching.
- HTML cleanup.
- Deduplication.
- SQLite writes.
- Markdown rendering.
- Basic source snippet extraction.

## Antigravity / Gemini CLI Assumption

The user has a Gemini Pro account but does not currently have a separate API key for `agy` / Antigravity.

Treat Antigravity or Gemini CLI as an account-backed CLI candidate, not as a confirmed production API provider yet. Before using it in a scheduled backend workflow, verify:

- The CLI exists on the server.
- It can run non-interactively under systemd.
- It can authenticate without browser prompts or desktop keyring dependencies.
- It can accept stdin payloads.
- It can return strict JSON without extra prose.
- It has stable timeout behavior.
- It does not require broad filesystem permissions for simple model tasks.

If any of these fail, keep it as a developer/manual tool rather than a production runtime.

## Recommended Routing

Use a tiered route policy:

| Task class | Preferred runtime | Notes |
| --- | --- | --- |
| Fetch, parse, dedupe, persist | Local Python / OpenClaw tools | No LLM unless the source is ambiguous. |
| Source snippet compression | Gemini / Antigravity CLI candidate | Cheap/basic model task if non-interactive JSON works. |
| Candidate expansion | Gemini / Antigravity CLI candidate | Must be validated by source-aware ranking. |
| Final recommendation selection | Hermes with high-quality model | Requires user-profile reasoning. |
| Deep reading-pack final synthesis | High-quality model, but with capped input | Keep source excerpts compact. |
| Weekly reflection and memory update | Hermes with high-quality model | Higher judgment requirement. |
| Browser automation | OpenClaw | Tool executor, not default model caller. |

## Step-by-Step Plan

### Step 1: Reduce Current Waste Without New Providers

- Cap source excerpts passed into reading-pack generation.
- Disable raw source content unless needed.
- Lower daily recommendation count during testing.
- Avoid repeated real `run-daily` smoke tests unless explicitly accepted.
- Keep fallback packs cheap and deterministic.

Suggested env direction:

```text
SOURCE_SEARCH_INCLUDE_RAW_CONTENT=false
SOURCE_SEARCH_MAX_RESULTS=2
SOURCE_SEARCH_QUERIES_PER_BOOK=1
DAILY_RECOMMENDATION_COUNT=1
HERMES_AGENT_TIMEOUT_SECONDS=180
```

### Step 2: Add a Cheap Task Adapter

Add a small adapter contract for cheap JSON tasks:

```text
CheapTaskAdapter.run_json(task_name, payload, timeout_seconds) -> dict
```

Candidate implementations:

- `LocalHeuristicAdapter`
- `GeminiCliAdapter`
- `AntigravityCliAdapter`

This adapter should only receive sanitized task payloads, not credentials, database handles, or broad filesystem permissions.

### Step 3: Split Deep Reading Pack Generation

Split the current one-shot `reading.deep_read_pack` route into two stages:

```text
source excerpts
-> cheap source compression
-> compact source dossier
-> high-quality final deep_read_pack_v2 synthesis
```

This keeps expensive model input small and makes failures easier to diagnose.

### Step 4: Route Hermes by Task Cost

Hermes should choose runtime by route:

- `reading.source.compress`: cheap CLI candidate.
- `reading.recommend.intent`: cheap or medium model.
- `reading.recommend.generate`: high-quality model.
- `reading.deep_read_pack`: high-quality model with compact context.
- `reading.reflection.generate`: high-quality model.

The business orchestrator in `ai-reading-coach` should still own SQLite writes, Feishu sends, artifacts, and retry policy.

### Step 5: Add Budgets and Observability

Each model route should record:

- provider/runtime name;
- input character count;
- output character count;
- timeout seconds;
- fallback used;
- route name;
- error summary.

Add hard limits:

- max input chars per route;
- max source count per book;
- max daily model calls;
- max real smoke runs per day.

## Feishu Daily Delivery Failure on 2026-06-02

The daily timer did trigger:

```text
ai-reading-coach-daily.timer
last trigger: Tue 2026-06-02 08:00:01 CST
next trigger: Wed 2026-06-03 08:00:00 CST
```

The service failed during Feishu send:

```text
run_id=37
run_type=daily_recommendation
status=failed
started_at=2026-06-02 00:00:01 UTC
finished_at=2026-06-02 00:00:15 UTC
error=recommendation send failed: recommendation_id=60
```

Journal logs show Feishu returned:

```text
code=11232
msg=frequency limited psm[lark.oapi.app_platform_runtime]appID[1500]
```

The current client retried after 2 seconds and 4 seconds, then gave up. This means the daily job ran, generated a recommendation, but did not deliver it to Feishu because the webhook was rate limited.

## Delivery Reliability Fixes

Recommended follow-up changes:

1. Treat Feishu `11232` as a longer cooldown condition, not a short retry.
2. Add configurable Lark retry settings:
   - `LARK_MAX_SEND_ATTEMPTS`
   - `LARK_RETRY_BASE_SECONDS`
   - `LARK_RATE_LIMIT_COOLDOWN_SECONDS`
3. Add a small send outbox table or resend command so generated recommendations can be resent after Feishu rate limits.
4. Avoid sending several cards back-to-back; combine daily recommendation, reading-pack preview, and profile summary into fewer messages where possible.
5. Make `run-daily` mark generation success separately from delivery failure, so generated content is not lost operationally.

## Immediate Next Actions

1. Fix Feishu delivery reliability first, because today's failure was delivery-side, not generation-side.
2. Then reduce reading-pack prompt size and route cheap source compression away from the premium API.
3. Only after that, test Antigravity/Gemini CLI non-interactive JSON behavior on the server.
4. If CLI behavior is stable, add it behind a narrow cheap-task adapter instead of making Hermes or OpenClaw depend on it globally.
