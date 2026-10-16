# 003 - Score the rules on the golden fixture and settle them

Spec: `../spec.md` (Requirements 5 and 14; Golden synthetic fixture / How rules are chosen).
Depends on: task 002.

## Goal

The half-equal rule is kept, changed or dropped, and `GRID_TOLERANCE`, `MIN_CELLS` and
`SHAPE_SHARE` get their final values, on the evidence of the 154 fixture documents. The result
is written back into the spec. No model is involved.

## Steps

1. `tests/fixture_tables.py`: build the `Table`s of a fixture document without a model. For each
   part in the truth file: `PageResult`s from `rows`, the columns from the part's `columns`
   (the header as discovery would report it), the real text layer of each page
   (`gridkey.text.load_layer` on the fixture PDF), then `ground_document` for `grounded` and
   `position`. A part on a page shared with another part (the `Stack` cases) gets its band of
   the layer the way `table_page_layers` does (read `regions.py`); if that cannot be rebuilt
   without a model, build the stacked cases' layers by cropping to the truth rows' own cells and
   record that in the module docstring. Use the same code in the pipeline where possible
   rather than copying it.
2. `tests/score_merge.py` (run as `python -m tests.score_merge`, recipe `just score-merge`):
   for each candidate `Rules` (the half-equal rule on and off, a replacement such as "at least
   one equal position" or "at least a third", `grid_tolerance` in {5, 8, 10, 12, 15, 20},
   `min_cells` in {3, 4, 5, 6, 8}, `shape_share` in {0.7, 0.75, 0.8, 0.9}), run `pair_verdict`
   over every relation with `stage == "merge"` and print:
   - harmful merges (merged, `same_table` false), split into the `residual_risk` cases and the
     rest;
   - required results broken (`expect_merge` true or false and the verdict disagrees);
   - missed merges (not merged, `same_table` true), by probe tag;
   - the per-probe breakdown for the `expect_merge: null` cases, so the effect of each rule can
     be read off.
   One sweep varies one setting at a time from the defaults, then a small grid over the settings
   that interact (the half-equal rule with the tolerance). Output is plain text, sorted so the
   best variant is on top by the order in the spec (harmful, then required, then missed).
3. Tests (`tests/test_fixture_tables.py`): every part of every fixture document builds a
   `Table` whose `position` has no `wrong`-column counts and whose cells ground `exact` (these
   are the truth rows against their own PDFs; the generator already guarantees it, this checks
   that this module reads them back correctly); the stacked cases get only their own band.
4. Run the sweep. Decide, in this order, applying the spec's scoring rules:
   - any variant with a harmful merge outside `residual_risk` is rejected;
   - every `true`/`false` `expect_merge` must hold, else the variant is rejected, and a case
     that no variant can satisfy is reported as a fixture or spec error to fix, not tuned
     around;
   - among what is left, fewest missed merges wins; ties go to the stricter variant.
   Also report how many `residual_risk` pairs merge under the chosen rules (the accepted
   residual risk, measured).
5. Write the outcome into `../spec.md`: replace "provisional" in Requirement 5 with the decision
   and the rule as chosen, set the three constants in Requirement 14 and the Design text, and
   add a short "Results on the golden fixture" section with the table of numbers above for the
   chosen variant and for the main rejected ones. If the half-equal rule is dropped or
   replaced, update Requirement 5, the Tests list and the `names_check` description. Do this
   edit only after the sweep; if the evidence is mixed (two variants tie, or a threshold sits
   on a cliff the fixture cannot place), say so in the spec and in the report, and ask the user
   before choosing.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

`just score-merge` reproduces the table in the spec; the chosen rules have zero harmful merges
outside `residual_risk` and break no required result; the spec records the decision and its
evidence; the user has seen the numbers (this task ends with a report, because it is the one
place the spec's open design choice is closed).
