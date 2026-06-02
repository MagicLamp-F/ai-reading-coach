# Deep Read Pack v2 TODO

Plan id: `2026-06-01_deep_read_pack_v2`

Status: implemented in code on 2026-06-01; full unit test verification was started and should be checked before real Tavily/Hermes/Feishu smoke.

Related docs:

- `docs/engineering/14_fast_read_pack_design.md`
- `docs/engineering/15_current_scope_and_next_plan.md`
- `docs/engineering/development_history/2026-05-31_tavily_source_grounding_plan.md`
- `docs/engineering/development_history/2026-05-31_source_aware_candidate_ranking_plan.md`

## Current User Problem

The daily Feishu card is received, and the recommendation -> reading pack -> Feishu path is basically connected.

However, the current fast read pack still feels like an abstract summary. It explains why the book fits the user and gives concise thesis/route/concepts, but it does not yet help the user feel that they have "passed through the book once".

The target is a content-rich compressed reading experience:

- less abstract recommendation language;
- more concrete book content;
- more chapter/part level expansion;
- more examples, stories, cases, arguments, and author reasoning;
- clear source visibility and no silent fallback;
- legal/public-source grounded, without copying full copyrighted text.

## Current Implementation Status

Known working pieces:

- Hermes is installed externally at `/home/ubuntu/projects/hermes-agent`.
- `ai-reading-coach` calls Hermes through `/home/ubuntu/projects/hermes-agent/bin/reflect-json`.
- Daily recommendation can use Hermes.
- Reading pack generation now uses Hermes with route `reading.deep_read_pack` and schema `deep_read_pack_v2`.
- Feishu card can include reading pack preview.
- SQLite stores reading packs, artifacts, book sources, and reading-pack-source links.
- Tavily key is expected at `/home/ubuntu/.config/tavily/api_key`.
- Source-aware candidate ranking exists and can select books with better public-source coverage.

Important issue fixed in this pass:

- `app/source_collector.py` had a control-flow/indentation bug in `_collect_search_results`.
- The loop now reads search result fields with duck typing, skips unsafe URLs, deduplicates URLs, prefers Tavily `raw_content`, and falls back to `HttpClient` fetch.

## Immediate Fix TODO

1. Fix `app/source_collector.py`. Done.

   Target function:

   - `BookSourceCollector._collect_search_results`

   Required behavior:

   - Iterate search results.
   - Read result fields with duck typing or `SearchResult`.
   - Skip unsafe URLs with `is_safe_book_source_url`.
   - Deduplicate URLs.
   - Prefer `raw_content` if available.
   - Otherwise fetch URL through `HttpClient`.
   - Store sources in `book_sources`.

   Suggested robust shape:

   ```python
   for result in results:
       url = str(getattr(result, "url", "")).strip()
       title = str(getattr(result, "title", "")).strip()
       content = str(getattr(result, "content", "") or "")
       raw_content = str(getattr(result, "raw_content", "") or "")
       if not url or url in seen_urls or not is_safe_book_source_url(url, title):
           continue
       seen_urls.add(url)
       ...
   ```

2. Add or keep tests for source safety and Tavily raw-content usage. Done.

   Relevant tests:

   - `tests/test_source_collector.py`
   - `test_collect_for_recommendation_fetches_tavily_search_results`
   - `test_collect_for_recommendation_uses_tavily_raw_content_before_fetching_url`
   - `test_is_safe_book_source_url_blocks_suspicious_pdf_sources`

3. Run focused tests. Done.

   ```bash
   python3 -m py_compile app/source_collector.py app/reading_pack.py
   python3 -m unittest tests.test_source_collector tests.test_reading_pack -q
   ```

4. Run full tests. Started in the implementation session; confirm final result before external smoke.

   ```bash
   python3 -m unittest discover -q
   ```

## Deep Read Pack v2 Product TODO

The current `fast_read_pack_v1` schema should be upgraded or extended without breaking existing records.

Recommended new route/schema:

- route: `reading.deep_read_pack`
- schema: `deep_read_pack_v2`

Implemented route/schema:

- route: `reading.deep_read_pack`
- schema: `deep_read_pack_v2`
- content includes `depth_profile: "deep_v2"`
- normalizer remains backward-compatible with legacy fast-pack fields returned by older test fixtures or temporary model behavior.

Required sections:

- `book_positioning`: what kind of book this is and what problem it enters;
- `author_project`: what the author is trying to prove or change;
- `expanded_argument`: 8-12 steps reconstructing the author's reasoning in order;
- `part_walkthrough`: part/chapter-level walkthrough, each item with:
  - title or inferred title;
  - what happens in this part;
  - key claim;
  - concrete examples/cases;
  - what the user should absorb;
- `story_case_bank`: concrete stories, examples, case studies, or scenarios;
- `concept_cards`: concept -> meaning -> why it matters -> how to recognize it;
- `mental_model_map`: how concepts connect;
- `what_you_would_miss_if_skipping_full_book`;
- `ten_min_absorption_path`: not just "read summary", but a sequence of concrete paragraphs/sections to read in the pack;
- `thirty_min_absorption_path`;
- `two_hour_absorption_path`;
- `user_application_playbook`;
- `source_quality`;
- `source_refs`;
- `limitations`.

Tone requirement:

- Write like compressed book notes, not like a recommendation memo.
- Prefer "the book first argues..., then shows..., then warns..." over generic definitions.
- Include concrete examples when public sources provide them.
- If concrete examples are not available from sources, say so explicitly instead of inventing.

