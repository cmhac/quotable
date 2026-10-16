# 010 - Extra fields: values read from outside the tables and added as columns

Status: draft, open questions to resolve (see the end)

## Summary

Some PDFs print information that applies to a page, and often to the pages after it, outside
any table: a title, a year, an appropriation name. The Senate sample
(`tests/data/senate_expenditures_paddleocr.pdf`) prints `APPROPRIATIONS`, `Funding Year 2018`
and `SALARIES, OFFICERS AND EMPLOYEES, SENATE` at the top left of page 1 only; pages 2 and 3
continue the same table with no such block. The full report repeats that block every time the
section changes, and a section can be one page or fifty.

This spec lets the caller name extra fields to read ("extra fields"), asks the model for them in
the same request that already finds the tables (discovery), checks every value against the
text layer like any other extracted text, carries a value forward to the pages that do not
print it (off by default, `carry_forward=True` turns it on), and adds the fields to every row of every table:

```python
from quotable import ExtraField, ExtraFields, FieldGroup, extract_tables

tables = extract_tables(
    "senate.pdf",
    "openai:<model-name>",
    extra_fields=ExtraFields(
        fields=[
            FieldGroup(
                "header",
                "The block at the top left of the first page of each section; its other pages omit it.",
                fields=[
                    ExtraField("appropriation", "The appropriation title, in capitals"),
                    ExtraField("funding_year", "The year printed after 'Funding Year'"),
                ],
            ),
            ExtraField("report_date", "The date the report was run, printed on page 1 only"),
        ],
        prompt="A section runs from one page to about fifty.",
        carry_forward=True,  # the default is False: pages that print no header stay empty
    ),
)
# columns: page, row, <table columns>, appropriation, funding_year, report_date, ...
df = tables[0].to_pandas()
```

Without `extra_fields` nothing changes: same requests, same cache keys, same output.

## Motivation

- The values that say what a table is about (which fund, which year) are often not in the table.
  Today they are lost, or the caller reads them by hand and joins them back.
- The library's stance is that nothing is trusted until the text layer agrees. Extra fields are
  held to the same rule as every other extracted value (requirements 8 and 17).
- Carrying a value forward is a decision about pages that print nothing, so it cannot be checked
  against those pages' text directly. The risk is a header the model misses: every following page
  would silently get the previous section's value. Section length does not matter, whether
  zero, one or fifty pages follow a header; what matters is whether each page is read right.
  The design therefore treats a missed header as the failure to protect against (requirements 11
  and 12).

## What was measured on the sample

Read-only checks on `senate_expenditures_paddleocr.pdf` (text-layer coordinates, points):

