# Feature Specification: Migrate two VRA improvements (omission audit, sharp page images)

**Feature Branch**: `spec/014-vra-feature-migration`

**Created**: 2026-11-10

**Status**: Approved by the user on 2026-11-10; waiting for the plan

**Input**: User description: "Adapt the omission audit and sharper page images from the VRA community-projects repository into quotable, on by default. Research Anthropic as a provider and note in the documentation that sharp images are verified only for OpenAI. Do not blank dot-leader or dash-only cells: extract cell contents exactly. One spec for all of it. Gold-table scoring, the gold annotation app and everything else from the VRA project are set aside for now."

## Summary

quotable was distilled from the VRA script `scripts/extraction/extract_included_projects.py`. Since
the two diverged (quotable's first commit, 2026-10-15) the VRA script gained changes that help any
document. This spec brings two of them over, generalized, and keeps everything quotable has gained
since (several tables per page, OCR, extra fields, cost tracking, saved runs).

1. **Omission audit.** Grounding checks the values the model gave. It cannot see a value the model
   left out: a whole row, or one cell returned empty. The audit finds these from the text layer
   (words printed in the table that no extracted cell accounts for), asks the model once about that
   page, and keeps only what the text layer supports, exactly or in part (a value with no match at
   all is refused). It is a first-class step like the recheck, so it is **on by default**.
2. **Sharp page images.** The images that carry cell text to the model are rendered at 300 dpi
   instead of 150 and, for OpenAI, sent at the highest image-detail setting, so small print is
   readable. It is **on by default**. It is verified to work for OpenAI only; the README says so.

A third VRA change, blanking cells that hold only dot leaders or dashes, is **not** migrated. The
goal is to extract cell contents exactly, so quotable keeps such cells as the model transcribed them.

Not in scope: gold-table scoring, the gold annotation app, the requestor and roster checks, the
Senate comparison, memos, standardizing, and every other part of the VRA project.

## Clarifications

### Session 2026-11-10

- Q: The user's message calls the target "goldlabel". A: Read as quotable, the project this repository holds. Nothing in the spec depends on the name. [Assumed; the user should correct this if a rename is planned.]
- Q: Is the omission audit on by default? A: Yes, like `recheck`. Omission audit and recheck are both essential steps of the process.
- Q: Are sharp images on by default? A: Yes. The user reports a significant improvement on tricky real-world cases. Anthropic's handling was researched (see Research notes); the README states that the feature is verified for OpenAI only.
- Q: On a page that holds one table, does the audit count unexplained words anywhere on the page or only inside the table's area? -> A: Anywhere on the page, as the VRA script does. A page shared by several tables keeps the existing per-table band of spec 004.
- Q: Should the audit keep a row or cell whose values the text layer matches only in part (`fuzzy`)? A: Yes, and leave them to the recheck (decided after the live run, which rejected two correct rows for text-layer reasons). A value with no match at all is still refused.
- Q: Should cells of only dots or dashes be blanked (the third VRA change, and the earlier request to blank dash-only cells too)? A: No. Extract cell contents exactly and remove no character-only cells. That change is dropped from this spec.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Find rows and cells the model left out (Priority: P1)

A user extracts a table and wants to know that no row is missing. After the first pass, quotable
compares each table page's text layer with the extracted cells. If the page prints words that no
cell accounts for, quotable asks the model once to report only what it omitted. A proposed row or
cell is kept only if the text layer supports every value in it, exactly or in part; a partly
matched cell is flagged `fuzzy` and the recheck then corrects it. Kept rows and cells are marked as
added by the audit.

**Why this priority**: it closes the one gap grounding cannot: a dropped row leaves nothing to
check. Missing rows silently change counts and totals downstream.

**Independent Test**: run the pipeline with a fake model that drops one row from a page of the
synthetic fixture on its first answer and returns that row when audited. The row is back in the
table, in page order, marked `audit_added`, with grounding `exact`. A fake model that proposes a
row whose values are not on the page adds nothing.

**Acceptance Scenarios**:

1. **Given** a page whose text layer prints a row that the first pass omitted, **When** the audit
   runs, **Then** the model is asked once about that page and the row is added at its place on the
   page.
2. **Given** a page where every text-layer word is accounted for by a cell, **When** the audit
   runs, **Then** no audit request is made for that page.
3. **Given** a cell returned empty whose area on the page prints text, **When** the audit runs,
   **Then** the request names that cell, and a proposed value is filled in only if the text layer
   supports it.
4. **Given** the model proposes a row whose values are not all found in the page's text layer,
   or a row that repeats an existing row, **When** the audit judges it, **Then** the row is
   rejected and the table is unchanged.
5. **Given** `audit=False`, **When** the pipeline runs, **Then** no audit request is made and the
   audit changes nothing in the output or in any request.
6. **Given** a page shared by two tables, **When** the audit runs, **Then** each table is judged
   against its own band of the page only, and words of the other table never count as omissions.

---

### User Story 2 - Make small print readable to the model (Priority: P2)

A user whose documents have small print (dense tables, footnotes, narrow columns) gets sharper
images without doing anything. The pages that carry cell text are rendered at 300 dpi. For OpenAI
models they are sent at the highest image-detail setting. A user who needs the old behavior
passes `sharp_images=False`.

**Why this priority**: the user reports a significant improvement on tricky real-world cases, so
it is the default. It is not P1 because it improves reading quality and the audit adds a missing
check.

**Independent Test**: with `sharp_images=False`, every request is byte-identical to today's, so an
existing cache answers all of them. With it on and an OpenAI model, the extraction, recheck and
audit requests carry a 300-dpi image with detail `original`, and discovery requests are unchanged.

**Acceptance Scenarios**:

1. **Given** `sharp_images=False` and `audit=False`, **When** the pipeline runs against a cache
   filled by an earlier version, **Then** no request misses the cache.
2. **Given** sharp images are on and the model is an OpenAI model, **When** a page is extracted,
   rechecked or audited, **Then** the image sent is the page rendered at 300 dpi with detail
   `original`.
3. **Given** sharp images are on and the model is an Anthropic model, **When** a page is
   extracted, rechecked or audited, **Then** the image sent is the page rendered at 300 dpi and
   no detail value is relied on (Anthropic has no such setting).
4. **Given** sharp images are on and the model is from any other provider, **When** the pipeline
   runs, **Then** its requests are the same as with `sharp_images=False`.
5. **Given** a page so large that its 300-dpi image exceeds what the provider accepts,
   **When** the run starts, **Then** it stops with an `ExtractionError` that names the page and
   its size, before any model request is made.

---

### Edge Cases

- **A page number or running title is the only unexplained word.** The audit still sends the page
  (it cannot know). Words unexplained on many pages of one table are treated as page furniture and
  ignored, so repeated headers and footers do not cause requests. The number of requests this
  costs on a real document is unmeasured; see Success Criteria.
- **Cells of only dots or dashes stay as extracted.** They are not blanked. Dots and dashes carry
  no word tokens, so such a cell is neither an empty cell for the audit to fill nor an unexplained
  word. Grounding reports it as it does today.
- **The model reports a row that is a copy of an existing one.** Rejected, so a stuttering answer
  cannot duplicate rows.
- **The model reports a row between two existing rows, or before the first.** It is placed at that
  position. A position that does not exist is rejected.
- **The model's spelling is a little off the page's** (`Bennett` for `Bennet`). Words of five or
  more letters up to two letters off a page word are accepted for the check only. The model's
  spelling is kept, grounding flags it `fuzzy`, and the existing recheck corrects it. Numbers must
  match exactly.
- **OCR pages.** The audit uses the OCR'd text layer like every other step. Words OCR garbled show
  up as unexplained and may cost a request, but the confirmation rule still holds.
- **A table of one to four pages.** Furniture cannot be recognized from so few pages (it needs at
  least five), so every unexplained word counts.
- **Anthropic downscales.** Anthropic resizes any image above its model's limit (see Research
  notes), so on models before Claude 4.7 the extra pixels of a 300-dpi page are not read, and the
  cost is a larger upload. On Claude 4.7 and later the limit is higher and more of the page is read,
  at up to about 3 times the image tokens.
