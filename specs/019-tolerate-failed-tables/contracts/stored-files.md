# Contract: stored files

Two files gain keys. Both changes are additive: a reader that does not know the key ignores it, and a reader of the new version supplies a default when the key is missing. Constitution IV: no migration is needed. Spec: [../spec.md](../spec.md).

## 1. Request cache entry (Story 6)

Where: `<cache dir>/<request key>.json`. The name is unchanged.

Before: the answer's own fields.

```json
{
 "pages": [
  { "tables": [ { "label": "Investment Account #6 transactions", "columns": [], "first_row": "…", "last_row": "…" } ] }
 ]
}
```

After: the same fields, plus `_quotable`:

```json
{
 "pages": [ "…as before…" ],
 "_quotable": {
  "stage": "schema",
  "pages": [357, 358, 359, 360],
  "model": "openai:gpt-5.6-luna:{}",
  "written": "2026-11-13T15:04:05Z",
  "run": "3f6c…32 hex characters",
  "retry_of": "9be2…64 hex characters",
  "problem": "page 357, table 'Investment Account #6 transactions': … no columns …"
 }
}
```

| Key | Always present | Meaning |
|---|---|---|
| `stage` | yes | `schema`, `extract`, `audit`, `recheck` or `extras` (the request's `stage`) |
| `pages` | yes (may be empty) | the pages the request covered, 1-based |
| `model` | yes | the client's `identity` (model name and settings), as in the key |
| `written` | yes | UTC time the entry was written, `YYYY-MM-DDTHH:MM:SSZ` |
| `run` | yes (may be `null`) | the run id the cost log uses; `null` when the client was built without one |
| `retry_of` | only for a retry | the request key of the request it retried |
| `problem` | only for a retry | what was wrong with the earlier answer |

Rules:

- The answer's own fields keep their names and values. `_quotable` is never an answer field; no answer model has a field of that name.
- Reading: `output_type.model_validate` on the whole file, as today. Pydantic ignores `_quotable` (no answer model forbids extra keys).
- An entry written by an earlier version has no `_quotable`. It is read and used, and never rewritten to add one.
- Not stored: prompts, images, file paths, credentials, extracted values beyond the answer itself.
- A failure to build the details (an unexpected request) must not stop the entry from being written without them.

## 2. Saved run (`.quotable/runs/<id>/`; FR-011)

`FORMAT_VERSION` stays 1.

`run.json` `summary` gains `failed` (number of failed tables, default 0). Each entry of `run.json` `tables` and of `tables.json` `tables` gains:

| Key | Meaning |
|---|---|
| `failed` | `true` for a failed table; absent means `false` |
| `problems` | list of `{"stage": str, "pages": [int, ...], "message": str}`; absent means `[]` |

A failed table's other keys keep their meaning, with empty values where the table holds nothing (`columns: []`, `pages: []`, `rows: 0`).

Reading: a run saved before this feature has neither key and loads as not failed. A run saved by this version and read by an older one: the older reader ignores the keys (it reads the tables as it did; a failed table with no pages shows as an empty table).
