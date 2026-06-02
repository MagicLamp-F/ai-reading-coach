# 2026-06-02 Hermes / ARC / Feishu Delivery Summary

Date: 2026-06-02

## One-line Status

`ai-reading-coach` has moved from Feishu-only long text delivery toward an ARC-hosted reading experience: Hermes generates long reading packs by default, ARC stores structured/file artifacts, Feishu sends a preview and business URL, and the user reads/feeds back on a responsive ARC page.

## Completed Work

### Hermes as the Default Generation Path

- Daily recommendations, reading packs, and reflection now default to `hermes-agent` at the application config level.
- Production `.env` was aligned so the active routes use Hermes rather than the repository's direct OpenAI client:
  - `DAILY_RECOMMENDATION_PROVIDER=hermes-agent`
  - `READING_PACK_PROVIDER=hermes-agent`
  - `HERMES_REFLECTION_PROVIDER=hermes-agent`
  - `HERMES_AGENT_TIMEOUT_SECONDS=1800`
- Hermes reading-pack generation was changed from a short one-shot pack to segmented generation:
  - `foundation`
  - `walkthrough`
  - `concepts_and_cases`
  - `application_routes`
- Segment outputs are merged into `deep_read_pack_v2`.
- The Hermes wrapper now rejects obvious model/API failure text instead of treating it as valid generated content.

### Long Reading Pack Artifact Model

- A long Hermes reading pack was successfully generated for recommendation `60`:
  - `reading_pack_id=31`
  - `status=generated`
  - `provider=hermes-agent`
  - `content_json_chars=45231`
  - artifact path: `library/2026/06/2026-06-02__designing-data-intensive-applications/reading-pack.md`
- The generated pack was also split into module files under:

```text
library/2026/06/2026-06-02__designing-data-intensive-applications/modules/
```

- Module files:
  - `01-overview.md`
  - `02-argument.md`
  - `03-walkthrough.md`
  - `04-concepts-cases.md`
  - `05-application.md`

### ARC Reading Page

- Added signed business URL support for reading packs:
  - `GET /reading-pack?id=<reading_pack_id>&token=<signature>`
  - `module=` query parameter for page/module selection.
- Added ARC reading modules:
  - `overview`
  - `argument`
  - `walkthrough`
  - `concepts-cases`
  - `application`
- Added page features:
  - full-pack overview cards;
  - module navigation;
  - actual scroll progress bar;
  - per-module reading guide;
  - in-page section navigation;
  - previous/next page preview;
  - inline feedback forms;
  - mobile-safe layout.
- Mobile fixes were applied after real phone feedback:
  - removed page-level horizontal overflow;
  - constrained long navigation labels;
  - split long paragraphs into readable blocks;
  - split list items into line blocks;
  - made mobile feedback non-sticky so it no longer overlaps pagination;
  - changed mobile feedback buttons to wrap in two columns.

Current live URL:

```text
http://120.53.247.229:8000/reading-pack?id=31&token=<signed-token>
```

### Inline Feedback

- Added `POST /feedback/inline`.
- Reading-pack pages now include feedback groups at the bottom of the reading flow.
- Existing signed feedback security model is reused.
- Free text remains limited to 500 characters.
- Mobile feedback is now a normal stacked section rather than a sticky bottom bar.

### Feishu Delivery Reliability

- Root cause for the missed daily delivery on 2026-06-02 was Feishu-side request frequency limiting:

```text
code=11232
msg=frequency limited
```

- The daily timer was moved from morning to early morning:

```text
04:30 Asia/Shanghai
```

- Lark retry behavior now has configurable settings and a longer cooldown for rate limits.
- Added a delivery outbox table so generated content can survive delivery failure.
- Added a resend CLI for pending deliveries.
- Historical recommendation `60` was manually enqueued and resent.

### Source-aware Recommendation and Reading-pack Context