- **Image file size on Anthropic.** A 300-dpi PNG of a dense scan can approach Anthropic's image
  size limit (10 MB base64 on the Claude API, 5 MB on Amazon Bedrock). The up-front check covers
  pixel size only. A request the provider rejects fails loudly with the provider's error, as any
  request does.
- **The first run after upgrading.** With both on, extraction and recheck requests have new images
  and miss an existing cache, and audit requests are new, so the first run on a document already
  extracted pays for those again. Discovery requests still hit the cache.
- **The cap on new requests (`max_requests`).** Audit requests count. When the cap is reached the
  run raises `BudgetExceededError`, as for any request.
- **An unusable audit answer** (it fails the output schema after the library's own retries). The
  error is raised like any other request failure. A *valid* answer whose proposals are all
  rejected is not an error.

## Requirements *(mandatory)*

### Functional Requirements

**Omission audit**

- **FR-001**: `extract_tables` MUST accept a boolean `audit`, default `True`. With `audit=False`
  the pipeline MUST make no audit request, and the audit MUST change nothing in the output or in
  any other request.
- **FR-002**: For each page of each table, after the first-pass extraction (and its grounding) and
  before the final grounding of the table, the
  pipeline MUST count the page's *unexplained words*: words in the page's text layer whose tokens no
  extracted cell of that table accounts for, matched one cell token to one page token with the
  same tokenization grounding uses. On a page that holds one table that is every word on the page
  (page numbers, titles and footnotes included, so a row dropped at the top or bottom of the table
  is still found). On a page shared by several tables it is the words in that table's own band of
  the page (spec 004). A page with at least one unexplained word MUST be audited; a page with none
  MUST NOT.
- **FR-003**: A word unexplained on at least 30% of a table's pages MUST NOT count, when the table
  has at least five pages (page furniture such as a running header). Both numbers are the VRA
  script's and are fixed constants, not settings.
- **FR-004**: An audited page MUST cost at most one model request. The request carries the page
  image, the page's extracted rows (numbered from 1 in page order), the unexplained words (at most
  40, in reading order, each once), and the empty cells whose area on the page prints words (at
  most 40, each named by row number, column and the words printed there). It MUST tell the model
  that the words are a hint and not evidence, that the image is authoritative, that many pages
  have no omissions, and to report only omissions: missing rows (with the number of the row each
  one follows, 0 for before the first) and cells that are empty in the list but printed on the
  page.
