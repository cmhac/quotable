# gridkey

Extract tables from PDFs with a vision LLM, then check every value against the PDF's
own text layer. A barebones starting point, distilled from the extraction pipeline of
the VRA community-projects analysis.

The name is a play on words: tables in PDFs are grids that are locked on the page, and
this is the key that unlocks them.

```python
from pathlib import Path
from gridkey import CachedClient, extract_table
from gridkey.pydantic_ai_client import PydanticAIClient  # needs the [openai] extra

client = CachedClient(PydanticAIClient("openai:<model-name>"), Path(".cache"), max_requests=100)
table = extract_table(Path("tables.pdf"), client)

table.records()  # one flat dict per row: values, <column>__grounding, <column>__coverage, ...
table.flagged()  # every cell that is not an exact match, with its status
```

Any object with an `identity` string and an `async ask(request)` method is a client, so
other providers (or a fake) plug in without touching the pipeline.

## Requires a readable text layer

Every value is checked against the PDF's text layer, and grounding cannot be turned off.
Before any model request, the text layer is scored with English character trigrams; a PDF
whose layer is garbled (a broken font encoding, bad OCR) or missing (a scan with no OCR) is
rejected with `TextLayerError`, having made no request. The fix is to improve the PDF's OCR
(for example re-run OCR over the whole document, replacing the existing text layer with
`ocrmypdf --force-ocr`) and try again. The model is English and Latin-script only. A
document with text but too few letters to score (only numbers) is accepted.

## What it does

| Stage | Module | What happens |
|---|---|---|
| Text-layer check | `textcheck` | Each page's text is scored against an English trigram model; the document is rejected if more than 10% of the scorable pages are garbled, or it has no text. |
| Schema discovery | `extract` | The first pages go to the model, which returns only the column structure. |
| Layout discovery | `layout` | Each page's printed header (found in the text layer) says which columns that page prints; pages without a header inherit the previous layout. |
| Extraction | `extract` | One request per page returns its rows. Rows with wrong keys are sent back once. |
| Grounding | `grounding` | Each value is looked up in the page's text layer: exact token match, else a fuzzy longest-common-subsequence match. Statuses: `exact`, `fuzzy`, `ungrounded`, `untokenized`, `empty`, `not_on_page`. |
| Position check | `position` | A value must sit in its own row and column (row windows from uniquely-occurring values, column bands pooled over the document). Values found elsewhere become `misplaced`. |
| Recheck | `recheck` | Flagged cells go back to the model once with their reason, the page image and the page's whole text layer; the model is told to copy the text layer's reading. An answer is kept only if grounding of that cell strictly improves. Because the text layer wins, OCR errors in it (for example thousands commas read as periods) can pass into the output. |

Model requests are cached on disk by a hash of everything that decides the answer
(`CachedClient`), and `max_requests` caps how many new requests one run may make.

## Development

Commands are in the `justfile` ([just](https://github.com/casey/just)); run `just` to list them.

```bash
just setup       # uv sync --extra openai, and install the git pre-commit hook
just test        # offline: no network, no API key, ~5 s
just lint        # ruff check
just format      # ruff format
just typecheck   # ty check
just hooks       # all pre-commit hooks (ruff check --fix, ruff format, ty) on all tracked files
just check       # hooks, then tests
```

### Tests

- `tests/` runs offline. A fake model replays rows recorded from the original project
  against real sample PDFs (`tests/data/`), so the whole pipeline is exercised without
  any API call. Several tests corrupt the recorded rows (a swapped value, a typo) to
  check that the position check and the recheck catch it.
- `tests/live/` calls a real model. These tests are deselected by default and skip
  themselves unless `OPENAI_API_KEY` and `GRIDKEY_LIVE_MODEL` are set:

  ```bash
  GRIDKEY_LIVE_MODEL="openai:<model-name>" uv run pytest -m live
  ```

  Their answers are cached in `tests/live/.cache`, and each run is capped at a few requests.

## Not carried over yet

Deliberately omitted from this first cut; the original code is the reference for each:

- **Page orientation:** the original rotated sideways pages upright in a separate step. The
  samples already carry a correct `/Rotate` flag, and `get_text` / rendering honour it.
- **Layout discovery:** grouping header pages by column x-position, choosing a layout for
  headerless pages by word-position histograms, and adding columns the schema lacks from
  header labels (the `Recipient` case).
- **Position check:** the `incomplete` verdict, per-layout column bands, and sharing space
  between unbanded columns.
- **Recheck:** splitting pages with many flagged cells over several requests, capping the size
  of the text layer sent, and undoing accepted changes that make another cell worse.
- **Cost:** dollar pricing and a dollar cap (only a request-count cap exists), usage ledger,
  and the run-metadata sidecar.
- **Output:** no CSV/sidecar writer or CLI yet; `Table.records()` is the interface.
