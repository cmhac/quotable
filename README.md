# quotable

Extract tables from PDFs with a vision LLM, then check every value against the PDF's
own text layer. A barebones starting point, distilled from the extraction pipeline of
the VRA community-projects analysis.

```python
from quotable import extract_tables

tables = extract_tables(
    "tables.pdf",
    model="openai:<model-name>",  # required; a pydantic-ai model string or Model instance
    cache_dir="cache",  # optional: where answers and OCR results are cached (default .quotable/cache/)
    max_requests=100,  # optional: cap on new (uncached) model requests
)  # one Table per table in the PDF

for table in tables:
    table.label  # the model's short name for the table
    table.records()  # one flat dict per row: values, <column>__grounding, <column>__coverage, ...
    table.to_pandas()  # the same rows as a pandas DataFrame
    table.to_polars()  # ... or a polars DataFrame
    table.flagged()  # every cell that is not an exact match, with its status
```

`model` has no default and is never read from an environment variable. It is a
[pydantic-ai](https://ai.pydantic.dev) model string (`"provider:model-name"`) or a pydantic-ai
`Model` instance, which is how a custom provider plugs in. The provider's API key comes from the
environment, as pydantic-ai documents it (for example `OPENAI_API_KEY`). The install includes the
SDKs for Anthropic, Bedrock, Cohere, Google, Groq, Hugging Face, Mistral, OpenAI, OpenRouter and
xAI. `model_settings=` is passed to pydantic-ai. `extract_tables_async` takes the same arguments.

pandas and polars are installed with quotable. The frames have the columns of `records()`: `page`,
`row`, the PDF's columns (strings, exactly as extracted), then for each of them its `__grounding`
status and `__coverage` (a float, missing when the cell was never looked up), then
`grounding_status` and `recheck_changes`. A PDF column is never renamed: if it already has the name
of one of those columns (a PDF column called `page`, say), the quotable column gets a trailing `_`
(`page_`). Write a CSV with `table.to_polars().write_csv(path)`.

A PDF with one table returns a list of one. Pages are shown to the model `discovery_pages`
at a time (default 4; pass `discovery_pages=` to change it).

### Headers worded differently on different pages

Discovery joins pages whose column names match (case and punctuation ignored). If a table is
headed "Requested Local Match" on some pages and "Requested Match" on others, those are two
tables to discovery. After extraction, and before the recheck, quotable joins two tables only
when all of these hold, and otherwise leaves them apart (no model request is made):

- they share no page and have the same number of columns;
- at every position one column name's words contain the other's ("Requested Match" in
  "Requested Local Match"; word order does not matter), and no column also fits a different
  position of the other table (a bare "Amount" next to "Requested Amount" and "Recommended
  Amount" is ambiguous);
- the columns sit at the same x positions (within 10 pt) and in the same order;
- every column holds the same kind of value on both sides (currency, percent, integer,
  decimal, date or text; at least 80% of its cells), judged from at least 5 grounded cells
  per column and side. Too little data to judge means no merge;
- each table has exactly one possible partner.

The merged table uses the earlier part's column names; `Table.merged` lists each absorbed part
(`MergedPart`: its pages, its original column names, and the evidence: word sets, grid
difference, shapes and cell counts). `extract_tables(..., merge_reworded=False)` turns the step
off. The residual risk is two different tables that share a template and whose names contain
each other ("Population" and "Population 2020" in two sections): the golden fixture merges 4 of
its 5 such cases. Look at `Table.merged` if your documents are like that, or turn the step off.
`just score-merge` shows how each rule and threshold did on the fixture.

### Values printed outside the tables (extra fields)

A page header such as a fiscal year or a section name is not in any table, but it often belongs
on every row. Name the values to read and `extract_tables` adds them as columns:

```python
from quotable import ExtraField, ExtraFields, FieldGroup, extract_tables

tables = extract_tables(
    "report.pdf",
    model="openai:<model-name>",
    extra_fields=ExtraFields(
        [
            # fields printed together in one block go in a group; the description goes to the model
            FieldGroup(
                "heading",
                "The block of lines at the top left of a page that starts a section",
                [
                    ExtraField("year", "The funding year, from the second line of the block"),
                    ExtraField("title", "The title of the section, from the third line"),
                ],
            ),
            ExtraField("agency", "The agency named in the footer"),  # a field on its own
        ],
        prompt="",  # optional free text for the model, e.g. where the blocks are
        carry_forward=True,  # off unless asked for (see below)
    ),
)
```

Describe where a field is and what it is, not what it says: the description goes to the model,
and a word of the header in it biases the reading.

When a printed line is a label followed by its value (`Year 2018`), the model reports only the
value by default. Say in the description what you want when it differs or the line is
ambiguous: "the account line, label included" keeps the whole line, and "the name that follows
the label at the start of the second line" leaves the label out. The model cannot tell from the
page alone where a label ends, so a description that says nothing about it gets inconsistent
answers.

- **Columns.** After the table's own value columns, `records()` and both frames have one column
  per field, named as you named it, then for each field `<name>__grounding`, `<name>__coverage`
  and `<name>__source_page` (the page that printed the value; a nullable integer, `Int64` in
  pandas). Each `Row` has `Row.extra` and each `Table` has `Table.extra_fields` (page -> field ->
  `ExtraResult`). If a field has the name of a PDF column it gets a trailing `_`; the library's
  own columns give way to a field called `page`, so the page number becomes `page_`.
- **Checked like any other text.** Each value is looked up in the page's whole text layer
  (`exact`, `fuzzy`, `ungrounded`, `untokenized`; `empty` when nothing was printed). A field value
  counts in `Row.status`, `grounding_status` and `Table.flagged()` (flags with `extra=True`), and
  a `fuzzy` or `ungrounded` value gets one second look with the text layer, kept only if it grounds
  strictly better, and shown in `recheck_changes` (`recheck=False` turns it off).
- **Carrying forward.** By default (`carry_forward=False`) a page has exactly what it prints, so
  the continuation pages of a section have empty fields. With `carry_forward=True` a page that
  prints nothing takes the nearest earlier page's value (never a later one), with its grounding
  and `__source_page`. A field in a `FieldGroup` is also cleared on a page that prints some other
  field of its group (grounded `exact` or `fuzzy`) and not this one, because a block that drops a
  line has dropped it. A field in no group is never cleared.
- **Missed headers.** Discovery's `null` is the only evidence that a page prints no header. After
  it, for each field, the text layer is searched where the field is printed on other pages (plus
  6 pt), outside every table's band; a page with words there gets one second look at that page,
  and the answer counts only if it grounds. This runs whether or not the carry is on, and costs
  one request per suspect page (counted by `max_requests`).
- Nothing changes without `extra_fields`: the requests, and so the cache keys, are the same.

`just score-extra-fields` shows how the checks do with injected faults (no model, no cost).

## The text layer, and OCR

Every value is checked against the PDF's text layer, and grounding cannot be turned off.
Before any model request, the text layer is scored with English character trigrams. A page
whose layer is garbled (a broken font encoding, bad OCR) or missing (a scan with no OCR) is
a bad page. If too many pages are bad, quotable OCRs the bad pages (only those) with
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), builds a text layer from the result,
checks again, and carries on. If the OCR'd text is still unreadable, or OCR is not installed,
the run stops with `TextLayerError`, still before any model request. The check is English and
Latin-script only. A document with text but too few letters to score (only numbers) is
accepted.

```python
from quotable import OcrConfig, extract_tables

extract_tables("scan.pdf", model=...)  # ocr=True: OCR bad pages with the defaults
extract_tables("scan.pdf", model=..., ocr=OcrConfig(dpi=200, device="cpu"))  # configured
extract_tables("scan.pdf", model=..., ocr=False)  # never OCR: reject a bad layer instead
```

`Table.ocr_pages` lists the pages of a table whose text layer came from OCR. The recheck
defers to the text layer, so an OCR error (the sample OCR'd Senate PDF reads every thousands
comma as a period: `68.027.74`) can pass into the output; review those pages with more care.

### Installing OCR

OCR is an optional extra, so a plain `pip install quotable` stays small. If you are sure your
PDFs have good text layers you never need it. If a PDF needs OCR and PaddleOCR is not
installed, quotable raises `OcrUnavailableError` (a `TextLayerError`) saying so, before any
model request, so the only cost is installing and running again.

```bash
# CPU (macOS Apple Silicon, Linux x86_64, Windows x86_64; Python 3.11 to 3.13): one command
pip install "quotable[ocr]"
```

The extra installs `paddleocr` and the CPU build of `paddlepaddle` (about 100 to 200 MB, plus
OpenCV and others). It cannot install on Intel Macs, Linux ARM or Python 3.14, where
PaddlePaddle publishes no wheel; OCR the PDF yourself there (for example `ocrmypdf --force-ocr`).

### OCR on an NVIDIA GPU

With `device="auto"` (the default) OCR runs on an NVIDIA GPU when the installed PaddlePaddle can
use one and on the CPU otherwise. If an NVIDIA GPU is found but PaddlePaddle cannot use it, OCR
runs on the CPU and logs a warning saying why. A GPU that was chosen automatically and fails
(for example out of memory) falls back to the CPU once; a device you name is not retried. AMD
GPUs and Apple GPUs are not supported: those machines run on the CPU.

PaddlePaddle's CPU and GPU wheels both provide the `paddle` package, and the GPU wheels are on
Paddle's own index, not PyPI, so there is no `gpu` extra. Install the core extra, then the GPU
build:

```bash
pip install "quotable[ocr-core]"
pip install paddlepaddle-gpu==3.3.1 \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
# cu126 needs an NVIDIA driver >= 550.54.14; cu118 (use .../cu118/) needs >= 450.80.02 on Linux.
# You need the driver, not the CUDA toolkit. Linux x86_64 and Windows only. NVIDIA 50-series
# on Windows needs the special wheels listed in PaddleOCR's install guide.

# with uv
uv pip install "quotable[ocr-core]"
uv pip install paddlepaddle-gpu==3.3.1 \
  --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

Do not install `quotable[ocr]` in the same environment: it brings the CPU build, which would
overwrite the GPU one. The GPU path is untested on real hardware (the development machine has
no NVIDIA GPU); `tests/data/README.md` has a manual checklist. The `uv` line and
`--extra-index-url` were checked to resolve, not to install.

### OCR settings

`OcrConfig` has a default for everything: `lang="en"`, `ocr_version="PP-OCRv6"` (medium
models, the same on every device), `dpi=300`, `device="auto"` (or `"cpu"`, `"gpu"`, `"gpu:1"`),
`cpu_threads`, `min_confidence=0.0`, `text_detection_model` / `text_recognition_model` (name a
smaller or larger model), `engine` (passed to PaddleOCR; only PaddlePaddle is tested),
`model_dir`, and `paddleocr_options` / `predict_options` for any other PaddleOCR argument.
Options that rotate or unwarp the page are refused, since they would move the OCR boxes away
from the page the model sees. On a CPU a full page at 300 dpi takes about a minute (measured on
an Apple Silicon Mac); results are cached, so it is a one-time cost per page and setting.

PaddleOCR downloads its models itself the first time they are needed (about 140 MB for the
default ones) and stores them where PaddleOCR does (`~/.paddlex`). For an offline machine, copy
that folder's model subfolders and pass `OcrConfig(model_dir=<folder>)`.

### The cache

Model answers and OCR results are always cached on disk, in `.quotable/cache/` in the current
working directory unless you pass `cache_dir` (which is used as you give it). quotable creates
the folder and, when it makes `.quotable/` itself, puts a `.gitignore` containing `*` in it. A
cache that an earlier version left loose in `.quotable/` is moved into `cache/` the first time.
There is no in-memory mode, and nothing is ever deleted: remove `.quotable/cache/` to start
over. It holds content derived from your PDF (the model's
extracted values and the OCR'd text), so delete it if the data is sensitive. A run that cannot
write the folder raises an `OSError` naming it. A cached OCR page is reused whatever device made
it, and works without the OCR extra installed.

### Cost

Every request that reaches a model is recorded in `.quotable/cost/requests.jsonl`, in the
project's `.quotable/` folder even when you pass a `cache_dir`. It is kept apart from the cache,
so clearing the cache (`rm -rf .quotable/cache`) leaves the costs alone. A record holds the time,
a run id, the stage, the model, the token counts and the price; it never holds a prompt, an
answer or a path. Answers served from the cache cost nothing and are not recorded. The price is
an estimate from the price data that comes with pydantic-ai (genai-prices), worked out when the
request was made and stored; a model with no known price is recorded with no price and left out
of the total. If `cache_dir` points at `.quotable` itself, the cache and the cost folder share
it, so clear it with care.

`quotable cost-report` adds the records up. It makes no model request and needs no API key:

```console
$ quotable cost-report
Cost report for .quotable/cost/requests.jsonl

Runs:      7
Requests:  412 paid, 0 unpriced
Tokens:    3,204,118 in, 188,430 out
Total:     $9.87

By model            Requests      In tokens    Out tokens        Cost
openai:gpt-5.1           400      3,100,000       180,000       $9.40
openai:gpt-5-mini         12        104,118         8,430       $0.47
```

`--dir PATH` reads another project's `.quotable/` folder. "Requests" counts every request that
reached a model and "unpriced" says how many of those had no price. A line that cannot be read
is skipped and counted. With no records it says so and exits 0; an unreadable cost file exits 1.

## What it does

| Stage | Module | What happens |
|---|---|---|
| Text-layer check | `textcheck` | Each page's text is scored against an English trigram model; the document is rejected if more than 10% of the scorable pages are garbled, or it has no text. |
| Table discovery | `discover` | Every page goes to the model, `discovery_pages` at a time, one window after the next. It lists the tables on each page with their columns and the words of each table's first and last row. Later windows are told the tables found so far, so a page that continues a table without printing its header reuses that table's columns. Tables with the same columns on different pages are one table. |
| Layout discovery | `layout` | For each table, each page's printed header (found in the text layer) says which columns that page prints; pages without a header inherit the previous layout. |
| Extraction | `extract` | One request per table and page returns its rows. On a page with several tables the request names the other tables and asks for this one only. Rows with wrong keys are sent back once. |
| Grounding | `grounding` | Each value is looked up in the table's text layer (the page's, or on a page with several tables only the band between the table's first and last row, found with `regions`): exact token match, else a fuzzy longest-common-subsequence match. Statuses: `exact`, `fuzzy`, `ungrounded`, `untokenized`, `empty`, `not_on_page`. |
| Position check | `position` | A value must sit in its own row and column (row windows from uniquely-occurring values, column bands pooled over the document). Values found elsewhere become `misplaced`. |
| Merge | `merge` | Two tables that are really one but whose headers are worded differently on different pages are joined when every check passes (see "Headers worded differently"); any doubt leaves them apart. Switch off with `merge_reworded=False`. |
| Extra fields | `extra_fields` | Optional (see "Values printed outside the tables"). Discovery also reads the requested fields on each page; they are grounded in the page's whole text layer, rechecked if fuzzy or ungrounded, checked for missed headers (a second look at pages with unexplained words where the header is printed elsewhere), carried forward on request and attached to every row. |
| Recheck | `recheck` | Flagged cells go back to the model once with their reason, the page image and the page's whole text layer; the model is told to copy the text layer's reading. An answer is kept only if grounding of that cell strictly improves. Because the text layer wins, OCR errors in it (for example thousands commas read as periods) can pass into the output. |

Model requests are always cached on disk (see "The cache" above), by a hash of everything that
decides the answer, and `max_requests` caps how many new requests one run may make
(`BudgetExceededError` beyond it).

## Not handled

- Tables side by side on a page. Tables are separated by a vertical band only; if two bands
  overlap, or a table's first or last row cannot be found in the text layer, the run raises
  `ExtractionError`.
- Tables whose column names change between pages are merged only in the cases described under
  "Headers worded differently on different pages". Names that share no words ("Amount" and
  "Funding"), a different column count and more than one possible partner stay separate tables;
  two real tables with the same columns are returned as one.
- Titles and captions printed outside a table are captured only if you name them as extra fields.
  For those: a header that starts a new section halfway down a page (scope is per page); a header
  that clears a field by leaving it out, for a field in no group (it keeps the old value: put
  fields that are printed together in a `FieldGroup`); a section with no printed marker at all;
  a header printed at a different place on different pages, or right-aligned or centred with a
  changing length (the missed-header check does not see it; only the model's reading does);
  values that depend on a table's rows (that is a column); pages not in reading order.
- Page orientation in scans: OCR does not rotate or unwarp pages, so a sideways scan with no
  `/Rotate` flag stays sideways and is rejected after OCR.

## Development

Commands are in the `justfile` ([just](https://github.com/casey/just)); run `just` to list them.

```bash
just setup       # uv sync, and install the git pre-commit hook
just test        # offline: no network, no API key, ~15 s
just test-ocr    # real PaddleOCR models on the CPU: slow, no API cost, downloads models first time
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
- `tests/data/synthetic/` is a golden fixture: 154 generated PDFs for the merge step and 20
  `extra-*` ones for extra fields, each with a real text layer and a truth file (`just synthetic`
  regenerates it byte for byte; `just score-merge` and `just score-extra-fields` score the merge
  rules and the extra-field checks on it, with no model). The live tests
  `tests/live/test_live_merge.py` and `tests/live/test_live_extra_fields.py` run their cases
  through a real model; the second describes each field by its position only, so the request
  never prints a word of the header it asks about (`tests/test_extra_fields_live_prompts.py`
  checks that offline).
- `tests/ocr/` runs the real PaddleOCR models on the CPU (`just test-ocr`). Deselected by
  default; it takes minutes, downloads the models on first use, and calls no model API.
- `tests/live/` calls a real model. These tests are deselected by default and skip
  themselves unless `OPENAI_API_KEY` and `QUOTABLE_LIVE_TEST_MODEL` are set:

  ```bash
  QUOTABLE_LIVE_TEST_MODEL="openai:<model-name>" uv run pytest -m live
  ```

  Their answers are cached in `tests/live/.cache`, and each run is capped at a few requests.
  To speed up the spec 010 live file, add `-n 4` (pytest-xdist; each worker keeps up to 4
  requests in flight, so lower it on rate-limit errors) and/or set `QUOTABLE_LIVE_RUNS=1` to run
  each case once instead of three times.

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
- **Cost:** a dollar cap (only a request-count cap exists) and the run-metadata sidecar.
  Per-request cost is recorded and summed by `quotable cost-report` (see "Cost").
- **Output:** no CSV/sidecar writer or extraction CLI yet; `Table.records()`, `Table.to_pandas()` and
  `Table.to_polars()` are the interface.
