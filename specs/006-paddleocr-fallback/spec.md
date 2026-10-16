# 006 - OCR with PaddleOCR when the text layer is garbled or missing, and an always-on cache

Status: implemented (the NVIDIA GPU path has never run on real hardware; see the manual checklist
in `tests/data/README.md`)

## Summary

Today a PDF whose text layer is garbled or missing is rejected with `TextLayerError` before
any model request (spec 001), and the user is told to run OCR themselves. This spec makes
gridkey do that step: when the check rejects a document, gridkey OCRs the pages that failed
with PaddleOCR, builds a new text layer for them, checks the result again, and carries on. If
the OCR'd text is still unreadable, or OCR is not installed, the run stops with
`TextLayerError`, still before any model request.

It also changes where results are kept: OCR results **and** model answers are always cached on
disk, in `.gridkey/` in the current directory unless `cache_dir` says otherwise. There is no
in-memory-only mode.

```python
from gridkey import extract_tables, OcrConfig

# Default: OCR runs only if the text layer is bad; device chosen automatically;
# results cached in ./.gridkey/
tables = extract_tables("scan.pdf", model="openai:<model-name>")

# Configured, and cached somewhere else.
tables = extract_tables(
    "scan.pdf",
    model="openai:<model-name>",
    cache_dir="cache",
    ocr=OcrConfig(device="cpu", dpi=200, lang="en", ocr_version="PP-OCRv5"),
)

# Previous behaviour for the text layer: reject, do not OCR.
tables = extract_tables("scan.pdf", model="openai:<model-name>", ocr=False)
```

## Motivation

The Senate trial (spec 001) showed the quality check works but leaves the user with a chore:
install and run `ocrmypdf` or PaddleOCR, produce a new PDF, and call gridkey again. The
repo's own OCR fixture (`tests/data/senate_expenditures_paddleocr.pdf`) was made by hand with
PaddleOCR 3.7.0, PP-OCRv6 medium models at 300 dpi, and the pipeline then ran correctly on it.
Doing that inside the library removes the manual step, and lets gridkey keep the guarantee
that grounding cannot be turned off: the text layer it verifies against is always one it has
checked.

OCR is slow on a CPU and model requests cost money, so neither should be repeated by accident.
Always caching to a predictable folder makes a second run cheap without the user having to
remember an argument.

## Requirements

1. **Trigger.** OCR runs when `check_text_layers` would reject the document (no words on any
   page, or more than `MAX_GARBLED_PAGE_SHARE` of the scorable pages garbled). It does not run
   on an accepted document. The thresholds and the check itself are unchanged and cannot be
   switched off.
2. **Which pages.** Only bad pages are OCR'd: pages judged `garbled`, and pages with no words.
   Pages with a good native layer keep it. (Resolved by the user.)
3. **New layer, not a new PDF.** The OCR result becomes `Layer` objects, built from the cached
   OCR words (requirement 11), that replace the bad pages' layers. The input file is never
   modified and no PDF is written. Rendering for the model and for the recheck still use the
   original PDF's pages.
4. **Check again.** The merged layers go through `check_text_layers` a second time. If that
   rejects, raise `TextLayerError` saying OCR was tried (engine, device, pages) and what the
   OCR'd text looked like. Zero model requests are made in every rejection path.
5. **Public argument.** `extract_tables` and `extract_tables_async` gain
   `ocr: OcrConfig | bool = True`, keyword-only. `True` means `OcrConfig()` (the defaults);
   `False` means never OCR (spec 001 behaviour, with the message below); an `OcrConfig`
   configures it.
6. **Sensible defaults, everything configurable.** `OcrConfig` (frozen dataclass, exported
   from `gridkey`) has the fields in the table under Design. Anything PaddleOCR accepts that
   `OcrConfig` does not name can be passed through `paddleocr_options` (constructor) and
   `predict_options` (per-page call). The default models are the same on every device; a user
   who wants a smaller or larger model names it (`ocr_version`, `text_detection_model`,
   `text_recognition_model`). (Resolved by the user.)
7. **Automatic hardware choice.** With `device="auto"` (the default) OCR runs on an NVIDIA GPU
   when the installed PaddlePaddle is a GPU build that can see one, and on the CPU otherwise.
   CPU always works. The rules are under Design / Hardware. AMD GPUs are out of scope: an AMD
   machine runs on the CPU. (Resolved by the user.)
