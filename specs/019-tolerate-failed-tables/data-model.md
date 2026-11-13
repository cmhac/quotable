# Data Model: A table that fails validation no longer stops the run

Spec: [spec.md](spec.md). Plan: [plan.md](plan.md). Everything here is internal except what [contracts/public-api.md](contracts/public-api.md) lists.

## Problem (new, public)

A frozen dataclass in `quotable/table.py`.

| Field | Type | Meaning |
|---|---|---|
| `stage` | `Literal["discovery", "extraction", "location"]` | which check found it |
| `pages` | `tuple[int, ...]` | the pages it concerns, 1-based, in order; never empty |
| `message` | `str` | a sentence a person can act on; no prompt, no extracted value, no path |

Rules: `message` names the table's label when the problem is about the table and not one page. Two problems with the same stage and message are one problem with the pages joined.

## Table (changed, public)

New field, last in the dataclass so every existing construction still works:

| Field | Type | Meaning |
|---|---|---|
| `problems` | `list[Problem]` (default empty) | what failed; empty for a sound table |

New property `failed -> bool`: `bool(self.problems)`.

What a failed table holds, by where it failed:

| Failed in | `columns` | `pages` (extracted) | `label` | `problems` |
|---|---|---|---|---|
| discovery (unusable columns after the retry) | what the model gave (maybe empty) | none | the model's label | one `discovery` problem, pages = the pages the table was reported on |
| location (row not found, overlap) | the discovered columns | none | the label | one `location` problem per page |
| extraction (rows invalid after the retry) | the discovered columns | the pages that did extract | the label | one `extraction` problem listing the pages that did not |

A failed table that extracted pages has their `layers`, `grounded` and `position` as a sound one does; the others have empty dicts. Later stages never add `proposals`, `audit`, `merged` or `extra_fields` to it.

State of a table through a run:

```text
found by discovery ──► sound ──► located ──► extracted (every page) ──► audited, extra fields, merged, rechecked
        │                  │            │
        │ unusable         │ not found  │ rows invalid
        ▼                  ▼ / overlap  ▼ after retry
   failed(discovery)   failed(location)  failed(extraction)   ← skipped by every later stage
```

A table never leaves "failed". A table that fails at one stage is not looked at by the next.

## Found (changed, internal, `steps/discover.py`)

| Change | Meaning |
|---|---|
| `problems: list[str]` | the unusable-schema problems for this discovered table; empty when sound |
| `failed` (property) | `bool(problems)` |
| signature of a failed `Found` | `("failed", label)`; never equal to a sound table's signature, so a failed entry is grouped only with entries of the same label |

`known_tables(found)` skips failed entries. `validate_found(found)` still raises when `found` is empty ("no table found in the document") and no longer raises for a table's columns.

`Discovery.tables` holds sound and failed entries in order of first appearance. The pipeline splits them.

## TableFailedWarning (new, public)

`class TableFailedWarning(UserWarning)` in `quotable/errors.py`. Emitted at a failure and on each read of a failed table's data. Text: [contracts/messages.md](contracts/messages.md).

## BandError (new, internal)

`class BandError(ExtractionError)` in `steps/layout.py` with `labels: tuple[str, ...]` (the tables at fault) and `page: int`. Other callers of `table_layers` see an `ExtractionError` as before.

## Request (changed, internal, `llm/client.py`)

Three optional fields after `page`, none part of `request_key`:

| Field | Type | Meaning |
|---|---|---|
| `pages` | `tuple[int, ...]` (default empty) | the pages the request covers; discovery sets all of its window's pages |
| `retry_of` | `str | None` | the key of the request this one retries |
| `problem` | `str | None` | what was wrong with the answer that caused the retry |

## Cache entry (changed, internal)

The answer's own JSON fields plus one key, `_quotable`. See [contracts/stored-files.md](contracts/stored-files.md).

## Saved run (changed, internal)

`tables.json` tables and `run.json` summary gain `failed` and `problems`. See [contracts/stored-files.md](contracts/stored-files.md). `RunTable` in `runs.py` gets `failed: bool = False` and `problems: list[...] = []`.

## What does not change

`PageResult`, `Row`, `Flag`, `Proposal`, `AuditItem`, `MergedPart`, `OcrConfig`, the answer models in `llm/answers.py`, every prompt, every request key.
