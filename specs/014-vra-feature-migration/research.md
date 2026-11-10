# Research: omission audit and sharp page images

Each entry is Decision, Rationale, Alternatives. Facts about the VRA script come from
`scripts/extraction/extract_included_projects.py` in the VRA repository at `HEAD` (read
2026-11-10); facts about quotable from this repository at the spec's commit.

## 1. Where the audit runs

- **Decision**: after the first-pass tables are built and grounded (`ground_document`), per table,
  as a step that takes a `Table` and returns a `Table`, like `recheck_table`. It runs before the
  extra-field attachment and the merge, and it grounds the table again only if it accepted
  something. Order: extract, ground, **audit**, extra fields, merge, recheck.
- **Rationale**: the audit needs the row windows and column ranges that `check_positions` stores
  on each `PageGrounding`, and it needs the cells' grounding to know what is empty. Taking a
  grounded table gets both for free and costs a second `ground_document` only on a page where
  something was added. The VRA script grounds a provisional copy first, which does the same work
  every time.
- **Alternatives**: audit before any grounding with a provisional grounding (the VRA way, always
  pays the extra pass); audit after the merge (a merged table would have to be audited as parts
  anyway, and a part's words are judged against that part's own pages).
- **Spec link**: FR-002 now says "after the first-pass extraction (and its grounding) and before
  the final grounding".

## 2. Which text the unexplained words come from

- **Decision**: `Table.layers[page]`, the layer the table is grounded against. That is the whole
  page when one table is on it, and the table's band when several are (the band comes from the
  first and last row text discovery reported, see `steps/layout.py: shared_bands`).
- **Rationale**: exactly what the user chose (clarification, 2026-11-10) with no new code, and
  the band logic of spec 004 is reused.
- **Alternatives**: recompute a band from the extracted rows (rejected by the user's answer: it
  cannot see a dropped first or last row).

## 3. Unexplained words and page furniture

- **Decision**: port `unmatched_tokens`, `audit_furniture` and `audit_words` from VRA, using
  `Layer.tokens`, `Layer.tok_word` and `tokenize`. A page token is unexplained when the cells'
  token multiset has none left for it. Furniture: a token unexplained on at least 30% of the
  table's pages, for tables of at least five pages.
- **Rationale**: quotable's `Layer` is the same structure as VRA's (`tokens`, `tok_word`,
  `words`), so the functions port without change. Tokenization is the shared `tokenize`, so
  dots and dashes make no tokens and a dot-leader cell is never an omission (spec edge case).
- **Alternatives**: none worth weighing; this is the rule the spec states.

## 4. Near-spelling allowance without a new dependency

- **Decision**: a small function, "Damerau-Levenshtein distance at most 2" (optimal string
  alignment: insert, delete, substitute, swap two neighbours), written in pure Python for words of
  at least five letters. It is about a dozen lines.
- **Rationale**: VRA imports `rapidfuzz.distance.DamerauLevenshtein`. quotable does not depend on
  `rapidfuzz` (checked in `pyproject.toml` and the environment: not installed). Ponytail and
  principle VI say not to add a dependency for a few lines. Words are short and the page
  vocabulary is a few hundred tokens, so speed is not a concern.
- **Alternatives**: add `rapidfuzz` (a pinned dependency for one call); `difflib` ratio (not an
  edit distance, would change which words qualify).

## 5. The audit request and its answer