## Prompt TODO

Update `HermesReadingPackAdapter.generate_pack` and the legacy LLM branch in `app/reading_pack.py`.

Status: done. Both Hermes and legacy LLM prompts now request a source-grounded compressed pass through the book and forbid claiming unavailable full-text access.

The prompt should tell Hermes:

- The user does not want a short overview.
- The output should feel like a compressed pass through the book.
- Use provided source excerpts heavily.
- Extract concrete examples, cases, named mechanisms, chapter sequence, and author argument order.
- Do not copy long copyrighted passages.
- Do not claim to have read unavailable full text.
- Mark inferred chapter maps as inferred.
- If sources are only reviews/snippets, state exact limitations.

## Markdown TODO

Update `render_fast_read_pack_markdown` so the saved file becomes useful even if Feishu preview is short.

Status: done. The Markdown artifact now uses the deep-pack section order below.

Suggested Markdown order:

1. `What This Book Is Really About`
2. `Author's Project`
3. `Argument Walkthrough`
4. `Part / Chapter Walkthrough`
5. `Stories, Cases, Examples`
6. `Concept Cards`
7. `Mental Model Map`
8. `What You Miss If You Skip The Full Book`
9. `10 / 30 / 120 Minute Absorption Paths`
10. `How This Applies To You`
11. `Limits, Doubts, Opposing Views`
12. `Source Quality And References`

## Feishu TODO

Do not try to put the whole deep pack into the Feishu card.

Status: done. Feishu preview shows source quality, thesis, argument steps, chapter/part items, examples, limitations, and artifact path.

Feishu should show:

- source status and whether fallback happened;
- one strong thesis;
- 3-5 argument steps;
- 2-3 concrete examples/cases;
- 3 chapter/part walkthrough items;
- machine artifact path.

The long content should stay in:

```text
library/YYYY/MM/YYYY-MM-DD__book-title/reading-pack.md
```

## Source And Safety TODO

Keep the current safety position:

Status: kept. No browser automation, OpenClaw, Docker, SSH/firewall/system-user, private network fetch, or API-key-printing changes were made.

- no OpenClaw yet;
- no browser automation yet;
- no Docker change;
- no SSH/firewall/system-user changes;
- no private network fetches;
- no suspicious full-book/PDF piracy domains;
- no API key printing.

The source collector should only store:

- official pages;
- publisher pages;
- legal sample chapters;
- tables of contents;
- author interviews;
- talks/transcripts;
- reviews and serious book notes;
- public metadata pages.

Unsafe source examples already blocked or should remain blocked:

- `dokumen.pub`
- `pdfcoffee.com`
- `vdoc.pub`
- `epdf.pub`
- `pdfdrive.com`
- `z-lib.org`
- `libgen.*`
- `annas-archive.org`
- `oceanofpdf.com`

PDF policy:

- Block arbitrary PDF-looking URLs by default.
- Allow known trusted official domains or obvious sample chapters only.

## Token Cost Notes

Yesterday's high token use was likely not only from writing docs.

Main contributors:

- repeated large code/doc reads in Codex sessions;
- long engineering docs;
- multiple Hermes reading-pack generations;
- source-grounded prompts that include Tavily raw excerpts;
- real daily runs with several books;
- repeated context handoffs and debugging.

Deep read pack v2 will use more tokens than the current summary-style pack.

Token controls to add later:

- cache source digests per `book_id`;
- generate source digest once, then generate pack from compact digest;
- cap source excerpt chars per source;
- cap number of sources per book;
- avoid regenerating existing packs unless source set or prompt version changes;
- record prompt/schema version in `reading_packs.content_json`.

## Verification Commands

After implementation:

```bash
python3 -m py_compile app/source_collector.py app/reading_pack.py app/lark.py
python3 -m unittest tests.test_source_collector tests.test_reading_pack tests.test_lark -q
python3 -m unittest discover -q
```

Optional real smoke, only when the user accepts Tavily/Hermes/Feishu cost:

```bash
DAILY_RECOMMENDATION_PROVIDER=hermes-agent \
READING_PACK_PROVIDER=hermes-agent \
HERMES_AGENT_TIMEOUT_SECONDS=240 \
SOURCE_AWARE_RECOMMENDATIONS=true \
SOURCE_AWARE_STRICT_MODE=true \
SOURCE_AWARE_CANDIDATE_COUNT=6 \
SOURCE_MIN_COVERAGE_SCORE=0.5 \
SOURCE_AWARE_ALLOW_LIMITED_FILL=false \
SOURCE_SEARCH_ENABLED=true \
SOURCE_SEARCH_DEPTH=advanced \
SOURCE_SEARCH_QUERIES_PER_BOOK=3 \
SOURCE_SEARCH_MAX_RESULTS=3 \
SOURCE_SEARCH_INCLUDE_RAW_CONTENT=true \
SOURCE_FETCH_TIMEOUT_SECONDS=6 \
SOURCE_FETCH_RETRIES=0 \
python3 -m app.cli run-daily
```

Do not print API keys or `.env`.

## Completion Criteria

- Source collector tests pass.
- Full unit test suite passes.
- Reading pack Markdown contains content-rich sections, not just abstract summary.
- Feishu preview clearly marks source quality and fallback status.
- SQLite stores the generated pack and source references.
- If public sources are weak, the pack says exactly what is missing.
- No unsafe book source is stored or used in a prompt.
