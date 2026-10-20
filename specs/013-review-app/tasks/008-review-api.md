# 008 - The review API: queue, verdicts, drafts, statistics

Spec: `../spec.md` (Requirements D1 to D9, E, F1 to F5). Depends on: tasks 004, 005 and 007.

## Endpoints

- `GET /api/queue?<QueueSettings>`: the D1 counts per status, the matching count, the
  suggested sample size, the queue (one entry per item: run, table, page, row, column or extra
  field, status, review state for the progress strip and its hover text), the index of the
  first unreviewed item, and the statistics of section E.
- `POST /api/verdicts`: body `{key, run, verdict, value, category, note, queue}`; validated
  with `validate` (task 004); the extracted value and status are read from the run on the
  server, never taken from the body; appended; the draft cleared; returns the saved verdict
  and the next unreviewed item of the queue.
- `PUT /api/drafts` (a `POST` to `/api/drafts` if `PUT` complicates the handler) with
  `{key, note, value, category}`; returns `saved_at`. `DELETE` is not needed: saving a verdict
  clears the draft.

## Steps

1. Red first: tests in `tests/review/test_review_api.py` on the project of task 007.
2. `quotable/review/review.py`: the functions behind the endpoints, wired into the route table.
3. Tests: a verdict saved through the API is in `verdicts.jsonl` with every F2 field and the
   queue settings; a forged `value` in the body is ignored; `changed` without a category or
   with the same value is 400 with the message; a 5,001-character note is 400; a verdict on a
   re-run with the same value counts as reviewed, with another value as stale (D8); the queue
   of the same settings and seed is the same in two requests; statistics change after a
   verdict; drafts round trip and are cleared by a verdict; a failed append (monkeypatch) is a
   500 with a message and nothing half-written.
4. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The review flow works end to end over HTTP, and verdicts can be rebuilt into the statistics
from `verdicts.jsonl` alone.
