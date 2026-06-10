# 2026-06-08 Hermes Subagent Fit Assessment

## Background

The user asked whether the daily reading recommendation workflow should move from the current ARC-orchestrated Hermes route calls to a Hermes-led workflow where a main Hermes agent can dispatch subagents.

The user placed Hermes' prior recommendation in `back_prompt.md`. The core suggestion was:

- ARC should not drive Hermes step-by-step as chat turns.
- ARC should build a structured task package.
- Hermes could act as a main agent, split work into subagents, collect results, and return a final structured recommendation.
- ARC should still control permissions, budget, schema, writes, and acceptance criteria.

## Current Runtime Reality

The current `run-daily` workflow remains ARC-orchestrated:

```text
ARC creates run
ARC processes feedback
ARC reads profile and recommendation history
ARC calls Hermes reading.recommend.intent
ARC searches book sources
ARC calls Hermes reading.recommend.generate
ARC filters hard exclusions and ranks candidates
ARC writes SQLite, creates reading packs, and sends messages
```

The Hermes adapter is not using a native Hermes conversation thread. The local session in ARC is explicit payload context only:

```text
hermes_internal_thread = not_supported_by_current_reflect_json_wrapper
```

The wrapper at `/home/ubuntu/projects/hermes-agent/bin/reflect-json` invokes Hermes through:

```bash
hermes --oneshot <prompt> --ignore-rules
```

Its generated safe config disables toolsets including:

```text
delegation
memory
terminal
file
browser
web
session_search
```

Therefore the current implementation does not use Hermes subagents, persistent Hermes sessions, native session search, or direct Hermes tool execution.

## Assessment

Hermes' suggestion is directionally useful but should not be applied as a direct replacement for `run-daily`.

Useful and aligned parts:

- ARC should continue controlling boundaries, permissions, budget, schema, and acceptance criteria.
- Hermes is well suited for profile interpretation, semantic recommendation judgment, candidate explanation, ranking rationale, and style.
- A structured task package is better than an unbounded free-form prompt.
- If subagents are used later, ARC must cap subagent count, runtime, allowed tools, and output schema.

Not suitable for immediate adoption:

- Handing the entire daily job to Hermes as a black-box agent.
- Letting Hermes subagents perform final business writes, delivery, memory updates, or retry logic.
- Letting Hermes independently search, write files, update SQLite, send messages, or mutate native memory.
- Replacing ARC's hard-exclusion checks, source-aware ranking, audit tables, and delivery outbox with agent behavior.

## Decision

Keep the current production path:

```text
ARC = business orchestrator and source of truth
Hermes = bounded JSON decision layer
```

Do not enable Hermes subagents for the full daily workflow yet.

Use the subagent idea only as a future controlled experiment, preferably as a planning layer rather than an execution layer.

## Recommended Future Route

If this direction is pursued, add a new experimental route instead of replacing current daily routes:

```text
reading.recommend.plan_v1
```

Suggested responsibility:

- Interpret profile and recent history.
- Propose task decomposition.
- Suggest search queries.
- Return theme intents, candidate discovery angles, and acceptance criteria.
- Optionally describe subagent roles without executing business side effects.

Example output shape:

```json
{
  "subtasks": [
    {
      "role": "profile_interpreter",
      "goal": "Summarize stable preferences, weak signals, fatigue, and avoidances."
    },
    {
      "role": "candidate_discovery",
      "goal": "Propose book discovery angles and search queries."
    },
    {
      "role": "quality_reviewer",
      "goal": "Define filtering and ranking criteria for candidate books."
    }
  ],
  "theme_intents": [
    {
      "theme": "科幻经典中的文明想象、技术伦理与未来社会",
      "slot": "profile_fit",
      "reason": "User profile supports classic science fiction and technology ethics."
    }
  ],
  "search_queries": [
    "科幻经典 文明想象 技术伦理 书籍 书评"
  ],
  "acceptance_criteria": [
    "Recommend books, not articles.",
    "Respect hard exclusions.",
    "Include at least one classic/high-reputation literature angle and one classic science fiction angle when profile evidence supports them."
  ]
}
```

ARC would still execute search, schema validation, source-aware ranking, hard-exclusion filtering, SQLite writes, reading-pack generation, and message delivery.

## Requirements Before Real Subagent Execution

Before Hermes subagents can be used for production daily recommendations, the wrapper/runtime would need:

- A controllable Hermes session or thread API, not only `--oneshot`.
- Explicit support for bounded delegation/subagents.
- Budget controls: max subagents, max wall time, max model calls, max search calls.
- Tool policy controls: read-only search may be allowed; file, memory, SQLite, and messaging writes remain forbidden.
- Structured trace output so ARC can audit which subagent produced which evidence.
- Strict final schema validation and fallback behavior.
- Tests that prove subagent failure does not corrupt ARC state or mark feedback as processed incorrectly.

## Current Recommendation

Do not migrate the full daily workflow to Hermes subagents now.

The pragmatic next step is a small `reading.recommend.plan_v1` experiment that lets Hermes produce a richer plan while ARC remains the executor and fact system.
