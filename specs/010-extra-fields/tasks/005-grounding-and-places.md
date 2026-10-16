# 005 - Ground the field values and find their place

Spec: `../spec.md` (Requirement 8; Design / Code: `ground_fields`). Depends on: task 003.

## Goal

Each value read from a page is graded against that page's whole text layer, and its place (a
bounding box) is known for the region check.

## Steps

1. Read `grounding.py` (`find_candidates`, `SEVERITY`, `UNFLAGGED`, the status names and the
   coverage figure) and `text.py` (`Layer`, `bbox`) first. Reuse the statuses and the coverage
   rule; do not invent new ones.
2. In `extra_fields.py` add `FieldGrounding` (status, coverage, place) and `ExtraResult(value,
   source_page, grounding)` as in requirement 14. `extra_fields.py` must not import `table.py`
   (task 009 makes `table.py` import it).
3. `ground_fields(layer, values)`: for each non-null value, look it up in the whole layer (no table
   band) and grade it `exact`, `fuzzy`, `ungrounded` or `untokenized`. A missing value is `empty`.
   Never produce `misplaced`.
4. Place selection: with several candidates (the `2018` case), pick the candidate nearest the centre
   of the page's fields that have exactly one candidate; if no field on the page is unambiguous,
   the place is `None`. A field with one candidate takes it.
5. Tests in `tests/test_extra_fields.py`, on small hand-made layers and on the Senate sample's
   page 1 (the three values and the `2018` with five matches; the expected x/y ranges are in the
   spec's measurements): the nearest candidate wins; no unambiguous field gives no place; fuzzy and
   ungrounded are graded as table cells are; a missing value is `empty`; `misplaced` never occurs.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The Senate page 1 values ground `exact` with the `2018` placed in the title block, and the checks
are clean.