- **FR-005**: The audit MUST NOT change or remove any value already extracted. It can only add rows
  and fill cells that were empty.
- **FR-006**: A proposed row MUST be kept only if all of these hold: its position exists; it is
  not a copy of an existing row (every non-empty cell of the proposal repeats the same cell of some
  row); every non-empty value is found in the page's text layer, either exactly or in part (an
  `exact` or `fuzzy` grounding; a value with no match, `ungrounded`, is refused), with the
  near-spelling allowance of FR-007; and at least one of its tokens is an unexplained word. A
  proposed cell MUST be kept only if its row exists, its column is one the page prints, the
  existing cell is empty, and it meets the same found-in-the-text-layer and unexplained-word
  conditions. Every other proposal MUST be rejected. A kept value that grounds `fuzzy` is flagged
  like any other `fuzzy` cell and goes to the recheck.
- **FR-007**: For the check only, a word of five or more letters may differ from a page word by up
  to two letters (insertions, deletions, substitutions or one adjacent swap), provided exactly one
  page word is that near, preferring one of the unexplained words. A token with a digit MUST match
  exactly. When accepted, the cell MUST keep the model's spelling, not the page's.
- **FR-008**: Kept rows MUST sit at their position on the page, and the page's rows MUST be
  numbered in page order afterwards (row numbers are positions, as everywhere in quotable). Later
  steps (grounding, position check, merge, recheck) MUST treat them like any other row.
- **FR-009**: Each table MUST report every audit proposal with its outcome (`accepted`, or the
  reason it was rejected) in `Table.audit`, the way `Table.proposals` reports the recheck.
- **FR-010**: `Table.records()` and the DataFrames MUST gain a column `audit_added`: `row` for a
  row the audit added, `cells: <columns>` for cells it filled, otherwise empty. The name follows
  the collision rule of spec 008 (a PDF column with the same name keeps its name; the library's
  column gets a trailing `_`). Existing columns and their order MUST NOT change.
