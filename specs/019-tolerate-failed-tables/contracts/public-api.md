# Contract: public API changes

What `import quotable` gives a user after this feature. Everything not listed here is unchanged. Spec: [../spec.md](../spec.md).

## Exports

`quotable.__all__` gains `TableFailedWarning` and `Problem`.

```python
from quotable import Problem, Table, TableFailedWarning, extract_tables
```

- `TableFailedWarning(UserWarning)`: defined in `quotable/errors.py`.
- `Problem`: frozen dataclass `(stage, pages, message)`; see [../data-model.md](../data-model.md).

`extract_tables` and `extract_tables_async` keep their names, arguments and return type `list[Table]`. `ocr=True` stays the default.

## What a call returns

- One `Table` per table, sound or failed, in the order of the first page each appears on (no reordering when nothing failed).
- A call raises for a document-level failure only: no table in the document, a window answer that is wrong (page count, extra-field names) after its retry, a page too large for the image policy, the request cap, the cost limit, an unusable text layer (`TextLayerError`, `OcrUnavailableError`). These are unchanged.
- A call does not raise for a check that concerns one table. Those become `Table.problems`.

## Table additions

| Member | Type | Warns when read |
|---|---|---|
| `problems` | `list[Problem]` | no |
| `failed` | `bool` property | no |
| `label`, `columns`, `pages`, `layers`, `grounded`, `position`, `layouts`, `proposals`, `audit`, `ocr_pages`, `merged`, `extra_fields`, `extra_names`, `extra_changes` | as today | no |
| `rows()`, `page_rows(page)`, `records()`, `to_pandas()`, `to_polars()`, `flagged()` | as today | **yes, once per call, only on a failed table** |

Not public: `Table.first_page()`, `Table.problem_pages()`, `Table.warn_failure()`, the quiet `_rows`, `_page_rows`, `_records` and `_flagged` and the function `page_ranges` are for the package itself and may change.

On a failed table:

- The six accessors return what the table holds and never raise because it failed. A table with no extracted pages gives `[]` from `rows()`, `records()` and `flagged()` and an empty frame (with the usual columns) from `to_pandas()` and `to_polars()`.
- `page_rows(page)` for a page the table does not hold raises `KeyError`, as it does today for a sound table. It does not raise because the table failed.
- A missing optional dependency still raises `ImportError` from `to_pandas()`/`to_polars()`; that is not a failure of the table.
- A sound table never warns.

## Warnings

- `TableFailedWarning` is emitted once per failed table when the call finds the failure, and once per call of each accessor above on a failed table. The text is in [messages.md](messages.md).
- The user controls it with Python's `warnings` module: `warnings.simplefilter("ignore", TableFailedWarning)` silences it, `"error"` turns a read into an exception. A filter that turns it into an error also affects the warning at failure time, where it raises inside the call; that is the user's choice and the library does not guard against it.

## Compatibility

- Code that read `tables[i].rows()` on a sound table sees no change.
- Code that relied on `ExtractionError` for the checks above no longer gets it; it should look at `table.failed`.
- `pip install "quotable[ocr]"` and `"quotable[ocr-core]"` stop being extras (pip warns that the extra does not exist). PaddleOCR comes with `pip install quotable` on macOS arm64, Linux x86_64 and Windows x86_64 with Python 3.11 to 3.13.