- Source collection and source-aware candidate ranking have been strengthened.
- Public sources, raw content, and coverage scores are persisted and used before final recommendations are selected.
- Reading packs receive source context and record source links/quality in the database.

## Validation

Automated validation after the latest ARC mobile fixes:

```text
python3 -m py_compile app/server.py
python3 -m unittest tests.test_server -q
python3 -m unittest discover -q
```

Result:

```text
tests.test_server: 10 tests OK
full suite: 90 tests OK
```

Operational validation:

- `ai-reading-coach-server.service` was restarted and is active.
- The live reading-pack URL returns `200`.
- All five modules return `200`.
- Checks confirmed the page includes:
  - full-pack overview;
  - module and section navigation;
  - scroll progress;
  - paragraph/list splitting;
  - inline feedback;
  - mobile non-sticky feedback styles.

## Current Architecture Direction

The preferred direction is now:

```text
Hermes
-> generates long reading-pack text/JSON
-> ARC persists DB rows + Markdown/module files
-> Feishu sends preview + ARC business URL
-> user reads and submits feedback on ARC
-> feedback updates profile facts and future recommendation behavior
```

This is better than sending a full long pack directly through Feishu because:

- Feishu rate limits are less likely to block delivery.
- Long text can be paginated and styled.
- Feedback can be collected in context.
- Generated content remains available even if Feishu delivery fails.
- ARC can later add history, search, bookmarks, and per-section reactions.

## Remaining Risks

- The current ARC page is server-rendered HTML/CSS in `app/server.py`; this is acceptable for the current stage but should be split into templates or a frontend app when UI complexity grows.
- The reading-pack URL is signed but not user-authenticated; this is fine for personal use but not multi-user production.
- Hermes generation can still take a long time. Current timeout accepts this, but background job state is not yet visible in a user-facing UI.
- Feishu delivery reliability has an outbox/resend path, but long-term monitoring still needs daily observation.
- GitHub push is currently blocked by expired local authentication.

## Recommended Next Work

### P0: Observe the Current User Experience

- Use the ARC page on mobile for one full pack.
- Watch for:
  - horizontal page drag;
  - blocked vertical scrolling;
  - unclear paragraph grouping;
  - pagination/feedback overlap;
  - places where Hermes content is too shallow or too verbose.

### P0: One More Daily Run Observation

- Let the next 04:30 timer run.
- Check:
  - whether Hermes generated successfully;
  - whether Feishu delivered without `11232`;
  - whether the reading-pack URL is included in the preview;
  - whether delivery outbox remains empty or is resent cleanly.

### P1: ARC User-side Reading Refinement

- Add per-section feedback once the page shape is stable.
- Add a compact "reading mode" switch only if the current typography still feels dense.
- Add a reading-pack history page after user-facing single-pack quality is stable.

### P1: Cost and Runtime Control

- Keep Hermes as the default high-quality generator.
- Add route-level input/output size metrics.
- Compact source excerpts before final deep synthesis.
- Avoid repeatedly running real daily smoke tests unless explicitly needed.

## GitHub Authentication Recovery

Local commit can be created without GitHub authentication. Push requires restoring authentication.

Recommended options:

### Option A: GitHub CLI

```bash
gh auth status
gh auth login
```

Choose:

```text
GitHub.com
HTTPS
Login with a web browser
```

Then verify:

```bash
gh auth status
git push
```

### Option B: Personal Access Token over HTTPS

Create a fine-grained GitHub token with repo write access, then run:

```bash
git remote -v
git push
```

When prompted:

```text
username: <your GitHub username>
password: <the token, not your GitHub password>
```

### Option C: SSH Key

```bash
ssh -T git@github.com
```

If SSH is not configured, add a public key to GitHub and switch remote:

```bash
git remote set-url origin git@github.com:<owner>/<repo>.git
git push
```

Do not put API keys, Feishu secrets, or Hermes provider credentials into GitHub auth commands or commit messages.
