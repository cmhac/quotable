# Contract: what a user of quotable sees change

## `extract_tables` and `extract_tables_async`

Two new keyword-only arguments; everything else is as before.

```python
extract_tables(
    pdf, model, *,
    ...,
    recheck: bool = True,
    audit: bool = True,          # new
    sharp_images: bool = True,   # new
    ...
)
```

| Argument | `True` (default) | `False` |
| --- | --- | --- |
| `audit` | pages with words that no cell accounts for go back to the model once; proposals the text layer confirms are added | no audit request; nothing else about the output changes |
| `sharp_images` | extraction, recheck and audit use the provider's sharp image (table below) | requests are identical to the version before this change |

| Provider (from the model string or `Model.system`) | Image for extraction, recheck, audit | Up-front size check |
| --- | --- | --- |
| `openai`, `openai-chat`, `openai-responses` | 300 dpi, detail `original` | at most 30,000 patches of 32 px |
| `anthropic` | 300 dpi (detail not used by Anthropic) | at most 8,000 px on each side |
| anything else | 150 dpi, detail `high` (unchanged) | none |

Errors:

- `ExtractionError` before any model request when `sharp_images=True` and a page's image would
  exceed the check. The message names the page, its size in pixels and says to pass
  `sharp_images=False`.
- `BudgetExceededError` counts audit requests like any other new request.

## `Table`

- `Table.audit: list[AuditItem]`, empty when nothing was audited. `AuditItem` has `page`, `kind`
  (`"row"` or `"cell"`), `values`, `outcome`, `row` (see `data-model.md`).
- `Table.records()` and `to_pandas()` / `to_polars()`: one more column, last, named `audit_added`
  (a PDF column of that name keeps it; the library's gets `_`). Values `"row"`,
  `"cells: <columns>"` or `""`. No other column or order changes.
- `Row.row` is still the 1-based position in the page. An added row shifts the rows after it.

## Saved runs (`.quotable/runs/<id>/`)

- `run.json` `settings` gains `audit` and `sharp_images`.
- `tables.json` tables gain `audit`.
- Version stays 1. A run saved before this change opens and has no `audit` entries.

## Cost log

- Requests of the new step are recorded with `stage` `audit`. `quotable cost-report` sums them
  with the rest.

## Model request of the new step (`stage == "audit"`)

- Instructions: the audit prompt (see `research.md`, entry 5).
- Output type: `Omissions`.
- Parts, in order: the numbered column structure, the page image, one text part with the listed
  rows, the unexplained words (at most 40) and the empty-cell hints (at most 40).
- Cached, counted and priced like every other request.

## Not changed

- Prompts, images and cache keys of schema discovery, extra-field reads, the extra-field recheck
  and the second look.
- Any cell value: no cleaning of dots or dashes (FR-030).
