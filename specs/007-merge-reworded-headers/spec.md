# 007 - Merge the parts of a table whose header is reworded

Status: draft; open questions resolved; tasks written (`tasks/001` to `007`), awaiting approval.
The golden fixture (`tests/data/synthetic/`) exists; no `src/` code yet.

## Summary

Discovery merges the pages of a table by comparing column names (case and punctuation
ignored). If a table's header is worded differently on later pages, for example "Requested Local
Match" on pages 1-3 and "Requested Match" on pages 7-9, the two parts are reported as two
`Table`s although they are one table. Each part is extracted and grounded correctly; only the
grouping is wrong.

This spec adds a consolidation step, after extraction and before the recheck, that joins two
`Table`s only when a set of independent checks all pass. Any doubt leaves them separate. It is
on by default, and a boolean argument, `merge_reworded`, turns it off.

Which checks are right is settled by testing, not by argument: a golden synthetic fixture (see
"Golden synthetic fixture") is built first, and the open rule and thresholds are chosen against
it.

## Motivation

Evidence from live runs of the real pipeline on synthetic PDFs (6 table pages, a gap of
table-free pages, 3 runs each, model `openai:gpt-6-luna`):

- The same header repeated after a gap, with only case/layout changed (CAPS, flattened onto one
  line), merges into one `Table` on 3 of 3 runs.
- A header with two columns reworded after the gap splits into two `Table`s on 3 of 3 runs. The
  split is deterministic: the model reports the headers as printed, the signatures differ, and
  nothing downstream joins them. Cell values were 100% exact on both halves.
- `discover.py` states this as a deliberate omission: "merging tables whose column names drift
  between pages beyond case and punctuation".

A split like this is not a data error, but the caller gets two tables to stitch together.

The risk in fixing it is the opposite error: joining two different tables. That is silent and
corrupts the output, so the design is built to refuse in every uncertain case. Note the
baseline: exact-signature merging already joins any two tables with identical column names,
whatever they are titled. The new rule needs more evidence than that, not less; its only extra
reach is names that differ in wording.

## Requirements

1. **Where it runs.** In `run_pipeline`, after every table has been extracted and grounded and
   before `recheck_table`. Its input is the list of `Table`s; its output is a list of `Table`s
   (shorter if merges happened). It makes no model request.
2. **Candidate pair.** Two tables A and B (A is the one whose first page is smaller) are a
   candidate pair only if every condition in 3-8 holds. A condition that cannot be evaluated
   (see 9) counts as failed.
3. **No shared page.** `set(A.pages) & set(B.pages)` is empty. Two tables on one page are
   different tables.
