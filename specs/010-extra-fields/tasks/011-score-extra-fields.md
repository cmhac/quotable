# 011 - Offline fault-injection scoring: `just score-extra-fields`

Spec: `../spec.md` (Synthetic fixture, last bullet). Depends on: tasks 002, 006, 007 and 010.

## Goal

A no-model, no-cost command measures how the checks behave on the fixture under injected faults,
and the numbers are on record in the spec.

## Steps

1. Read `tests/score_merge.py` and the `score-merge` recipe in the `justfile` first; copy their
   shape.
2. New `tests/score_extra_fields.py`: build a fake discovery answer from each `extra-*` truth,
   inject named faults one at a time (a missed header, an invented value, a misread value, a value
   placed on the wrong page), run the library's checks, and print per scenario: values right, missed
   headers caught by the region check, false alarms, second looks needed.
3. Add the `score-extra-fields` recipe to the `justfile` and to the commands table in `AGENTS.md`.
4. Run it and record the numbers in the spec, in a new "Offline scoring" section, with the date and
   the commit.
5. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

`just score-extra-fields` runs without a model or network, and its numbers are in the spec.