- **Decision**: new answer models `MissingRow(after_row, values)`, `FilledCell(row, column,
  value)` and `Omissions(missing_rows, filled_cells)` in `llm/answers.py`, and the prompts of VRA
  (`AUDIT_PROMPT`, the word hint, the empty-cell hint) with one addition that VRA also makes: the
  position rule ("decide which column a value belongs to only from its horizontal position;
  an empty cell stays empty"). The parts are the numbered column structure, the page image, the
  listed rows and the hints. Stage name `audit`.
- **Rationale**: the prompts contain nothing specific to VRA (checked: no column or document
  names). The position rule matters here because the audit reports values for empty cells, where
  a value filed in the neighbouring column is the likely error.
- **Alternatives**: reuse the recheck request (it works from flagged cells, not omissions).

## 6. Judging a proposal

- **Decision**: port `_cell_outcome`, `_row_outcome`, `_is_copy`, `_all_exact` (now `_all_found`), `_draws_on`,
  `_near_word` as `steps/audit.py`. A proposal's values are first respelled to the page's spelling
  for the check only (the near-spelling rule), then grounded with `ground_rows` against the
  table's layer: every cell must be `exact`, `fuzzy` or `empty`; `ungrounded` is refused. The
  proposal keeps the model's spelling. (Changed after the live run: it first required `exact`,
  which refused correct rows whose text layer splits or misreads a word; the final grounding now
  flags a `fuzzy` cell and the recheck corrects it.)
  Outcomes (reported in `Table.audit`): `accepted`, `invalid_row`, `invalid_cell`, `duplicate`,
  `not_empty`, `repeated`, `ungrounded`, `no_evidence`, `empty`.
- **Rationale**: same rules as the spec's FR-006, FR-007; `ground_rows` is quotable's own
  grounding, so principle I holds by construction.
- **Alternatives**: none.

## 7. Applying accepted proposals and numbering

- **Decision**: fills are applied to the listed rows first, then accepted rows are inserted after
  the listed row each names (0 means first), in the order the model gave them. Rows are then
  numbered by position (spec assumption). The result is a new `PageResult` list; the table is
  grounded again with `ground_document`, like `recheck`'s `_regrounded`.
- **Rationale**: VRA's stable `labels` numbering would add a second row number to `Row`,
  `records()`, the frames, saved runs and the review app (spec assumption). Verdicts are keyed
  by page, row and column and show as stale when the value differs.
- **Alternatives**: VRA's stable labels (rejected in the spec).

## 8. Empty-cell hints

- **Decision**: for each text-layer word of the page, find the row window (`PageGrounding.row_windows`)
  and column range (`PageGrounding.column_ranges`) holding its centre; if that cell of the
  listed rows is empty, name the cell and the word. At most 40, in row order. Columns without a
  fitted range are skipped.
- **Rationale**: both structures are already stored by `check_positions`. VRA gets the same data
  from its `_Grid`.
- **Alternatives**: count tokens per column instead of position (VRA's own comment says a page-wide
  token count cannot tell which copy of a repeated word is the leftover).

## 9. Image policy by provider

