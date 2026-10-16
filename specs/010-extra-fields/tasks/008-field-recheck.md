# 008 - Recheck of fuzzy and ungrounded field values

Spec: `../spec.md` (Requirement 9; Design / Code: `recheck.py`). Depends on: task 005.

## Goal

A field value that grounds `fuzzy` or `ungrounded` gets one second look, and is replaced only if the
answer grounds strictly better.

## Steps

1. Read `recheck.py` (`recheck_table`, the prompt, the acceptance test) and spec 002 first.
2. Add a function next to `recheck_table` for fields: one request per printing page with flagged
   fields (page image, the page's whole text layer, the flagged fields), telling the model that the
   text layer is the reference. Reuse the existing prompt rule and the strictly-better comparison
   through `SEVERITY`; do not duplicate them. New answer model in `models.py`.
3. It is skipped when `recheck=False`.
4. Return the accepted changes (field, page, old, new) so task 009 can show them in
   `recheck_changes`.
5. Tests (fake client): a better answer is accepted; an equal or worse one is not; an answer that
   leaves the field `ungrounded` keeps the old value; `recheck=False` makes no request; one request
   per printing page, not per field.
6. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The tests pass and the existing recheck tests pass unchanged.
