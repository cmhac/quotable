# Contract: install extras and the missing-library error

These are the only outward-facing changes of spec 015. The public API in `quotable/__init__.py`,
the review app's HTTP API, the saved-run format and the cache keys do not change.

## Install

| Command | Brings |
|---------|--------|
| `pip install quotable` | the pipeline; no pandas, no polars |
| `pip install "quotable[pandas]"` | the above plus `pandas>=3,<4` |
| `pip install "quotable[polars]"` | the above plus `polars>=2,<3` |
| `pip install "quotable[pandas,polars]"` | both |
| `pip install "quotable[ocr]"` / `"quotable[ocr-core]"` | unchanged |

## Error when the library is missing

`Table.to_pandas()` without pandas installed raises `ImportError` with this message (the polars
message is the same with `polars` in each place):

```text
to_pandas() needs pandas, which is not installed by default. Run: pip install "quotable[pandas]"
```

The original `ImportError` is chained as the cause. `records()` and everything else work without
either library.

## README

The sentence "pandas and polars are installed with quotable" is replaced by the install table
above. A short passage tells notebook users to `await extract_tables_async(...)` because
`extract_tables` cannot run while an event loop is running.