8. **GPU failure falls back to CPU when the choice was automatic.** If a GPU was chosen by
   `auto` and loading the models or the first page fails (out of memory, unsupported card),
   gridkey logs a warning and redoes the work on the CPU. An explicitly requested device
   (`device="gpu:1"`) is not retried; the error is raised.
9. **OCR is an optional extra; the default install is lean.** `pip install gridkey` has no
   PaddleOCR. If a document needs OCR and PaddleOCR is not importable, raise
   `OcrUnavailableError` (a `TextLayerError` subclass, so existing `except TextLayerError`
   keeps working) whose message gives the install command. This costs the user nothing but a
   rerun, because the text-layer check runs before any model request. Someone certain their
   documents have good text layers never installs the OCR stack (about 100 to 200 MB plus
   OpenCV, pandas and others). Nothing imports PaddleOCR until OCR actually runs on a page
   the cache cannot answer. The extras are described under Design / Dependencies.
10. **Clear rejection messages.** `REMEDY` in `textcheck.py` becomes one of three messages,
    chosen by why OCR did not rescue the document: OCR disabled (`ocr=False`: "enable OCR or
    OCR the PDF yourself"), OCR not installed (`pip install "gridkey[ocr]"`, and a pointer to
    the README for NVIDIA GPUs; on a platform with no PaddlePaddle wheel, say so and suggest
    OCR'ing the PDF yourself), OCR ran but the result is still unreadable (the existing
    advice, plus what was tried).
11. **Everything is cached on disk; there is no in-memory-only mode.** This replaces spec 005's
    "`cache_dir=None` means no caching". The cache directory is the `cache_dir` argument when
    given, otherwise `.gridkey/` in the current working directory at the time
    `extract_tables` is called (`cache_dir` stays `str | Path | None = None`; `None` now means
    "use the default"). It holds two kinds of file:
    - **Model answers**, as today: `<dir>/<request-key>.json`, same key, same layout, so
      existing caches stay valid. `max_requests` still caps only new (uncached) requests.
    - **OCR results**: `<dir>/ocr/<key>.json`, one file per page.

    Rules for both:
    - The directory is created if missing. When gridkey creates `.gridkey/` itself it also
      writes `.gridkey/.gitignore` containing `*`, so the cache is never committed by accident.
      A directory the user named with `cache_dir` is not given a `.gitignore`.
    - Writes are atomic (temp file, then rename). An unreadable or mismatched file counts as a
      miss and is overwritten.
    - If the directory cannot be created or written, raise an `OSError` that names the path
      and says to pass `cache_dir`. The run does not fall back to memory.
    - OCR file contents: the page's words (text, box in points, score) and the settings that
      produced them. OCR key: SHA-256 of the PDF file, page number, and a fingerprint of
      everything that changes the output: `dpi`, `lang`, `ocr_version`, the resolved detection
      and recognition model names, `min_confidence`, `paddleocr_options`, `predict_options`,
      and the PaddleOCR version. The device is not in the key (see Limits).
    - The cache is read before anything else. A page found in the cache needs neither
      PaddleOCR nor a device, so a populated cache works on a machine without the OCR extra.
    - gridkey never expires or deletes cache files. Deleting the folder starts over.
12. **Surfaced in the result.** `Table.ocr_pages: tuple[int, ...]` (default `()`) lists the
    pages of the table whose text layer came from OCR, so a caller can treat their grounding
    with the extra caution the README already describes (OCR errors can pass into the output).
13. **Does not block the event loop.** OCR is blocking work. `extract_tables_async` runs it in
    a worker thread (`asyncio.to_thread`). Pages are OCR'd one after another; the PaddleOCR
    object is built once per run.
14. **Local only.** OCR sends nothing to a service. gridkey does not manage OCR models: it
    leaves their download and storage to PaddleOCR (see Limits). `model_dir` in `OcrConfig`
    allows a fully offline setup. (Resolved by the user.)
15. **Behaviour otherwise unchanged.** Prompts, pipeline stages, the keys and file layout of
    model-answer caching, and the thresholds do not change. A document that passes the check
    runs the same code path and never imports PaddleOCR.

## Design

### Flow