- **FR-011**: Audit requests MUST go through the same client as every other request: they are
  cached, count toward `max_requests`, and are recorded in the cost log with stage `audit`.
- **FR-012**: A saved run (`.quotable/runs/`) MUST record the audit outcome of each table and the
  `audit` setting. Runs saved before this change MUST still load and show no audit marks. How the
  review app displays audit marks is not part of this spec.

**Sharp page images**

- **FR-020**: `extract_tables` MUST accept a boolean `sharp_images`, default `True`. With
  `sharp_images=False` every request MUST be identical to today's (150 dpi, detail `high`), so an
  existing cache still answers all of them.
- **FR-021**: With `sharp_images=True`, the images sent with the page extraction, the recheck and
  the audit MUST depend on the provider of the model:

  | Provider | Image | Detail sent | Up-front size check |
  | --- | --- | --- | --- |
  | OpenAI | page at 300 dpi | `original` | at most 30,000 patches of 32 px |
  | Anthropic | page at 300 dpi | none (Anthropic has no detail setting) | at most 8,000 px on each side |
  | Any other | as today (150 dpi) | as today (`high`) | none |

- **FR-022**: Schema/table discovery, the extra-field reads and the extra-field recheck and second
  look MUST keep 150 dpi and today's detail for every provider.
- **FR-023**: With `sharp_images=True` and a provider that has a size check, quotable MUST check
  every page's 300-dpi image against that limit before any model request, and raise
  `ExtractionError` naming the first page that exceeds it, its pixel size and the remedy (pass
  `sharp_images=False`). Nothing is sent for a document that fails this check.
- **FR-024**: The saved run MUST record the `sharp_images` setting.

**Cell contents**

- **FR-030**: This spec MUST NOT add any rewriting of cell values. A cell of only dots, ellipsis
  characters or dashes stays as the model transcribed it.

**Everywhere**

- **FR-040**: The README MUST document the audit; the `sharp_images` setting with the provider
  table of FR-021; a note that sharp images are **verified to work with OpenAI only**, that on
  Anthropic they are unverified and the provider downsizes large images (so the effect is
  unmeasured and image tokens can rise), and that other providers are unchanged; the first-run
  cache note; and that cells of only dots or dashes are kept as extracted. `AGENTS.md` MUST be
  updated in the same change (project state, file structure, the spec list).
- **FR-041**: Offline tests MUST cover every requirement above with fake clients and no network.
  Live checks (a real model) MUST be opt-in, in `tests/live/`, and are run only with the user's
  go-ahead.

### Key Entities

- **Unexplained word**: a word in a page's text layer (on a page shared by tables, in the table's
  band) that no extracted cell of that table accounts for. It is a reason to ask, never evidence of an omission by itself.
- **Audit proposal**: a row or a cell the model reports as omitted, with an outcome (`accepted` or
  a rejection reason) kept in `Table.audit`.
- **Page furniture**: a word unexplained on many pages of the same table (a running header or
  footer). It is ignored by the audit.
- **Sharp images**: a run-level setting that changes the resolution and, where the provider has
  one, the detail of the images sent with extraction, recheck and audit requests.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With `audit=False` and `sharp_images=False`, the offline test suite's outputs for
  every existing test are unchanged and an existing cache answers 100% of requests.
- **SC-002**: On the synthetic fixture, with a fake model that drops each page's last row on the
  first pass and returns it when audited, the audit restores 100% of the dropped rows and adds 0
  rows to pages where nothing was dropped.
- **SC-003**: For every proposal kept by the audit in any test, 100% of its non-empty values are
  found in the page's text layer (exactly or in part, or within the near-spelling allowance). No test finds a
  kept proposal that breaks FR-006.
- **SC-004**: With `sharp_images=True`, the offline tests show the image of each request stage and
  provider as FR-021 says: OpenAI 300 dpi with `original`, Anthropic 300 dpi, any other provider
  and every discovery request unchanged.
