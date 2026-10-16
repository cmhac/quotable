# 006 - The carry rule and groups (`propagate`)

Spec: `../spec.md` (Requirement 10; Design / Code: `propagate`). Depends on: tasks 003 and 005
(task 001 for the oracle in the fixture tests).

## Goal

A pure function turns the per-page printed values into the value each page ends up with, including
group clearing, and is tested alone.

## Steps

1. `propagate(pages, flattened_fields, carry_forward)` in `extra_fields.py`, pure (no I/O, no
   model): input is, for every page in document order (all pages, including pages with no table),
   the printed `ExtraResult` or `None` per field; output is the per-page, per-field `ExtraResult`
   with `source_page` set.
2. `carry_forward=False` (the default): a page that prints no value has none (missing); groups
   have no effect.
3. `carry_forward=True`: a page that prints a value uses it; a page that prints none takes the
   nearest earlier printed value with its grounding and coverage; before the first printed value
   the field is missing; never backwards.
4. Groups: on a page where at least one field of a group is printed with grounding `exact` or
   `fuzzy`, every other field of that group not printed on that page is cleared on that page and
   stays missing until a page prints it. A page that prints no field of the group carries as
   usual. An `ungrounded` or `untokenized` value is that field's value but does not trigger
   clearing. A field in no group is never cleared by other fields. A group of one field clears
   nothing.
5. Tests in `tests/test_extra_fields.py`, as a table of cases: sections of 0, 1 and many
   continuation pages; leading missing pages; a table-less page that prints; independent fields; a
   repeated value (new `source_page`); `carry_forward=False`; every group rule above. Add a test
   that runs `propagate` over each `extra-*` fixture document (printed values from the truth) and
   equals the truth's `expected` (the generator's independent loop is the oracle).
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

All cases pass and `propagate` agrees with the fixture's `expected` for every document, with
`expect_stale` and `expect_blind` documents compared under the grouping their truth declares.
