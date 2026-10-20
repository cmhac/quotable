# 004 - One page-rendering setting

Spec: `../spec.md` (Requirement 5; Design step 4). Depends on: task 003.

## Goal

`steps/recheck.py` renders pages with `render_png` from `steps/extract.py` instead of its own
`dpi=150`, so the two cannot drift apart. The PNG bytes, and so the cache keys, do not change.

## Steps

1. In `quotable/steps/recheck.py`, `recheck_table`: replace
   `document[n - 1].get_pixmap(dpi=150).tobytes("png")` with `render_png(document[n - 1])`, and
   import `render_png` from `quotable.steps.extract`. Check there is no import cycle
   (`steps/extract.py` must not import `steps/recheck.py`).
2. `grep -n "get_pixmap" quotable` : the remaining hits are `render_png` and `ocr/pages.py`
   (which renders at the OCR config's own `dpi`, a different setting; leave it).
3. `just check`. Do not commit unless the user asks.

## Acceptance

- `grep -rn "dpi=150" quotable` finds nothing.
- Before and after the edit, the PNG bytes for one page of `tests/data/fy22_ag_house_original.pdf`
  are identical (`hashlib.sha256` of `render_png(page)` equals that of the old expression run on
  the same page); report both hashes.
- `tests/test_recheck.py` and `tests/test_extra_fields_recheck.py` pass unchanged, including any
  fixed request keys.
- `just check` passes with the baseline count.
- No live or OCR test was run.