4. **Same column count.**
5. **Header compatibility, per position.** For each position i, let `a` and `b` be the token
   sets of A's and B's column name i (`gridkey.text.tokenize`, multi-level names `x.y` just
   contribute both parts' tokens). Position i is compatible when `a` and `b` are both non-empty
   and `a <= b` or `b <= a`. Every position must be compatible. No synonym lists, no fuzzy or
   embedding similarity. **Provisional (the "half-equal rule"):** in addition, at least half of
   the positions (rounded up) must have `a == b`. The user is not sure this rule is right. It
   stays in the first implementation only if the golden fixture shows it removes harmful merges
   without losing too many correct ones (see "Golden synthetic fixture / How rules are
   chosen"); otherwise it is dropped or replaced by what the fixture supports.
6. **No ambiguity inside the pair.** For every i != j, column i of A must not be compatible
   (per 5) with column j of B, and column j of A must not be compatible with column i of B.
7. **Same physical grid.** For each column, take the cells that are non-empty and grounded
   `exact` or `fuzzy` with a bounding box. A column's position on a side is the median of those
   cells' horizontal centres, over all of that side's pages. For every column the positions of
   A and B differ by at most `GRID_TOLERANCE` (initial value 10 pt; tuned by the negative tests,
   below). The order of the columns by position must also be the same on both sides.
8. **Same kind of value in every column.** For each column and side, classify the cells of 7 by
   shape: `currency`, `percent`, `integer`, `decimal`, `date`, `word` (one token, letters) or
   `text` (two or more tokens), plus a catch-all `other`. The dominant shape is the one holding
   at least 80% of the cells; with none at 80%, the column is unknown (see 9). The dominant
   shapes of A and B must be equal for every column.
9. **Unknown always means no merge** (decided by the user). A column that has fewer than
   `MIN_CELLS` (initial 5) qualifying cells (7) on either side, or no dominant shape (8), makes
   the pair fail. So does a table with no pages, or a column that is empty throughout.
10. **Mutual uniqueness.** Among all tables, A and B merge only if B is the only candidate pair
    partner of A and A the only one of B. If A has two candidate partners, none of those pairs
    merges. Candidate pairs are decided on the original tables, before any merge is applied.
11. **What a merge produces.** A single `Table` with:
    - `columns`: A's names, unchanged.
    - `pages`: both parts' `PageResult`s sorted by page number, B's row keys renamed to A's
      column names by position.
    - `layers`: the union of both (disjoint by 3). `layouts`: aligned to `pages`, with B's
      column names renamed the same way.
    - `grounded` and `position`: recomputed with `ground_document` on the merged pages and the
      renamed columns, so the position check covers the whole table.
    - `label` from A. `ocr_pages` the union.
    - a new field `merged: tuple[MergedPart, ...]` (empty for a table that was never merged),
      one entry per absorbed part, giving the absorbed pages, the column names that part had,
      and the evidence: per-position token sets, largest x difference, the shapes, the cell
      counts. This is the audit trail; callers can see what was joined and why.
12. **No change when nothing merges.** If no pair passes, the output is identical to today's.
    The existing offline tests pass unchanged.
13. **On by default, with an off switch.** `extract_tables` and `extract_tables_async` get a
    keyword-only `merge_reworded: bool = True` (name chosen by me; any name is cheap to change
    before implementation). With `False`, `merge_tables` is not called: the result is exactly
    what the pipeline returned before this spec, and every `Table.merged` is empty.
14. **Thresholds are module constants** (`GRID_TOLERANCE`, `MIN_CELLS`, `SHAPE_SHARE`) with the
    starting values below; the implementation tunes them against the golden fixture and records
    the final values and the evidence in this spec.

## Design

### Why after extraction

- Both halves have already extracted correctly, so merging only renames and concatenates; no
  extraction prompt depends on the decision, and nothing has to be redone if the decision is
  "no".
- Grounding keeps what the checks need. `FieldGrounding.bbox` is set for grounded cells
  (verified in `grounding.py`); it is `(x0, y0, x1, y1)` in points, from how `Layer.crop` uses
  it. Header-based x positions (`layout.find_header`) are a weaker source for multi-level
  headers, so they are not used.
- The merge acts on the final result type, so the recheck, which runs next, needs no change
  (to be confirmed in the implementation: `recheck.py` was not read for this spec).

### The checks together

No single check is enough. Header words can contain each other for different tables ("Amount"
inside "Requested Amount" and "Recommended Amount"); geometry can match for tables that share
a template; value shapes can match for any two money tables. The join needs all of: nothing
shared on a page, compatible and unambiguous words, the same grid, the same kinds of values,
and exactly one possible partner.

### Residual risk (accepted)

Two different tables on disjoint pages with the same column count, mostly equal header words,
header words in the rest contained in each other, the same grid within 10 pt, the same kinds of
values in every column and no other candidate would be joined. Example: "Name | Amount" and
"Name | Amount Awarded" in two sections printed on one template. The user accepts this risk
for now. The mitigations are the audit trail (11), which exists so the risk can be measured
while testing, and the off switch (13). A caller-supplied veto is not in this spec. The golden
fixture contains such cases on purpose (tag `residual_risk`) so the rate is known.

### Golden synthetic fixture

A deterministic generator makes PDFs with a real text layer plus the ground truth for each, so
every rule and threshold can be tested on documents where the right answer is known.

Where: `tests/synthetic.py` (renderer, data model, checks) and `tests/synthetic_cases.py` (the
case matrix); output goes to `tests/data/synthetic/` (`just synthetic`; tracked in git), one `<id>.pdf` and
`<id>.json` per case plus `manifest.json`. Seeds are derived from the case id, so regenerating
gives the same rows and the same text layer; the PDF files are byte-identical too (the random
file ID MuPDF writes is replaced by a fixed one).

Each case is a document of parts (tables), gaps (prose or look-alike pages) and optionally
stacked parts (two tables on one page). For each pair of parts the truth file says:

- `same_table`: whether the two parts really are one table (`true`, `false`, or `null` when
  it is a judgement call).
- `expect_merge`: what the spec requires of the merge step: `true` or `false` when the answer
  is settled by the requirements, `null` when it depends on a rule or threshold still being
  decided (the half-equal rule, the tolerance band, the alignment cases).
- `probes`: the rule(s) the case exercises (`half_equal`, `token_containment`, `ambiguity`,
  `shared_page`, `count`, `order`, `grid`, `tolerance_band`, `alignment`, `min_cells`, `shape`,
  `unique`, `residual_risk`, `known_limit`).
- `stage`: `merge` (the pair reaches `merge_tables`) or `discovery` (the headers already match
  and discovery joins them; controls).
- `names_check`: computed at generation time: column count, number of positions with equal
  token sets, whether every position is compatible, whether any cross-position pair is
  compatible, and whether the signatures already match. A case that is meant to isolate one
  rule is generated only if the other header rules pass.

The truth file also has, per part, the pages, the header names as discovery would report them,
and every row's values per page (the rows a perfect model would extract).

Families (a parameter sweep for each rule, positive and negative):

- Half-equal sweep: 5 schemas (3, 4, 6, 8 and 10 columns), k = 1..n columns reworded (by adding
  or dropping a word), first-k and last-k. Only the half-equal rule can decide these.
- Word order only ("Amount Requested" vs "Requested Amount"): equal token sets.
- Grid: whole-table shifts of 0 to 40 pt (both directions) and a single column drifting; the
  band around the tolerance is `expect_merge: null`.
- Alignment and font: numeric columns right- vs left-aligned, font 8 vs 9.5 vs 11.
- Cells: 2 to 20 rows per part, asymmetric sizes, and a sparse column with 0 to 10 values.
- Value shape: the share of the dominant kind from 100% down to 50% (80% boundary exactly),
  asymmetric shares, and a column whose kind changes between parts.
- Structure: shared page, extra and dropped column, swapped column order, abbreviation and
  disjoint rewording (known limits), ambiguous bare "Amount", three parts with one wording and
  with two, interleaved tables, two different tables on one template.
- Residual risk: different tables whose headers are contained in each other and whose grid and
  shapes match, with and without a shifted grid.
- Pipeline: gaps of 0, 1, 4, 9 and 20 pages, exact and reworded headers, header-less
  continuation, for the live test.
- Controls: single table, exact repeat, case-only drift, two unrelated tables.

#### How rules are chosen

The fixture is scored by running each candidate rule set over the `stage: merge` pairs:

1. **Harmful merges** (a merge where `same_table` is `false`) are counted first. Outside the
   cases tagged `residual_risk`, the target is zero, and any rule variant that produces one is
   rejected.
2. **Required results:** every `expect_merge` that is `true` or `false` must come out as
   stated, for every variant.
3. **Missed merges** (no merge where `same_table` is `true`) are then counted and the variants
   compared. A rule that removes no harmful merge but misses more is dropped.
4. The half-equal rule is kept, changed or dropped on this score. The result and the final
   threshold values are written back into this spec.

### Module and code

New `src/gridkey/merge.py`: `merge_tables(tables: list[Table]) -> list[Table]` plus small pure
functions for each check (`compatible`, `grid_positions`, `dominant_shape`, `candidate`). `Table`
gets the `merged` field and `MergedPart` is defined next to it in `table.py`. `extract.py`
calls `merge_tables` before the recheck. The `discover.py` docstring line about drift is
updated to point here.

### Alternatives considered

- **A looser rule at discovery** (merge by token subset when the prompt's known-tables list
  matches). Rejected: at that point only the model's header words exist, and nothing
  independent can veto.
- **Ask the model whether two tables are the same.** Rejected as approval: non-deterministic,
  and one answer would be the only thing between a wrong merge and the output. It could be a
  veto only; not needed here.
- **Fuzzy or embedding header similarity, or synonym lists.** Rejected: no strict guarantee.
- **Merge when the geometry matches alone.** Rejected: tables from one template share a grid.

## Out of scope

- Differently worded headers that are not token-contained ("Amount" vs "Funding").
- Different column counts (a column added or dropped after the gap).
- Merging more than two parts when any part has two candidate partners (it refuses).
- Page orientation, scans of different sizes, and tables whose pages have different widths.
- A caller-supplied veto (a function the caller passes to refuse a particular merge). The
  boolean `merge_reworded` is in scope.

## Tests

Deterministic logic is tested offline, on real text layers (small PDFs generated with pymupdf
at test time), not with a scripted model standing in for the model. Model behaviour is checked
with the live test only.

Offline, one or more tests for each of:

- The checks as pure functions: token compatibility (subset, equal, disjoint, empty), the
  half-equal rule, cross-compatibility, grid positions and tolerance edge, shape classification
  and the 80% rule, `MIN_CELLS` edge.
- Must merge: the reworded two-column case; "Amount Requested" vs "Requested Amount".
- Must not merge (one test each): shared page; different column count; headers contained but
  fewer than half equal; the ambiguous bare "Amount" with both "Requested Amount" and
  "Recommended Amount"; same words, different grid (shifted by more than the tolerance);
  compatible headers but different value shapes; too few cells; no dominant shape; three
  mutually compatible tables; the interleaved table A / table B / table A case.
- A merged table's rows, `layouts`, `position` and `merged` audit entry; renamed keys; page
  order; a document where nothing merges returns the same tables as today.
- The existing suite passes unchanged.
- `merge_reworded=False` returns exactly what the pipeline returned before this spec, and
  `Table.merged` is empty; the default is `True`.
- Fixture integrity (offline): every truth row of the committed fixture grounds `exact`
  against its page's text layer; every document passes the text-layer check; each
  `names_check` matches the header names; regenerating into a temporary directory gives the
  same truth files and text layers as the committed ones; each probe tag has cases on both
  sides of its rule.

Live (opt-in, costs money, only with the user's go-ahead): the "Pipeline" family of the golden
fixture, plus the earlier ad-hoc cases (`caps_reworded` must now come back as one `Table`;
`multilevel_gap`, `headerless_long_gap`, `caps_flat_drift`, `interleaved_two_tables`,
`lookalike_prose_gap`, `long_gap_20` must be unchanged), 3 runs each.

## Docs

`README.md` ("Not handled" and any "Not carried over" mention; the `merge_reworded` argument and
the `merged` field), `AGENTS.md` (project state, file tree: `merge.py`, `tests/synthetic.py`,
`tests/synthetic_cases.py`, `tests/data/synthetic/`; the `just synthetic` command),
`discover.py` docstring, spec 005's argument list (a pointer to the new argument).

## Open questions

1. Resolved (user): on by default, not opt-in (requirement 13).
2. Resolved (user): unknown (too few cells) always means no merge (requirement 9).
3. Resolved (user): the half-equal rule is provisional. It stays or goes on the golden fixture's
   evidence (requirement 5, "How rules are chosen").
4. Resolved (user): `GRID_TOLERANCE` 10 pt, `MIN_CELLS` 5 and the 80% shape share are the
   starting values; tuning them against the fixture is part of the implementation (requirement
   14).
5. Resolved (user): the residual risk is accepted for now, with the `merged` audit field to
   measure it while testing.
6. Resolved (user): a boolean off switch is wanted (requirement 13). The name `merge_reworded`
   is my pick.
7. Resolved (user): work in the repo now. Branch `spec/007-merge-reworded-headers` opened from
   `main` (clean tree, spec 006 committed); this file is `specs/007-merge-reworded-headers/spec.md`.
8. Resolved (user): the generated fixture (`tests/data/synthetic/`, PDFs and truth files) is
   tracked in git like any other test fixture; it is not git-ignored. The generator and
   `just synthetic` stay so it can be regenerated, and a test checks that regenerating gives
   the same truth and text layers as the committed files.
