# 002 - Fixture: the `extra-*` documents and their checks

Spec: `../spec.md` (Requirements 19, 20; Synthetic fixture / `tests/synthetic_cases.py`; Tests /
Fixture). Depends on: task 001.

## Goal

The golden fixture holds a family of documents covering every scenario in the spec, tracked in git,
and an offline test verifies the fixture itself.

## Steps

1. `tests/synthetic_cases.py`: add a family `extra_fields()` to `all_docs()` with ids `extra-...`.
   One or more documents per scenario in the spec's list (1 to 12), including: sections of 1, 2, 3
   and 25 pages and the mix (1, 3, 1, 12, 2); pages before the first block; a block on a page with
   no table; a later block that changes one field; a later block that prints only one of two
   fields, generated twice (grouped: the other is cleared; ungrouped: it carries, marked
   `expect_stale`) plus a document with an ungrouped field that keeps carrying while its group
   clears; a repeated value in two sections; the Senate geometry; the `2018` number case with a
   decoy column named like a field; a wrapped value; a moved block and a right-aligned block
   (`expect_blind`); a continuation page with a table header row inside the block's region; the
   spec 007 reworded-header case; a caption that looks like a field but is not requested.
2. Tag every document with the scenario numbers it covers, in the truth, so a test can check that
   each scenario has a document.
3. Run `just synthetic`. New files are additions only; `git diff --stat tests/data/synthetic` must
   show no change to the 154 earlier files and `manifest.json` only gaining entries.
4. `tests/test_synthetic.py` gains the fixture checks of the spec: every printed value grounds
   `exact` at its recorded box (use the library's own tokenizer and `find_candidates` only to
   look the value up, not to define the truth); no block overlaps a table drawn on its page; every
   region-check bait (task 007) is declared in the truth; `expected` recomputed by an independent
   loop in the test equals the truth's; each scenario has a document (by tag); regenerating gives
   the same files (the existing "fresh run equals committed files" test must cover the new ones).
5. Update `tests/data/README.md` for the new family (what the documents are, the truth keys, the
   tags, `expect_stale` and `expect_blind`).
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The fixture has at least one document per scenario, the earlier 154 files are unchanged, the fixture
tests pass, and the checks are clean.