`run_pipeline` (extract.py) today loads layers, calls `check_text_layers`, then renders. It
becomes:

1. Load layers; run the assessment.
2. If rejected and OCR is enabled: for each bad page, read the OCR cache; on a miss render the
   page at `dpi`, OCR it, and write the cache file. Build `Layer`s from the words, replace
   those pages, assess again. PaddleOCR is imported and the device chosen only when at least
   one page misses the cache.
3. If still rejected (or OCR disabled/unavailable): raise `TextLayerError` or
   `OcrUnavailableError`.
4. Continue exactly as now.

`textcheck.py` is split so the second step can ask "which pages failed?" without parsing an
error: `assess_text_layers(layers) -> Assessment` returns the per-page qualities, the
rejection reason (or `None`) and `bad_pages` (garbled pages plus pages with no words).
`check_text_layers` calls it and raises, as now. `run_pipeline` gains an internal
`ocr: OcrEngine | None` argument and the resolved cache directory, so the offline tests inject
a fake engine the way they inject a fake model client.

`extract_tables_async` resolves the cache directory once (argument, else `Path.cwd() /
".gridkey"`), creates it, and passes it both to `CachedClient` and to the OCR step.
`CachedClient.cache_dir` becomes required (no `None`); tests that passed `None` pass a temp
directory.

### Modules

- `ocr.py`: `OcrConfig`, the `OcrEngine` protocol (`recognize(png: bytes) -> list[OcrWord]`,
  where `OcrWord` is text, box in pixels and score), `ocr_pages(...)` (cache lookup, render,
  call the engine, convert pixels to points, build `Layer`s), `OcrUnavailableError`.
- `cache.py`: the cache-directory rule (argument, else `.gridkey/`, with its `.gitignore`) and
  the atomic write, shared by `llm.py` (which already has `_write_atomic`) and the OCR cache.
- `ocr_cache.py`: the OCR key and the per-page files.
- `ocr_device.py`: choosing the device (below). Pure functions over a small `Capabilities`
  value, so the choice is tested without any GPU or PaddleOCR installed.
- `_paddle.py`: internal adapter, the only module that imports `paddleocr`. It builds the
  pipeline from the resolved settings and turns its result into `OcrWord`s. The import is
  deferred to the first call because the package is optional (spec 005's rule against
  deferred imports was for a dependency that became required).

### `OcrConfig`

| Field | Default | Meaning |
|---|---|---|
| `lang` | `"en"` | PaddleOCR `lang`. The text-layer check is English/Latin-script only, so other scripts will likely be rejected after OCR anyway. |
| `ocr_version` | `"PP-OCRv6"` | PaddleOCR `ocr_version` (v3 to v6). The default is the version the repo's OCR fixture used (medium models). Same on CPU and GPU. |
| `dpi` | `300` | Render resolution for OCR. Same as the fixture. Separate from the 150 dpi used for model images. |
| `device` | `"auto"` | `"auto"`, `"cpu"`, `"gpu"`, `"gpu:N"`, or any device string PaddleOCR takes. |
| `engine` | `None` | PaddleOCR `engine`. `None` leaves PaddleOCR's default (PaddlePaddle). Other values (`"transformers"`, `"onnxruntime"`) are passed through; the user installs that runtime, and gridkey neither tests nor supports it. |
| `cpu_threads` | `None` | CPU threads; `None` leaves PaddleOCR's default. |
| `min_confidence` | `0.0` | Words scoring below this are dropped (`text_rec_score_thresh`). Default keeps everything: a dropped real word makes a cell `ungrounded`, a kept wrong word is caught by the check or the grounding. |
| `text_detection_model` / `text_recognition_model` | `None` | Model names, to pick a smaller or larger model. PP-OCRv6 has medium, small and tiny; medium is the default. |
| `model_dir` | `None` | Directory holding already-downloaded models, for offline use. |
| `paddleocr_options` | `{}` | Extra keyword arguments for the `PaddleOCR(...)` constructor. |
| `predict_options` | `{}` | Extra keyword arguments for `predict(...)` (for example `text_det_limit_side_len`). |

Validated when the config is built: `dpi` outside 72 to 600 and `paddleocr_options` that turn
on `use_doc_orientation_classify` or `use_doc_unwarping` (see Limits) raise `ValueError` with
the reason.