- **Decision**: a small frozen `ImagePolicy(dpi, detail, max_patches, max_side)` in a new
  `llm/images.py`, with `TODAY = ImagePolicy(150, "high")` and `policy_for(model, sharp)`:
  OpenAI gives `(300, "original", max_patches=30_000)`, Anthropic `(300, "high", max_side=8_000)`,
  anything else `TODAY`. The provider is the text before `:` of `model_name(model)`; OpenAI is
  `openai`, `openai-chat` and `openai-responses` (pydantic-ai's prefixes), Anthropic is
  `anthropic`. `model_name` already turns a `Model` instance into `system:model_name`.
- **Rationale**: only OpenAI's `original` value is documented to give the full resolution.
  pydantic-ai passes `detail` to the OpenAI, Groq, Mistral and xAI models unvalidated (read in
  the installed `pydantic_ai/models/*.py`), so `original` could be rejected there; its Anthropic
  model ignores the value (no `vendor_metadata` use). Anthropic's limits (8,000 px a side) are
  from its vision documentation, read 2026-11-10 (see the spec's research notes).
- **Alternatives**: one rule for every provider (sends `original` to providers that may reject it);
  a caller setting for the detail value (a third public argument nobody asked for).

## 10. How the image reaches the model

- **Decision**: `Image` gains `detail: str = "high"`. `PydanticAIClient.ask` uses it instead of the
  literal `"high"`. `request_key` fingerprints the image bytes as now and adds the detail only when
  it is not `"high"`, so every existing key is unchanged.
- **Rationale**: keeps `sharp_images=False` byte-identical (spec FR-020) and the change in one
  place. With 300 dpi the bytes differ anyway, so the detail in the key matters only as a guard.
- **Alternatives**: put the detail in the client's `identity` (every request of a run would key
  differently, including discovery that keeps `high`).

## 11. Rendering sharp images

- **Decision**: `render_png(page, dpi=DPI)`. The pipeline keeps its list of 150-dpi `pngs` for
  discovery and extra fields. Extraction, recheck and audit render their own page at
  `policy.dpi` when they need it (the pipeline already opens the PDF in `recheck_table`; extraction
  opens it per page). Nothing renders all pages at 300 dpi at once.
- **Rationale**: a 300-dpi PNG of a Letter page is megabytes; holding every page of a long
  document in memory would be the worst case. Rendering when needed is what `recheck_table` does.
- **Alternatives**: render a second list up front (memory); cache PNGs on disk (new storage).

## 12. The size check

- **Decision**: `check_page_sizes(pdf, policy)` in `llm/images.py`, called in `run_pipeline` after
  the text-layer check and before the first render or request. It reads each page's rectangle
  (rotation included), computes pixel size at `policy.dpi`, and raises `ExtractionError` for the
  first page over `max_patches` (OpenAI: `ceil(w/32) * ceil(h/32)`) or `max_side`. It does
  nothing when the policy has no limit.
- **Rationale**: spec FR-023 and SC-006. Pixel size comes from the page rectangle, so nothing is
  rendered.
- **Alternatives**: check at render time (the failure would come after discovery was paid for).

## 13. Defaults of the internal function

- **Decision**: `run_pipeline(..., audit=False, images=TODAY)`; `extract_tables` and
  `extract_tables_async` default to `audit=True, sharp_images=True` and pass the values on.
- **Rationale**: `run_pipeline` is internal and driven by hundreds of tests with fake clients that
  fail on an unknown stage. Keeping its defaults at the old behavior keeps those tests unchanged
  (spec SC-001); the public defaults are covered by tests that go through `extract_tables`.
- **Alternatives**: public defaults on `run_pipeline` too (every fake would have to answer an
  audit request or every test would need `audit=False`).
- **Known cost**: tests that call the public function with a counting fake model (listed in the
  plan) get `audit=False`, or an answer for the new stage, where they count requests.

## 14. Saved runs

- **Decision**: add to `run.json` settings `audit` and `sharp_images`, and to each table in
  `tables.json` an `audit` list. The reader uses `.get(..., default)` for the new keys. The format
  version stays 1.
- **Rationale**: the reader today indexes `data["proposals"]` directly, so a run saved before
  this change would be skipped as damaged if the new key were required. Additive keys with
  defaults need no migration (constitution IV).
- **Alternatives**: bump the version (every old run would stop loading).

## 15. Output columns

- **Decision**: `OutputNames` gets `audit` (default name `audit_added`, collision-safe like its
  neighbours) and `records()` / the frames add the column last, after `recheck_changes`.
- **Rationale**: existing columns and their order do not change (spec FR-010).
- **Alternatives**: none.

## 16. Concurrency

- **Decision**: audit requests share the `asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)` that
  extraction uses, passed into the audit step.
- **Rationale**: the audit makes up to one request per page, so a long document would otherwise
  send hundreds at once. (`recheck_table` has no gate; this spec does not change it.)
- **Alternatives**: no gate, like recheck (rejected: the audit is on by default and per page).

## 17. Evidence still to be gathered

- No measurement of cost or benefit exists (the VRA commits record none). The live run of SC-005
  is the first. Nothing in the design depends on its outcome except the two defaults, which the
  user has already set.
- Anthropic behavior and the OpenAI `original` value are not exercised by any test that calls a
  real provider. The OpenAI value is the user's report; Anthropic's is documentation only.
