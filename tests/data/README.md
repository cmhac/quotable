# Test data

Sample PDFs from the House Appropriations Committee's community project funding
"included projects" tables (public documents):

| File                                | Pages | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------------------- | ----- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fy22_milcon_house_original.pdf`    | 1     | Rotated page (`/Rotate 90`); every recorded cell is printed verbatim.                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `fy24_milcon_house_original.pdf`    | 2     | Rotated; a different column set.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `fy22_ag_house_original.pdf`        | 4     | Upright; shared (merged) cells repeated down rows, some real model misses.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `senate_expenditures_garbled.pdf`   | 3     | Rotated pages from the Secretary of the Senate's expenditure report (printed pages B-41 to B-43, a public document). The pages render correctly but the embedded text layer is garbled by a font-encoding problem (`0.00` is stored as `4$44`). Negative fixture for the text-layer check: it must be rejected with `TextLayerError`. Has no `.rows.json`.                                                                                                                                                                                   |
| `senate_expenditures_paddleocr.pdf` | 3     | The same three pages after OCR with PaddleOCR 3.7.0 (PP-OCRv6 medium models, 300 dpi): each page is the rasterized image plus an invisible word-level text layer. The layer is readable (scores like the House fixtures) but has real OCR errors, notably every thousands comma read as a period (`68.027.74`) and a few misread names (`MARESE`, `BOLIEK`). Positive fixture for the text-layer check, the document for exercising the recheck's deference to the text layer, and the only fixture with two tables on one page (see below). |

`<name>.rows.json` holds the rows a vision model returned for each PDF in the original
project (final values after its recheck), keyed by page: `{"columns": [...], "pages": {"1": [row, ...]}}`.
The offline tests replay these as the "model" answers. They are recorded outputs, not a
ground truth: a few cells in the ag sample are known to be wrong, which the tests allow for.

`senate_expenditures_paddleocr.rows.json` has a different shape because this document holds two
tables, a 7-row summary table above the detail table on page 1 and the detail table over pages 1
to 3: `{"discovery": <the model's table-discovery answer>, "tables": [{"label": ..., "pages":
{"1": [row, ...]}}]}`. It is the model's recorded output, not edited by hand: the rows are the
first-pass extract answers (before any recheck) from a live run on this PDF, and the discovery
answer is that run's. The answer was recorded with a prototype of the discovery prompt that also
asked for a page number and a `continues_from_previous_page` flag per table; those two fields are
dropped here because the library no longer asks for them. The rest is as the model returned it.

## NVIDIA GPU check (manual)

There is no automated test for the GPU path: the development machine is a Mac with no NVIDIA
GPU, so the GPU code is only tested against fakes (`tests/ocr/test_ocr_device.py`,
`tests/ocr/test_paddle_adapter.py`). Someone with an NVIDIA card should run this once and record it
below. Nothing in this repository claims a GPU result until a row is filled in.

On Linux x86_64 or Windows. The dev group installs the CPU build of PaddlePaddle, so swap it for the
GPU build and use `--no-sync` so that `uv run` does not put the CPU build back:

```bash
uv sync
uv pip uninstall paddlepaddle
uv pip install paddlepaddle-gpu==3.3.1 --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
uv run --no-sync python -c "import paddle; print(paddle.__version__, paddle.device.is_compiled_with_cuda(), paddle.device.cuda.device_count())"
# expect: 3.3.1 True 1 (or more)
uv run --no-sync pytest -m ocr -rs --durations=0               # device="auto" must pick the GPU
uv run --no-sync python -c "
import logging; logging.basicConfig(level=logging.INFO)
from pathlib import Path
from quotable import OcrConfig
from quotable.ocr.paddle import PaddleEngine
from quotable.ocr.pages import ocr_pages
config = OcrConfig(device='gpu')
ocr_pages(Path('tests/data/senate_expenditures_garbled.pdf'), [1], config, PaddleEngine(config), Path('gk-cache'))
"
```

Check that the log says `OCR device: gpu:0`, that there is no "trying again on the CPU" warning,
and that a page takes seconds, not about a minute as on a CPU. Then record:

| Date | Card | Driver | CUDA wheel | PaddlePaddle | Result | Seconds per page |
| ---- | ---- | ------ | ---------- | ------------ | ------ | ---------------- |
|      |      |        |            |              |        |                  |

## `synthetic/`: the extra-fields documents (`extra-*`)

Twenty of the generated PDFs (ids `extra-...`, made by `tests/synthetic_cases.py::extra_fields`,
drawn by `tests/synthetic.py`) carry a header block: lines of text at the top left of a page
(a label and a value per line, like the Senate sample) whose values are the extra fields of
spec 010. Their truth files have an `extra_fields` object:

- `fields` (name, description, group) and `groups` as the caller would declare them;
- `printed`: page -> field -> the value printed on that page, or `null`; `boxes`: the drawn box
  of each printed value; `block_boxes` and `table_boxes`: where the blocks and the tables are;
- `expected`: page -> field -> `{value, source_page}` or `null`, three ways: `plain` (a page has
  only what it prints, the default), `carry` (carried forward, groups clear) and
  `carry_ungrouped` (carried forward, no groups). The generator computes them with its own loop,
  which imports nothing from the library;
- `baits`: the (page, field) pairs where the missed-header check should fire (words in a field's
  region outside the tables' rows), computed from the PDF's words;
- `expect_stale` (an ungrouped field keeps a value a page dropped: the documented limit) and
  `expect_blind` (a block that moves or is right-aligned: the check cannot see it).

Each document is tagged `scenario-N` for the scenarios of the spec (1 to 12). The 154 documents
of the merge fixture are unchanged. `tests/test_synthetic.py` checks the family; `just
score-extra-fields` injects faults into what a fake model reads and prints how the checks do.