- **SC-005**: Before this spec is called done, a live run on a real multi-page document records,
  in this spec, the numbers that decide whether the defaults hold: pages audited out of pages,
  audit requests spent, rows and cells kept and rejected, and, for sharp images, the same pages
  with the setting off and on (flagged cells and tokens). No threshold is set in advance, because
  the VRA script recorded no measurements. The user's report of a significant improvement on
  tricky cases stands as the reason for the default; this run puts numbers on it.
- **SC-006**: A page too large for the provider at 300 dpi stops the run before the first request
  in 100% of cases (tested with a fake client that fails the test if asked).
- **SC-007**: A cell of only dots, ellipsis characters or dashes returned by a fake model appears
  unchanged in the final table.

## Research notes

How Anthropic handles page images (from [Anthropic's vision documentation](https://platform.claude.com/docs/en/build-with-claude/vision), read 2026-11-10; content rephrased):

- There is no per-image detail setting. The API scales an image down when it exceeds the model's
  limit: a long edge of 1,568 px and 1,568 image tokens for Claude models before 4.7, and 2,576 px
  and 4,784 tokens for Claude 4.7 and later, automatically.
- An image costs one token per 28 by 28 px patch, so a sharper page on a 4.7+ model can cost up to
  about three times the tokens of the same page at a lower resolution.
- Limits per image: 8,000 by 8,000 px, and 10 MB base64 (5 MB on Amazon Bedrock).
- pydantic-ai's Anthropic model does not read the `detail` value quotable sets on an image (it is
  read by the OpenAI, Groq, Mistral and xAI models), so it is ignored there.
- At 300 dpi a US Letter page is 2,550 by 3,300 px. On a model before 4.7 it is shrunk to about the
  size a 150-dpi render already has, so no extra text becomes readable. On 4.7 and later it is
  shrunk to fit the token cap, roughly 200 dpi, which is more than at 150 dpi.

How other providers handle it: pydantic-ai passes the `detail` value to OpenAI, Groq, Mistral and
xAI models unchanged. Only OpenAI's `original` value is documented to give the full resolution,
so quotable sends it only to OpenAI. Google's handling of the value quotable already sets is
unchecked and may be a separate problem (see Assumptions).

## Assumptions

- The name "goldlabel" in the request means quotable (see Clarifications).
- Row numbers stay positions within the page (`Row.row` is "1-based within the page"). VRA kept the
  old numbers and numbered added rows after the last one. quotable does not, because that would
  add a second numbering to the rows, records, frames, saved runs and the review app. The
  consequence: the audit being on by default can renumber the rows after an added one on a
  document already reviewed. A saved verdict is keyed by document, table columns, page, row and
  column, and a verdict whose extracted value no longer matches already shows as stale, so no
  verdict is applied to a wrong value silently.
- The audit runs before the final grounding. It needs row and column positions to name empty
  cells, which come from the position check; the plan decides how to get them for the first-pass
  rows without grounding more often than needed.
- The audit runs per table as discovery found it, before the merge step. A table that is later
  merged keeps the audit results of its parts.
- The constants (30%, five pages, 40 words, 40 cells, five letters, two edits, 300 dpi) are the
  VRA values. They are code constants, not settings, until a measurement shows they need to move.
- The provider is read from the model: the part of `provider:model-name` before the colon, or the
  `system` of a pydantic-ai `Model` instance. A model reached through a gateway (for example
  OpenRouter) counts as "any other" provider.
- The extra-field requests (discovery reads, recheck, second look) keep today's image, since they
  read short header values, not cells, and VRA did not change them.
- Anthropic gets 300 dpi, not a size fitted to its tier, to keep one rule and no per-model table.
  If the live run shows a cost problem on Claude 4.7 and later, a fitted size is the follow-up.
- quotable already sets `detail: high` on every image for every provider. Whether Google's model
  accepts that value was not checked here and is not changed by this spec.
- No gold-table scoring is added. Evidence that these changes help comes from SC-005's live run,
  not from a scorer.
- Cost log, saved runs, DataFrames and OCR keep their current behavior apart from the additions
  named above. Specs 001 to 013 are not rewritten.

## Live results (SC-005)

Run on 2026-11-10 with `just test-live tests/live/test_live_audit.py` and the model
`openai:gpt-5.6-luna` (the model the VRA script uses; the live test reads it from
`QUOTABLE_LIVE_TEST_MODEL`). The document is the 4-page sample `tests/data/fy22_ag_house_original.pdf`
(one table, 111 rows). The OpenAI key came from the project's `.env`. The cost figures are
quotable's own estimate from pydantic-ai's price data and have **not** been compared with the
provider's dashboard.

**Four settings on the whole document.** Runs with the same image setting share a cache, so each
audit row shows only the requests the audit added.

| Setting | New requests | Input tokens | Output tokens | Cost | Flagged cells |
| --- | --- | --- | --- | --- | --- |
| audit off, sharp off | discovery 1, extract 4, recheck 4 | 46,215 | 12,788 | $0.0268 | 59 |
| audit on, sharp off | audit 4 (added to the row above) | 20,338 | 1,241 | $0.0065 | 59 |
| audit off, sharp on | discovery 1, extract 4, recheck 4 | 105,748 | 9,864 | $0.0358 | 60 |
| audit on, sharp on | audit 4 (added to the row above) | 50,213 | 793 | $0.0135 | 60 |

- The audit sent a request for every one of the 4 pages, as expected with page numbers counting.
  It added 24% to the cost of the plain run and 38% to the cost of the sharp run. It found nothing
  to add, because nothing was omitted from this extraction.
- Sharp images used 2.3 times the input tokens and 0.77 times the output tokens, for 34% more cost
  in total. On this document they did not change the number of flagged cells (59 and 60). It is an
  easy document; the improvement on tricky pages reported by the user was not reproduced here.

**Omissions injected into a real extraction.** The test removed the last row of each page and
blanked one cell of the second row (8 omissions in all), then asked the real model through
`audit_table` with sharp images (4 audit requests, 50,359 input tokens, $0.0139):

| | Removed | Restored | Rejected |
| --- | --- | --- | --- |
| Rows | 4 | 2 | 2 (`ungrounded`) |
| Cells | 4 | 4 | 0 |

No wrong row or cell was added. The two rows that were not restored were correct rows, rejected
because the page's text layer disagrees with what is printed: one reads `$1.000.000` for the
amount `$1,000,000` (numbers must match exactly), the other splits `Administrator.` over two lines
as `Adminis-` / `trator.`, which grounds only `fuzzy`. In the original extraction the same cells
were `ungrounded` and `fuzzy`, so the recheck would have flagged them too. This is the rule of
FR-006 working as written: the audit's strictness costs recall on a document with a messy text
layer.

**After the run, the user decided to keep rows whose cells ground `fuzzy`** and leave them to the
recheck (FR-006 above is the changed text). Replaying the cached answers of the run above (no new
request) under the new rule restores 3 of the 4 rows, as before 4 of 4 cells, and adds nothing
wrong: the page-3 row comes back flagged `fuzzy`. The page-1 row is still refused, because its
`Account` and `Project` cells match nothing in that page's text layer (`ungrounded`), whatever the
amount reads; the recheck had flagged the same cells in the original extraction.

**Second live run, same day, after the change** (`tests/live/test_live_audit.py`, same model and
document). The four-setting test was answered entirely from the cache, so its numbers above stand.
The injection test now also runs the recheck on the audited table, with sharp images:

| | Result |
| --- | --- |
| Rows removed / restored by the audit | 4 / 3 (the fourth is refused, `ungrounded`) |
| Cells removed / restored | 4 / 4 |
| Status of the 3 added rows after the audit | `exact`, `fuzzy`, `exact` |
| Status after the recheck | `exact`, `fuzzy`, `exact` (no change) |
| Added rows whose values equal the removed row | 3 of 3 |
| Requests paid this run | recheck 4, audit 0 (answered from the cache) |
| Tokens and cost of those requests | 53,874 input, $0.0158 |

All three added rows carry the right values, and nothing wrong was added. The `fuzzy` one is the
page-3 row whose text layer splits `Administrator.` as `Adminis-` / `trator.`; the recheck copies
that reading back and cannot make it ground better, so the row stays flagged `fuzzy` for a human
to check. That is the outcome the change was meant to give: a correct row that is present and
marked for review, not a row that is missing.
