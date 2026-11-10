# Data model: omission audit and sharp page images

Only what is new or changes. Names are those the code will use; fields without a note are
required.

## `ImagePolicy` (new, `quotable/llm/images.py`, internal)

A frozen dataclass: how a page image is made for the stages that read cell text.

| Field | Meaning |
| --- | --- |
| `dpi: int` | Resolution the page is rendered at |
| `detail: str` | Value set on the image (`high`, or `original` for OpenAI) |
| `max_patches: int \| None` | Largest image in 32 px patches the provider accepts; `None` = no check |
| `max_side: int \| None` | Largest side in pixels; `None` = no check |

- `TODAY = ImagePolicy(150, "high", None, None)`.
- `policy_for(model, sharp) -> ImagePolicy`: `TODAY` when `sharp` is false or the provider is not
  OpenAI or Anthropic; OpenAI `(300, "original", 30_000, None)`; Anthropic `(300, "high", None, 8_000)`.
- `check_page_sizes(pdf, policy)`: raises `ExtractionError` for the first page over a limit.

Validation: none beyond the limits above. No state.

## `Image` (changed, `quotable/llm/client.py`)

Adds `detail: str = "high"`. Existing `Image(png)` calls are unchanged. `request_key` adds the
detail to the image's fingerprint only when it is not `"high"`.

## Audit answer (new, `quotable/llm/answers.py`)

| Model | Fields |
| --- | --- |
| `MissingRow` | `after_row: int` (number of the listed row it follows, 0 = before the first); `values: dict[str, str]` (column name to value as printed) |
| `FilledCell` | `row: int` (number as listed, from 1); `column: str`; `value: str` |
| `Omissions` | `missing_rows: list[MissingRow]`; `filled_cells: list[FilledCell]` |

## `AuditItem` (new, `quotable/table.py`)

One audit proposal and what became of it, the audit's counterpart of `Proposal`.

| Field | Meaning |
| --- | --- |
| `page: int` | Page the proposal is about |
| `kind: Literal["row", "cell"]` | A missing row, or a value for an empty cell |
| `values: dict[str, str]` | A row: every column of the proposal. A cell: one entry, column to value |
| `outcome: str` | `accepted`, or why not: `invalid_row`, `invalid_cell`, `duplicate`, `not_empty`, `repeated`, `ungrounded`, `no_evidence`, `empty` |
| `row: int \| None = None` | Only when accepted: the 1-based row number in the final page (after the audit renumbered) |

`values` holds the model's spelling. For a rejected proposal `row` is `None`.

## `Table` (changed, `quotable/table.py`)

Adds `audit: list[AuditItem]` (default empty), next to `proposals`. A table that had no audit
(`audit=False`, or no page with unexplained words) has `audit == []`. `merge_pair` carries
`[*a.audit, *b.audit]`.

Derived, for `records()`:

- a row is "added" if an accepted `kind == "row"` item has its `(page, row)`;
- cells are "filled" if accepted `kind == "cell"` items have its `(page, row)`; the columns are
  listed in column order.

## `OutputNames` (changed)

Adds `audit: str`, `audit_added` made collision-safe by the same `free()` as its neighbours, after
`changes`. `records()`, `_frame_columns()` and the DataFrames append the column last, kind `str`:

| Value | When |
| --- | --- |
| `"row"` | an added row |
| `"cells: <a>, <b>"` | cells filled, columns in the table's order |
| `""` | otherwise |

A row cannot be both: a filled cell is on a listed row, an added row is new.

## Pipeline arguments

| Where | New argument | Default |
| --- | --- | --- |
| `extract_tables`, `extract_tables_async` | `audit: bool` | `True` |
| `extract_tables`, `extract_tables_async` | `sharp_images: bool` | `True` |
| `run_pipeline` (internal) | `audit: bool` | `False` |
| `run_pipeline` (internal) | `images: ImagePolicy` | `TODAY` |
| `extract_page` | `detail: str` | `"high"` |
| `recheck_table` | `images: ImagePolicy` | `TODAY` |
| `render_png` | `dpi: int` | `150` (`DPI`) |

## Saved run (`quotable/runs.py`)

- `RunInfo` gains `audit: bool` and `sharp_images: bool`; `_settings()` writes both into
  `run.json` `settings`. For a run read back, `settings` is the stored JSON as it is today (a run
  saved before this change simply has no such keys).
- Each table in `tables.json` gains `"audit"`: a list of `{page, kind, values, outcome, row}`.
- `RunTable` gains `audit: list[dict[str, Any]]`; `_run_table` reads it with `data.get("audit", [])`.
- `FORMAT_VERSION` stays 1.

## Cost log

No change to the format. A record's `stage` can now be `audit`; `storage.CostRecord.stage`'s
comment lists it.

## State transitions

The audit does not add a state machine. For one page: `listed rows` → (audit request) →
`accepted proposals applied` → `rows renumbered by position` → `table grounded again`. A page with
no accepted proposal keeps its object as it was.
