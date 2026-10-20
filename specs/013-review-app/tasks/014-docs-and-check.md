# 014 - Docs and final check

Spec: `../spec.md`. Depends on: tasks 001 to 013.

## Steps

1. README: a "Reviewing the results" section: every run is saved to `.quotable/runs/`,
   `quotable review` (options, local only, what it writes), the review flow in a few lines, the
   statistics in one paragraph, where verdicts are and that they are audit only, that the PDF
   is not copied, how to delete runs. Update the `.quotable/` layout listing (cache, cost, runs,
   review). Remove anything the spec makes untrue.
2. AGENTS.md: project state (spec 013 implemented, what was not checked on real hardware or
   browsers), the file structure (`quotable/runs.py`, `quotable/review/` with its modules and
   `static/`, `tests/review/`, `tests/review_demo.py`), the `just review-demo` recipe in the
   commands table, and the `quotable review` command next to `quotable cost-report`.
3. Spec status line: implemented.
4. `just check`; a last browser pass over `just review-demo` covering every board, in Chrome
   and Firefox (the PDF viewer differs between them).

## Done when

Docs describe what was built, `just check` passes, and the browser pass found nothing left to
fix.