### Coordinates

Everything downstream works in the units `load_layer` produces: points, upright page space.
The page is rendered with `page.get_pixmap(dpi=...)`, which already applies the page's
rotation, so an OCR box in pixels converts with `points = pixels * 72 / dpi`, and no extra
rotation matrix is needed. A test checks this against a born-digital PDF (the OCR'd words must
land on the native words' boxes).

### Words

The layer needs word boxes (grounding and the position check use them). PaddleOCR returns
line boxes by default and word boxes with `return_word_box=True`; gridkey asks for word boxes.
If the engine returns only a line, the line is split on whitespace and its box divided in
proportion to character counts. The exact result keys for word boxes are not yet confirmed
against an installed PaddleOCR (task 001 checks them).

### Hardware

Only NVIDIA GPUs and the CPU are supported. PaddleOCR 3.7 runs on PaddlePaddle by default, and
PaddlePaddle's pip wheels come in a CPU build and NVIDIA CUDA builds.

With `device="auto"`:

1. If the installed PaddlePaddle is compiled with CUDA and reports at least one device, use
   `gpu:0`. Otherwise use `cpu`. This is what PaddleOCR does on its own; gridkey resolves it
   itself so it can log the choice and fall back (requirement 8).
2. If an NVIDIA GPU is present on the machine (`/dev/nvidia*`, or `nvidia-smi` on `PATH`; file
   and `PATH` checks only, no subprocess) but PaddlePaddle cannot use it, run on the CPU and log
   one warning that says why (CPU-only build, or a GPU build that finds no device) and gives
   the GPU install command. A CPU wheel on a GPU machine is the common case, so the warning is
   the feature here, not an error.
3. An explicit `device` skips step 1. An impossible request (`device="gpu"` with a CPU-only
   PaddlePaddle) raises `OcrUnavailableError` saying so.

`CUDA_VISIBLE_DEVICES` keeps working because PaddlePaddle honours it. Apple Silicon is
CPU-only: PaddlePaddle has no Apple GPU backend. When `engine` is not the PaddlePaddle default,
`auto` passes no device and PaddleOCR decides. The chosen device and the reason are logged at
INFO on the `gridkey.ocr` logger.

### Dependencies

Facts checked on PyPI on 2026-10-16:

- `paddleocr` 3.7.0 is a small pure-Python wheel (about 3 MB). It requires `paddlex[ocr-core]`
  but does **not** require PaddlePaddle, so installing it alone gives no inference engine.
- `paddlepaddle` (CPU) 3.3.1 is on PyPI, as three wheels per Python version: macOS arm64
  (about 104 MB), Linux x86_64 (about 195 MB) and Windows x86_64 (about 105 MB), for Python 3.9
  to 3.13. There is no wheel for Intel Macs, Linux ARM, or (in the list checked) Python 3.14.
- `paddlepaddle-gpu` on PyPI is stuck at 2.6.2, too old for PaddleOCR 3. Current GPU wheels are
  only on Paddle's own package index, one per CUDA version, so they cannot be pinned in
  gridkey's metadata.
- `paddlex[ocr-core]` adds `opencv-contrib-python==4.10.0.84` (exact pin), `shapely`,
  `pyclipper`, `pypdfium2`, `imagesize`, `python-bidi`, and, from paddlex itself, `pandas`,
  `numpy<2.4`, `modelscope`, `huggingface-hub`, `PyYAML==6.0.2` (exact pin) and others.
- Resolution check (`uv pip compile`, Python 3.11, with gridkey's current pins plus
  `paddleocr==3.7.0` and `paddlepaddle==3.3.1`, also with `--universal`): resolves with no
  conflict and no torch. It is `uv pip compile`, not `uv lock`; task 001 runs `uv lock`.

Two optional extras (not exclusive, nothing added to the base install):

```
gridkey[ocr]       paddleocr==3.7.0 + paddlepaddle==3.3.1 (CPU)   complete, one command
gridkey[ocr-core]  paddleocr==3.7.0 only                          you bring the PaddlePaddle build
```

Install recipes the README carries:

```bash
# CPU (macOS arm64, Linux x86_64, Windows): one command
pip install "gridkey[ocr]"

# NVIDIA GPU (Linux or Windows): the core extra, then the GPU build of PaddlePaddle
pip install "gridkey[ocr-core]"
pip install paddlepaddle-gpu==<tested version> -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
#   cu126 needs NVIDIA driver >= 550.54.14, cu118 needs >= 450.80.02 (per PaddleOCR's docs);
#   you need the driver, not the CUDA toolkit
```

Why there is no `gpu` extra, and why there are two: an extra cannot install the GPU build,
because extras only add packages, the current GPU wheels live only on Paddle's own index
(which a PyPI package's metadata cannot name), and the CPU and GPU wheels both provide the
`paddle` package, so pip treats them as unrelated and they overwrite each other's files. A
single `ocr` extra that includes the CPU wheel would make every GPU user uninstall it first
(and a later `pip install -U gridkey[ocr]` would put it back). `ocr-core` is the clean base
for GPU users; `ocr` is the one-line path for everyone else.

No environment markers: the extra is something the user asks for, so on a platform with no
PaddlePaddle wheel (Intel Mac, Linux ARM, Python 3.14) pip fails loudly at install, which is
the right moment to learn it.

Task 001 decides: the exact version pair to pin and test (the docs show `paddlepaddle` 3.2.0
for the GPU recipe, PyPI has 3.3.1 for CPU); whether `--extra-index-url` works as well as `-i`
for the GPU wheel, so the other dependencies still come from PyPI; and the `uv` equivalent (a
user-side explicit index plus `[tool.uv.sources]`).

Project changes: `pyproject.toml` gets the two extras and the dev group lists `paddleocr` and
`paddlepaddle` directly, so `uv sync` gives `ty` the imports and lets the real-OCR tests run
on the CPU. No `[tool.uv] conflicts` is needed. Total installed size and import time are not
yet measured (task 001).

## Limits

- **No GPU on this machine.** The development machine is a Mac, which has no NVIDIA GPU. GPU
  paths are tested with fakes only; a real NVIDIA run needs someone with the hardware (the
  manual checklist in Tests).
- **Page orientation and unwarping are off and not configurable.** They change the image
  geometry, so OCR boxes would no longer line up with the page the model sees. A sideways scan
  with no `/Rotate` flag stays sideways; this is the existing "page orientation" gap in the
  README. (Text-line orientation does not change geometry and can be set.)
- **OCR text has errors, and they can reach the output.** Recheck defers to the text layer
  (spec 002), so a misread in the OCR layer can override a correct model answer. The fixture
  already shows every thousands comma read as a period. `Table.ocr_pages` makes this visible;
  it does not fix it.
- **Results may differ by device.** CPU and GPU runs of the same model can differ in rare
  low-confidence words. The OCR cache key leaves the device out, so a cached result is reused
  across devices; this is deliberate (one answer per document) and stated here.
- **Models are PaddleOCR's business.** PaddleOCR downloads its models the first time (about
  130 MB for the default medium detection and recognition pair, by its published sizes) to its
  own storage location, from a model host it chooses. gridkey only triggers this when OCR is
  needed and a page misses the cache. Air-gapped use needs `model_dir`.
- **The cache holds document content.** `.gridkey/` contains the model's extracted table
  values (model-answer files) and the OCR'd text of bad pages, both derived from the PDF. It
  is kept out of git by its own `.gitignore`, but it is on disk in whatever directory gridkey
  was run from; delete it when the data is sensitive.
- **A new folder in the working directory.** Running gridkey creates `.gridkey/` wherever it
  is run from. A relative `cache_dir` is relative to the working directory too.
- **Stale or shared caches.** Nothing expires. A changed PDF has a different hash, so it never
  reads another file's OCR pages; model answers are keyed by their full request.
- **Speed.** CPU OCR at 300 dpi is slow for long documents (the cache means once). The knobs
  are `dpi`, smaller models and `cpu_threads`; no figure is claimed until task 001 measures one.
- **Platforms.** The OCR extras install only where PaddlePaddle publishes a wheel: macOS
  arm64, Linux x86_64, Windows x86_64, Python 3.11 to 3.13. Elsewhere (Intel Macs, Linux ARM,
  Python 3.14) gridkey installs without OCR and a document that needs it is rejected as
  before.
- English and Latin-script only, as the check is (spec 001).
- Born-digital pages with a good layer are never touched, even if a human would prefer OCR.

## Out of scope

- AMD GPUs and any accelerator other than NVIDIA CUDA (user decision). The `engine` field
  passes other PaddleOCR engines through, but they are not supported or tested.
- A default model that depends on the device, and a `model_size` shortcut (user decision:
  model switching is the user's).
- Writing a searchable PDF (`ocrmypdf`-style output), or saving the OCR layer anywhere except
  the cache.
- A switch to force OCR on a document that passes the check.
- OCR engines other than PaddleOCR. The `OcrEngine` protocol is internal, so another engine
  would be a later spec.
- Orientation correction, unwarping, deskew, and layout/table models from PaddleOCR
  (PP-StructureV3, PaddleOCR-VL). gridkey uses PaddleOCR for text and boxes only.
- Multi-GPU use, batching pages across processes, automatic installation of GPU wheels, cache
  expiry or cleanup commands, and a way to turn caching off.
- Changing the text-layer thresholds or the trigram reference.

## Tests

Offline tests (default `just test`; no PaddleOCR, GPU or network):

- `assess_text_layers`: bad pages are the garbled plus empty ones; `check_text_layers`
  behaves as before (existing textcheck tests unchanged).
- Pipeline with a fake `OcrEngine`:
  - the garbled Senate PDF with a fake engine that returns the words of the OCR'd fixture is
    accepted, the fake client receives its first request only after OCR, and
    `Table.ocr_pages` lists the OCR'd pages;
  - a no-text PDF is rescued the same way;
  - a mixed PDF (good native pages plus garbled ones, garbled share above 10%) OCRs only the
    bad pages and keeps the others' native layers;
  - an accepted PDF never calls the engine and never imports PaddleOCR;
  - OCR that returns noise leads to `TextLayerError` mentioning OCR, with zero client
    requests; `ocr=False` gives the old message; PaddleOCR not importable (blocked in the
    test) gives `OcrUnavailableError` whose message contains the `gridkey[ocr]` install
    command; it is also a `TextLayerError`.
- Coordinates: a fake engine that reports a known pixel box on a rotated page yields the
  expected point box in the `Layer`.
- Word splitting when only a line box is returned.
- OCR cache: a second run makes zero engine calls; changing `dpi`, `lang` or a model name
  misses; the device does not; a corrupt file is a miss and is rewritten; different PDFs never
  see each other's pages; a populated cache rescues the document with the engine and PaddleOCR
  absent.
- Default cache location: with no `cache_dir`, model answers and `ocr/` files appear in
  `./.gridkey/` (the test changes into a temp directory first) and `.gridkey/.gitignore`
  holds `*`; a second run makes no model request; with `cache_dir`, everything appears there,
  nothing is created in the working directory, and no `.gitignore` is added; an unwritable
  directory raises `OSError` naming the path.
- Existing `test_entrypoint` tests change meaning: "a second run with a cache_dir makes no
  request" becomes "a second run makes no request, with or without `cache_dir`", and
  `max_requests` is tested with the default and with an explicit directory. `test_llm` cases
  that built `CachedClient` with `None` pass a temp directory.
- A conftest fixture runs every offline test in a temp working directory, so no test writes
  `.gridkey/` into the repo.
- Device selection over a table of `Capabilities` values: CUDA build with a device, CUDA
  build with none, CPU build on a machine with `/dev/nvidia0`, nothing installed, explicit
  `cpu`, explicit impossible `gpu`; the warning names the cause and the install.
- GPU failure with `auto` falls back to CPU once and logs a warning; an explicit device
  re-raises.
- `OcrConfig` validation errors.
- `extract_tables_async` does not block the loop (the fake engine sleeps; a concurrent task
  keeps ticking).
- Existing rejection tests pass `ocr=False` (they are about the old rejection path).
- `gridkey.__all__` gains `OcrConfig` and `OcrUnavailableError`.

Opt-in real-OCR tests (`@pytest.mark.ocr`, deselected by default, `just test-ocr`; they run
the real models, need the first-run model download, and cost no money):

- Garbled Senate PDF: OCR rescues it, the second check passes, no client request before OCR.
- The same pages rasterised into an image-only PDF (built in the test): rescued.
- Alignment: on `fy22_ag_house_original.pdf`, OCR'd word boxes land on the native words'
  boxes within a stated tolerance (this checks the points conversion on a real page).
- Word-box result keys exist as assumed.
- The NVIDIA path has no automated test. A manual checklist in `tests/data/README.md` records
  who ran what on which card.

## Docs

- `README.md`: replace "Requires a readable text layer" with the new behaviour; the two
  extras and install recipes (CPU, NVIDIA), and when the default install is enough; the
  `ocr=` argument; the `.gridkey/` cache and `cache_dir`; the first-run model download. The
  example comment "optional: cache model answers on disk" changes, since caching is no longer
  optional.
- `AGENTS.md`: project state (spec 006), file tree (`ocr.py`, `cache.py`, `ocr_cache.py`,
  `ocr_device.py`, `_paddle.py`), commands table (`just test-ocr`).
- `justfile`: `test-ocr`. `pyproject.toml`: the two extras, dev group, `ocr` pytest marker.
  Repo `.gitignore`: `.gridkey/`.
- `llm.py`, `textcheck.py` and `extract.py` module docstrings: caching is always on; the
  rejection is now "after OCR".
- Specs 001, 002 and 005 are history and are not edited. This spec supersedes 001's "Out of
  scope: running OCR inside this library" and 005's "`cache_dir=None` means no caching" (and
  its "default on-disk cache is a later spec").

## Open questions

None.

Resolved by the user:

- OCR is an optional extra: the default install has no OCR, and the rejection error tells you
  to install it. Two extras (`ocr` for CPU, `ocr-core` for NVIDIA users who bring their own
  PaddlePaddle build); no `gpu` extra.
- OCR only bad pages (no text, or garbled).
- The same default model on CPU and GPU; switching is the user's job, no `model_size` field.
- AMD GPU support is dropped from this spec.
- Always cache, to `.gridkey/` in the current directory unless `cache_dir` is given, for
  model answers as well as OCR; no in-memory mode.
- Model downloads are left to PaddleOCR.

## Differences found in implementation

The probe is in `probe.md`. Where the spec and what was built differ:

- **`model_dir`** is not a PaddleOCR argument (PaddleOCR takes one directory per model). In
  `OcrConfig` it is a folder with one subfolder per model, named like the model (the layout of
  `~/.paddlex/official_models`). Because the subfolder names are the model names, `OcrConfig`
  raises `ValueError` if `model_dir`, or one model name, is given and the other name is not
  known (gridkey knows the `lang="en"` names for PP-OCRv3 to v6). Checked against the real
  models in `tests/ocr`.
- **Word boxes** (`text_word`, `text_word_boxes`) carry no per-word score, include the spaces
  between words as entries of their own, and also split at punctuation: `$15,142,000.00` comes
  as `'$', '15', ',', '142', ',', '000.00'` and `SALARIES, OFFICERS` as `'SALARIES', ', ',
  'OFFICERS'`. The adapter joins pieces until whitespace (a word is a run of pieces with none
  between them) and gives each word its line's score and the union of its pieces' boxes. This
  was found only by the live run: the first version kept every piece as a word, which broke
  every number with a thousands comma and made the band search for the page's first row fail.
- **The OCR cache key** uses the model names from the config when set, and otherwise relies on
  `lang`, `ocr_version` and the PaddleOCR version (all in the key) to decide the default models,
  so it needs no table of default model names.
- **`ocr_pages`** lives in `gridkey/ocr_pages.py`, not `ocr.py`, because it uses the OCR cache,
  which imports `ocr.py`.
- **The default pipeline also loads PaddleOCR's text-line orientation model** (6.6 MB, on by
  default in PaddleOCR; it rotates single lines, not pages), so the first-run download is about
  140 MB rather than 130 MB.
- **CPU speed:** about 55 s for one full page at 300 dpi on an Apple Silicon Mac (default
  `cpu_threads`).
- **`paddlepaddle-gpu` 3.3.1** exists on Paddle's cu126 index for the CPU pin's version (the docs'
  example says 3.2.0); `--extra-index-url` resolves as well as `-i`. Resolved with `uv pip
  compile`, not installed.
- **Real-OCR tests** cannot use the recorded discovery answer of the Senate PDF: its first and
  last row text is spelled as the hand-made OCR copy has it, and a fresh OCR run spells some of it
  differently, so the page-1 bands cannot be found. They replay the detail table alone instead.