- All three header values are in page 1's text layer, outside both tables: `SALARIES, OFFICERS
  AND EMPLOYEES, SENATE` at x 40-201, y 99-106; `Funding Year 2018` at x 40-102, y 85-93;
  `APPROPRIATIONS` (a label) at x 40-98, y 54-60. Pages 2 and 3 contain none of it.
- The value `2018` alone has **5 exact matches** on page 1 (four are dates in the summary table),
  so grounding says "exact" but cannot say which one is the field. Requirement 8 picks it.
- The detail table on pages 2 and 3 starts at the top of the page, so its rows (payee names at
  x 166-217, y 94-113) sit **inside the area where page 1 printed the appropriation title**. A
  check that only asked "is there text where the header was?" would fire on both continuation
  pages. Requirement 11 removes the table's own band from that check.

## Requirements

### API

1. **Three frozen dataclasses**, exported from `quotable` (`__all__`):
   - `ExtraField(name, description)`: one value to read.
   - `FieldGroup(name, description, fields)`: fields that are printed together in one block, with
     a description of the block (where it is, when it appears) that goes to the model. `fields` is
     a list of `ExtraField`.
   - `ExtraFields(fields, prompt="", carry_forward=False)`: the whole request. `fields` is a list
     whose items are `ExtraField` or `FieldGroup`, so a field can sit in a group or on its own.
   `extract_tables` and `extract_tables_async` take `extra_fields: ExtraFields | None = None`.
   A group has no column of its own and does not appear in the output (decision).
2. **Validation happens before any request.** The list must hold at least one field; every item
   must be an `ExtraField` or `FieldGroup` (a group inside a group is a `TypeError`). Each field
   `name` must be non-empty after stripping, and field names must be unique after stripping across
   the whole request, grouped or not. Each field `description` must be non-empty. Each group needs
   a non-empty `name` and `description`, at least one field, and a name unique among groups (a
   group with a single field is allowed and clears nothing). Otherwise `ValueError` (the same kind
   of error as `discovery_pages < 1`). Columns are ordered as the fields appear in the list, groups
   flattened in place. `prompt` is free text for the caller's document-specific guidance (where
   the blocks are, how far they apply); it may be empty.
3. **Nothing changes without `extra_fields`.** The discovery request is the same object as
   today (same instructions, same output schema, same parts), so its cache key is unchanged
   and existing caches are reused. A test pins this (see Tests).

### Reading the fields in discovery

4. **One request per window, as now.** With `extra_fields`, the discovery request also asks for
   the fields. The window size (`discovery_pages`) is unchanged. The answer has, for each page
   image, the page's tables as today and an `extras` list with one entry per requested field:
   `{name, value}` where `value` is the text exactly as printed on **that page**, or `null` if
   that page does not print it. Output models are in `models.py`: `ExtraValue`, and a page entry
   and window entry that extend `PageTables` and `WindowTables` (used only when extra fields are
   requested).
5. **The prompt.** `DISCOVER_PROMPT` tells the model to ignore page titles and section captions;
   with extra fields, a paragraph says that the fields below are exactly such text and are to be
   reported, not ignored, and that: each page is judged on its own; a field is reported only if
   it is printed on that page, never inferred from another page in the window or from the
   known tables; a value is copied verbatim (no reformatting); a field not printed on the page is
   `null`; values printed inside a table's cells are not extra fields unless the description says
   so. The text then lists each field (`name: description`) and appends `ExtraFields.prompt`.
   A group is listed with its name and description and its fields indented under it, and the
   paragraph says that a group is one block printed together: its fields are reported as printed
   on this page, each `null` if absent, and the group is not itself reported. The output schema
   does not change with groups (still a flat list of `{name, value}`), only the prompt does.
6. **No state between windows.** `CARRY_PROMPT` lists the tables found so far; it does not list
   field values. A wrong answer for one window cannot reach the next.
7. **Answer checks.** The answer must have one entry per page (as now) and, in each, exactly the
   requested names, each once. A mismatch is sent back once with the problems named, together
   with any page-count problem in the same retry; a second failure raises `ExtractionError`
   (the rule of `discover._ask_window`). An empty string value counts as `null`.

### Checking, with the text layer

8. **Grounding.** Each non-null value is looked up in the whole text layer of its page
   (`grounding.find_candidates`, not a table band: the block is outside the tables), giving
   `exact`, `fuzzy`, `ungrounded` or `untokenized`, the same statuses and the same coverage
   figure as a table cell. Pages whose layer came from OCR are grounded against the OCR text, as
   everything is. A field with no value (nothing printed yet, see requirement 10) has status
   `empty`, as an empty cell does. The position check (a value must sit in its own row and
   column) does not apply, because an extra field has no row or column, so the status
   `misplaced` never occurs for one. If a value has several candidates (the `2018` above), the
   one nearest to the centre of the fields that have exactly one candidate on that page is the
   field's place; if no field on the page is unambiguous, the page gives no place for that field.
   The place (a bounding box) is kept for requirement 11.
9. **Recheck.** With `recheck=True` (the default), values graded `fuzzy` or `ungrounded` get one
   second look per printing page, like table cells (spec 002): the page image, the page's whole
   text layer, and the flagged fields; the model is told the text layer is the reference. An
   answer is kept only if grounding of that field gets strictly better (`SEVERITY`). This matters
   more than for a table cell, because one wrong header value repeats on every row of its
   section. `recheck=False` turns this off.

### Carrying forward

10. **The rule.** With `carry_forward=True` (not the default), pages are walked in document order, all
    pages, including pages that hold no table. For each field separately, a page that prints a
    value (after requirements 8, 9, 11 and 12) uses it; a page that prints none takes the value of the
    nearest earlier page that printed one; before the first printed value the field is missing.
    The value carries with its grounding status and coverage. A field is never carried backwards.
    **Groups.** On a page where at least one field of a group is printed with grounding `exact`
    or `fuzzy` (after requirements 8, 9, 11 and 12), every other field of that group that the page
    does not print is cleared on that page: it is missing there, and stays missing on the
    following pages until one prints it. On a page that prints no field of a group, the group's
    fields carry as usual. A value graded `ungrounded` or `untokenized` is that field's value on
    its page but does not trigger clearing, so a misread or invented value cannot wipe its
    siblings. A field outside any group is never cleared by other fields. Because requirement 11
    runs first, a sibling that the model left null but whose spot holds text gets its second look
    before it is cleared. With `carry_forward=False` (the default), a page that prints no value
    has none, and groups have no effect (an unprinted field is already empty on that page). The
    default was chosen by the user: a caller gets exactly what each page prints unless they ask
    for the carry, so a table of the Senate sample's pages 2 and 3 has empty fields without it.
11. **Missed-header check.** For each field, the region where the field is printed is the union
    of its places (requirement 8) over all pages that printed it, plus 6 pt on every side. For a
    page where a field is null, the words of the page's text layer whose centre is inside that
    region, **minus words inside any table's band on that page**, are the evidence of a header the
    model missed. A table's band is located with `regions.locate` from the first and last row text
    that discovery already reports; if a table's rows cannot be located, no words are removed
    for it (this errs towards a false alarm, never towards a miss). A field with no place on any
    page has no region and is not checked.
12. **Second look at suspect pages.** For each page with evidence (requirement 11), one request
    per page: the page image, the fields in question, and the words found in the region, asking
    whether any of those fields is printed on this page. An answer value that grounds (`exact` or
    `fuzzy`) makes the page a printing page for that field; anything else is discarded and the
    page stays unprinted. So a noisy check costs requests, and never changes a value by itself.
    These requests go through the same client and cache and count against `max_requests`. The
    check and the second look run whenever extra fields are requested, whatever `carry_forward`
    says (decision: with carry off they still recover values the model missed; `carry_forward`
    only decides whether values are copied to later pages).
13. **Order.** Discovery, grounding, field recheck, region check, second look, then the carry
    rule, then the fields are attached to the tables.

### Output

14. **Per table and per row.** `Table.extra_fields: dict[int, dict[str, ExtraResult]]` maps each
    of the table's pages to its field results, and every `Row` has `Row.extra: dict[str,
    ExtraResult]` with its page's results. `ExtraResult` has `value` (string, `""` if missing),
    `source_page` (the page that printed it; `None` if missing) and `grounding` (a
    `FieldGrounding` of the printing page; status `empty` if missing). A table of several pages,
    or one made by the spec 007 merge, has an entry for each of its pages; a page shared by two
    tables gives both the same entry (the Senate summary and detail tables both get the year).
15. **`records()` and the frames.** After the table's own value columns, one column per field
    named as the caller named it; then, after the per-column `__grounding` and `__coverage`
    columns of the table's own columns, for each field `<name>__grounding`, `<name>__coverage`
    and `<name>__source_page` (integer; null if missing, `Int64` in pandas). Column order:
    `page`, `row`, values, field values, per-value grounding and coverage, per-field grounding,
    coverage and source page, `grounding_status`, `recheck_changes`. `to_pandas()` and
    `to_polars()` follow `records()` as in spec 008; field values are strings, coverage is float.
16. **Names.** Extends spec 008 requirement 9: PDF columns are never renamed; then the field
    columns, in the caller's names, with a trailing `_` appended until free if a PDF column has
    that name; then the library's own columns, which take a trailing `_` when taken (a field
    called `page` keeps its name and the page number becomes `page_`). Nothing raises. Without
    `extra_fields`, every name is as today.
17. **Grounded like any other text.** Extra fields take part wherever grounded text does:
    `Row.status` and the `grounding_status` column are the worst status over the row's cells and
    its extra fields; `Table.flagged()` lists a flag for an extra field on every row that carries
    the value (so filtering rows by flag works as for cells); a field flag is marked as such, and
    the existing cell recheck ignores it because the field has its own recheck (requirement 9).
    An accepted change of a field value appears in `recheck_changes` of each row that carries it,
    as `<name>: "old" -> "new"`. Table cells, their position check and the merge step are
    otherwise unchanged.
18. **Logging.** The number of fields read, pages carried, suspect pages and second-look
    requests is logged at INFO under the `quotable` logger.

### Tests and fixture (required)

19. **Synthetic fixture.** The generator (`tests/synthetic.py`, `tests/synthetic_cases.py`) is
    extended to draw header blocks, and a new family of documents with truth files covers the
    scenarios below. The fixture is tracked in git; `just synthetic` regenerates it. The 154
    existing files are byte-identical after the change (the drawing code is reached only by
    documents that ask for a block). Details under Synthetic fixture.
20. **Offline tests** drive the pipeline with fake clients (code logic only; no test claims
    anything about model behaviour), including the verification of the fixture itself.
21. **Live tests** with a real model measure behaviour: no regression of table discovery with
    extra fields on, and the accuracy of reading and carrying. They cost money and run only with
    the user's go-ahead. Details under Tests.

## Design

### Code

- `src/quotable/extra_fields.py` (new): `ExtraField`, `FieldGroup`, `ExtraFields`, `ExtraResult`;
  `validate_extra_fields` and a `flatten` that returns the fields in column order with their
  group; the prompt text (requirement 5); grounding and place selection (8);
  region and suspect-page detection (11); `propagate` (10), a pure function over the per-page
  printed values; `attach` (14). The functions are separate so each is tested alone.
- `models.py`: `ExtraValue`, the extras-bearing page and window models, the second-look answer,
  and the field recheck answer.
- `discover.py`: `discover(images, client, *, discovery_pages, extra_fields)` returns a
  `Discovery` (`tables: list[Found]` and `extras: dict[int, dict[str, str | None]]`); with
  `extra_fields=None` it behaves, and builds its requests, as today. `_ask_window` builds the
  extra-fields prompt and checks the field names in the same retry as the page count. Callers and
  tests are updated.
- `extract.py`: the new argument on `extract_tables_async`, `extract_tables` and `run_pipeline`;
  the steps of requirement 13 around the existing ones, using the layers from `usable_layers`
  (so OCR'd text is used where it replaced the text layer).
- `table.py`: `Table.extra_fields`, `Row.extra`, `ExtraResult`, the extra columns in
  `records()`, the frames, `output_names`, and `Row.status` / `flagged()` (requirements 14-17).
  `Flag` gains a marker for extra-field flags.
- `recheck.py`: a small function for fields next to `recheck_table`, sharing `RECHECK_PROMPT`'s
  rule that the text layer wins and the strictly-better acceptance test; `recheck_table` skips
  the extra-field flags.
- `llm.py`: stages `"extras"` (second look) and `"recheck"` reuse `Request`; no protocol change.
- Docs: `README.md` (usage, columns, limits), `AGENTS.md` (project state, file tree, test
  count, the new `just` recipe).

### Why in discovery

Discovery already shows the model every page and returns one entry per page, which is exactly
what per-page fields need; a separate pass would send every page image a second time. The cost
is a larger prompt and answer on discovery, and a risk that asking for more worsens the table
answers. The live regression check (below) is how that risk is measured, and with `extra_fields`
unset the request does not change at all.

### Why the carry is checked this way

The model's `null` is the only evidence for "this page prints no header", and a missed header
is the one failure that corrupts data silently (an invented value is caught by grounding). The
text layer can speak to it: a header printed on another page sits in the same place on this
one, so words in that place that are not table rows are a reason to ask again. The check is a
trigger for a focused question, not a decision, so its false alarms cost a request and its
misses are bounded to cases where a header sits somewhere else on the page. Its false-alarm and
miss rates are measured on the fixture (offline) and with a real model (live) before the result
is called good.

### Alternatives considered

- **A separate pass for fields.** Rejected (decision): doubles the image tokens.
- **Carry the known values into the next window's prompt, as `CARRY_PROMPT` does for tables.**
  Rejected: sequential, and one wrong window would taint every later one.
- **Carry forward outside the library (forward-fill the frame).** That is the unchecked version
  of the same rule; the library has the layout evidence to check it.
- **No carry-forward switch.** Rejected: the switch exists and the default is off, so a caller
  sees exactly what the model read page by page unless they ask for `carry_forward=True`.
- **Fail or drop a carried value when the check fires.** Rejected: the check is noisy by
  construction; asking the model once more turns noise into cost, not into wrong or missing data.
- **Count pages or use a fixed span.** Not possible: sections run from one page to fifty.

## Not handled (listed in the README)

- A header that starts a new section halfway down a page: scope is per page, so rows below the
  new header get the old value.
- A header that clears a field by leaving it out, for a field that is in no group: it keeps the
  old value. Put fields that are printed together in a `FieldGroup` to get the clearing.
- A new section with no printed marker at all.
- A header printed at a different place on different pages: the region check does not see it;
  only the model's own reading does (right-aligned or centred values of changing length fall in
  this group).
- Fields that depend on a table's rows (a per-row value): that is a table column.
- Documents where pages are not in reading order.

## Synthetic fixture

The generator draws, on a chosen page, a header block (a label line and value lines at a fixed
top-left place, like the Senate sample) and records it. All existing parameters keep their
defaults, so existing documents are rendered by exactly the same calls.

- `tests/synthetic.py`: a `HeaderBlock` (label and value for each field, position, font,
  alignment, whether a value wraps over two lines); `Part` and `Gap` gain an optional
  `blocks` (page index within the item -> block) and `table_top_after_block` (a table that
  shares a page with a block starts below it, as in the sample; on pages without one it starts at
  the usual top, which puts its rows where the block was printed on other pages). `render` adds to
  the truth, only for documents with a block: `extra_fields.fields`, `extra_fields.printed`
  (page -> name -> value or null, exactly as printed), `extra_fields.expected` (page -> name ->
  value and source page after carrying, with `null` for missing), and `extra_fields.boxes`
  (the drawn box of each printed value).
- `tests/synthetic_cases.py`: a family `extra_fields()` added to `all_docs()`, ids `extra-...`.
  Scenarios, each with at least one document:
  1. sections of 1, 2, 3 and 25 pages, alone and mixed in one document (1, 3, 1, 12, 2);
  2. pages before the first block (expected: missing);
  3. a block on a page with no table, followed by table pages;
  4. two fields where a later block changes only one (the other is printed again, same value) and
     where a later block prints only one of the two. The second case is generated twice: once
     with both fields in a `FieldGroup` (the other is cleared) and once with the two fields
     ungrouped (the other carries: the documented limitation, marked `expect_stale` in the truth
     so tests and scoring show it on purpose). The truth records the grouping each document is
     expected under, and a third document has a field outside the group that must keep
     carrying while the group clears;
  5. the same value printed in two consecutive sections (`source_page` differs);
  6. the Senate geometry: summary and detail tables on the block's page, and continuation
     pages whose rows sit where the block was (the region check must not fire);
  7. a value that is also a number in a table (the `2018` case) and a column in the table named
     like a field (a decoy);
  8. a value that wraps over two lines;
  9. a block that moves to another place on a later page, and a right-aligned block (documented
     blind spots: the truth marks them `expect_blind`);
  10. a continuation page with a table header row inside the block's region (the region check
      fires; the second look is expected to find nothing);
  11. a document with the spec 007 reworded headers and extra fields (fields attach by page, not
      by table);
  12. a caption that looks like a field but is not requested (must not be read as one).
- `just synthetic` writes them with the rest. `just score-extra-fields` (new recipe,
  `tests/score_extra_fields.py`, no model, no cost) builds a fake discovery answer from each
  truth, injects named faults (a missed header, an invented value, a misread value, a value placed
  on the wrong page), runs the library's checks and prints per scenario: labels right, missed
  headers caught by the region check, false alarms, second looks needed. The numbers are recorded
  in this spec when the work is done.

## Tests

Offline, new files `tests/test_extra_fields.py`, `tests/test_extra_fields_pipeline.py` and
additions to `tests/test_synthetic.py`, `tests/test_discover.py`, `tests/test_frames.py`:

- Validation: empty fields, blank or duplicate names (also across a group and an ungrouped
  field), blank descriptions, an empty group, a blank or duplicate group name all raise
  `ValueError`, and a group inside a group raises `TypeError`, before any request is made (the fake
  client saw none). Mixed lists keep their order in the columns.
- Unchanged without fields: the discovery `Request` for a document is identical to today's
  (instructions, output type `WindowTables`, parts), and `request_key` equals the key computed
  from the same request built by the pre-change code path.
- Prompt: fields, descriptions and the caller's text are in it; known-table text never contains
  a field value (requirement 6); a wrong name set is retried once together with a page-count
  problem, and a second failure raises `ExtractionError`.
- `propagate`: a table of cases covering sections of 0, 1 and many continuation pages, leading
  missing pages, a table-less page that prints, independent fields, a repeated value, and
  `carry_forward=False`; and for groups: a block that prints one of two fields clears the other,
  a page that prints none leaves the group carrying, an ungrounded value does not clear its
  siblings, an ungrouped field is not cleared, a group of one field clears nothing, and a sibling
  whose spot holds text gets its second look before being cleared.
- Prompt with groups: a group's name, description and indented fields are in the prompt, the
  output schema (and so the request's output type) is the same as without groups.
- Grounding and place selection: the `2018` case picks the nearest candidate; no unambiguous
  field gives no place; a fuzzy and an ungrounded value are graded as table cells are and are
  carried with their status; a missing value is `empty`.
- Region check: on the Senate sample (recorded rows, with a fake discovery answer that reads the
  block on page 1 only) no second look is requested for pages 2 and 3; with the band exclusion
  removed (a test-only switch) both pages would be suspect; a faked missed header on a page
  of a fixture document is caught.
- Second look: a grounded answer makes the page a printing page and changes the carried values
  after it; an ungrounded or null answer changes nothing; `max_requests` counts it.
- Grounded like any text: an ungrounded field value makes `Row.status` and `grounding_status` of
  every row that carries it `ungrounded`, shows in `flagged()` on those rows, and the cell recheck
  does not touch it; the field recheck is accepted only if it grounds strictly better and shows
  in `recheck_changes`.
- Output: `Row.extra`, column order and names, the collision rule (a field named like a PDF
  column, a field named `page`), dtypes in pandas and polars (nullable integer source page),
  tables sharing a page, merged tables, a table with no rows.
- Fixture: for every `extra-*` document, every printed value grounds `exact` at its recorded
  box; no block overlaps a table drawn on its page; every region-check bait is declared in the
  truth; `expected` recomputed by an independent loop in the test equals the truth's; each
  scenario above has a document (checked by tag); regenerating gives the same files; the 154
  earlier files are unchanged (`git diff --stat tests/data/synthetic` shows additions only).
- `just check` passes; the test count in `AGENTS.md` is updated.

Live, new `tests/live/test_live_extra_fields.py` (cost: money; needs `OPENAI_API_KEY` and
`QUOTABLE_LIVE_TEST_MODEL`; never run without the user's go-ahead), three runs each in separate
cache directories, as in `test_live_merge.py`:

- **Regression:** for the Senate sample and a chosen set of the spec 007 documents, discovery with
  and without `extra_fields` gives the same tables: same columns, same pages, same rows after
  extraction (recall against the truth as in `test_live_merge.py`). Any difference is a finding
  to report, not a test to loosen.
- **Accuracy on the fixture:** for the `extra-*` documents, per page and field: printed value
  equals the truth, carried value and `source_page` equal the truth, no missed header remains after
  the second look, no invented value; the blind-spot and stale documents are reported separately,
  not asserted. Reported numbers: missed headers before and after the region check, false alarms,
  second-look requests per 100 pages.
- **Real document slice:** a slice of 60 consecutive pages of the full report, from a path in
  `QUOTABLE_LIVE_EXTRA_PDF`, with the pages that truly start a section known from the text
  layer (the pages whose layer contains a given label, in `QUOTABLE_LIVE_EXTRA_LABEL`). It
  reports the same numbers on real data. The file is not committed.

## Docs

`README.md`: usage, the added columns, the carry rule and its switch, the region check in two
sentences, "Not handled". `AGENTS.md`: project state, file tree (`extra_fields.py`,
`score_extra_fields.py`), the recipe, the test count. Status set to implemented only after the
user approves the change.

## Offline scoring

`just score-extra-fields` (`tests/score_extra_fields.py`; a fake model answering from the truth
files, one injected fault at a time, the second look and the recheck answered faithfully, so it
measures the library's checks and says nothing about any real model). Documents marked
`expect_stale` or `expect_blind` are left out. Run on the 17 other `extra-*` documents, with
`carry_forward=True` and the groups of each truth file:

| Fault | Runs | Right | Wrong but flagged | Wrong and silent | Missed headers caught | False-alarm second looks | Second looks per 100 pages |
|---|---|---|---|---|---|---|---|
| none (faithful model) | 17 | 17 | 0 | 0 | - | 4 | 4.0 |
| a block missed, another page prints the same fields | 13 | 13 | 0 | 0 | 13 of 13 | 0 | 9.6 |
| a block missed, a field printed nowhere else | 13 | 0 | 0 | 13 | 2 (of 13) | 0 | 3.0 |
| a value invented on a page that prints none | 16 | 0 | 16 | 0 | - | 3 | 4.0 |
| a block value misread (one character) | 26 | 26 | 0 | 0 | - | 4 | 3.0 |
| a block value reported one page early | 8 | 0 | 8 | 0 | - | 0 | 10.1 |

What the numbers say. A missed header is recovered every time the check has a place to look
(the field is printed on another page); when a field is printed nowhere else the check has no
region and the header stays missing, silently: this is the design limit named under "Not
handled", not a defect to tune away. An invented or misplaced value is never silent: it is
`ungrounded`, so it shows in `flagged()`, on every row that carries it (it is not removed, and
with the carry it is carried until the next block). A one-character misread is corrected by the
field recheck. The four false-alarm second looks of a faithful model are on three documents:
`extra-header-in-region` (built to cause them: a table header printed where the block was; pages
2 and 3) and the two group documents, where a later block drops a line and the line above or
below it, 12 pt away, falls inside the dropped field's region (page 4). Each costs one request and
changes nothing. The second-look
rate depends on the fixture's mix of documents and says nothing about a real report: the live run
measures that.

## Open questions

Settled by the user: the name "extra fields"; fields are on every `Row` and in every output;
fields are grounded like any other text; the column suffix `__source_page`; a 60-page slice of
the real document for the live check; the missed-header check and its second look run whether
carry-forward is on or off; carry-forward is off by default (`carry_forward=False`), so tests and
live runs that rely on the carry set `carry_forward=True` explicitly; fields that are printed together are declared with a `FieldGroup`
(own name and description, fields inside it), which also clears the group's other fields when a
new block omits one.

None are open. Choices the draft made on its own, to be confirmed or changed at review:

1. A `FieldGroup` description is required (it is what tells the model about the block).
2. A group does not appear in the output (no column, no `ExtraResult` field); groups cannot
   be nested.
3. Only a field graded `exact` or `fuzzy` triggers clearing of its group's other fields.
