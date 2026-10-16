# 006 probe: PaddleOCR 3.7.0 / PaddlePaddle 3.3.1

Run on 2026-10-16 on the development Mac (Apple Silicon, macOS, Python 3.11.14, CPU only) with
`uv sync` from the new lock. "Verified" means run on this machine. "Resolved" means
`uv pip compile` found it, nothing was installed. "From the docs" means read, not run.

## Pins

`paddleocr==3.7.0` + `paddlepaddle==3.3.1` is a working pair (verified: real OCR ran). The GPU
counterpart `paddlepaddle-gpu==3.3.1` exists on Paddle's cu126 index for cp311 to cp313,
`linux_x86_64` and `win_amd64` (verified in the index page; not installed, no GPU here). The
docs page shows `3.2.0` in its examples, but 3.3.1 is listed, so the README recipe uses the
same version as the CPU pin.

## Install effect

| | before | after |
|---|---|---|
| `du -sh .venv/lib/python3.11/site-packages` | 313M | 1.0G |
| entries in `site-packages` | 201 | 273 |
| `uv pip list` lines | 100 | 131 |

No torch, triton, tensorflow or `nvidia-*` package is installed (`uv pip list | grep`). Packages
added include `paddlepaddle`, `paddleocr`, `paddlex` 3.7.2, `opencv-contrib-python` 4.10.0.84,
`numpy` 2.3.5, `pandas` 3.0.6, `shapely` 2.2.0, `modelscope`, `huggingface-hub` 1.18.0.
`uv lock` also moved `pyyaml` from 6.0.3 to 6.0.2 (PaddleX pins it exactly).

## Import time

`python -X importtime -c "import paddleocr"`: 0.69 s. `import paddle`: 0.70 s. `import gridkey`:
0.44 s, and `'paddleocr' in sys.modules` and `'paddle' in sys.modules` are both `False` after it.

## Result format (`PaddleOCR(...).predict(image, return_word_box=True)`)

Input: a file path or a BGR `numpy` array (`cv2.imread`); both verified. The call returns a
list with one `OCRResult` per image, a dict-like object. Keys: `input_path`, `page_index`,
`doc_preprocessor_res`, `dt_polys`, `model_settings`, `text_det_params`, `text_type`,
`text_rec_score_thresh`, `return_word_box`, `rec_texts`, `rec_scores`, `rec_polys`, `vis_fonts`,
`text_word`, `text_word_region`, `textline_orientation_angles`, `rec_boxes`, `text_word_boxes`.

- Line level: `rec_texts[i]` (str), `rec_scores[i]` (float), `rec_boxes[i]` (`[x0, y0, x1, y1]`),
  `rec_polys[i]` (4 points). All have one entry per line.
- Word level (only with `return_word_box=True`): `text_word[i]` is a list of strings for line `i`
  **including the separating spaces as their own `' '` entries**, and `text_word_boxes[i]` is an
  array of shape `(len(text_word[i]), 4)`, `[x0, y0, x1, y1]`, aligned one to one with
  `text_word[i]` (the space entries have a small box). `text_word_region[i]` holds the same boxes
  as 4-point tuples.
- Coordinates are pixels of the image passed in: a 300 dpi render of a 657.12 x 423.6 pt page is
  2738 x 1765 px, and the boxes fall inside that. So `points = pixels * 72 / dpi`.
- Example: line `'DETAILED AND SUMMARY STATEMENT OF EXPENDITURES'`, words
  `['DETAILED', ' ', 'AND', ...]` with boxes `[[1166, 30, 1331, 58], [1344, 30, 1348, 58], ...]`.
- The adapter therefore takes the words from `text_word` / `text_word_boxes`, skips entries that
  are only whitespace, and takes the score from the line (`rec_scores[i]`; there is no per-word
  score). If a line has no word entries it uses the line (`rec_texts[i]`, `rec_boxes[i]`).

## Argument names

Constructor (`PaddleOCR.__init__`, from `inspect.signature`): `lang`, `ocr_version`,
`text_detection_model_name`, `text_detection_model_dir`, `text_recognition_model_name`,
`text_recognition_model_dir`, `textline_orientation_model_name`,
`textline_orientation_model_dir`, `use_doc_orientation_classify`, `use_doc_unwarping`,
`use_textline_orientation`, `text_det_limit_side_len`, `text_det_limit_type`, `text_det_thresh`,
`text_det_box_thresh`, `text_det_unclip_ratio`, `text_det_input_shape`, `text_rec_score_thresh`,
`return_word_box`, `text_rec_input_shape`, and `**kwargs`. The kwargs are the common arguments in
`paddleocr/_common_args.py`: `device`, `engine`, `engine_config`, `enable_hpi`, `use_tensorrt`,
`precision`, `enable_mkldnn`, `mkldnn_cache_capacity`, `cpu_threads` (default 10),
`enable_cinn`. Any other name raises `ValueError: Unknown argument`.

`predict(input, *, use_doc_orientation_classify, use_doc_unwarping, use_textline_orientation,
text_det_limit_side_len, text_det_limit_type, text_det_thresh, text_det_box_thresh,
text_det_unclip_ratio, text_rec_score_thresh, return_word_box)`.

`engine` accepts `None`, `"paddle"`, `"paddle_static"`, `"paddle_dynamic"`, `"transformers"`,
`"onnxruntime"`; the first four run on PaddlePaddle.

Defaults that matter: a bare `PaddleOCR(lang="en")` has `use_doc_preprocessor=True` and
`use_textline_orientation=True`, so it also loads the document orientation model
(`PP-LCNet_x1_0_doc_ori`) and `UVDoc`. gridkey turns the first two off explicitly.

## Which models load

A bare `PaddleOCR(lang="en", device="cpu")` loads `PP-OCRv6_medium_det` and
`PP-OCRv6_medium_rec` (verified from the "Creating model" log and `ocr_version=None`). The model
names for `lang="en"` by version (from `PaddleOCR._get_ocr_model_names`, read in the source):

| `ocr_version` | detection | recognition |
|---|---|---|
| `PP-OCRv6` | `PP-OCRv6_medium_det` | `PP-OCRv6_medium_rec` |
| `PP-OCRv5` | `PP-OCRv5_server_det` | `en_PP-OCRv5_mobile_rec` |
| `PP-OCRv4` | `PP-OCRv4_mobile_det` | `en_PP-OCRv4_mobile_rec` |
| `PP-OCRv3` | `PP-OCRv3_mobile_det` | `en_PP-OCRv3_mobile_rec` |

The models are chosen from `(lang, ocr_version, paddleocr version)`, which are all in the cache
key, so the key does not need the resolved names; it uses the names only when the user sets them.
Passing a model name makes PaddleOCR ignore `lang` and `ocr_version` (it warns).

There is **no single `model_dir`** in PaddleOCR; each model has its own `*_model_dir`. gridkey's
`model_dir` therefore means a folder with one subfolder per model, named like the model, which is
the layout of `~/.paddlex/official_models/`.

## Downloads and timing

- Models live in `~/.paddlex/official_models/<model name>/`. Sizes on disk (`du -sh`):
  `PP-OCRv6_medium_det` 59M, `PP-OCRv6_medium_rec` 73M (together 132M, matching the spec's
  "about 130 MB"), `PP-LCNet_x1_0_textline_ori` 6.6M (loaded by default), plus 6.6M
  `doc_ori` and 31M `UVDoc` that gridkey does not load. `~/.paddlex` is 269M here because the
  fixture work downloaded other models earlier.
- **The models were already cached on this machine, so the first-download time was not
  measured.**
- `PaddleOCR(...)` construction: 1.3 s to 5.9 s with cached models.
- **One full 300 dpi page (2738 x 1765 px) takes about 55 s on this Mac's CPU** (first call
  55.4 s, second call 53.8 s; default `cpu_threads`). A 600-px-high strip of the same page took
  14 s. Not optimised.

## Paddle capability calls (CPU build, verified)

`paddle.__version__` is `'3.3.1'`; `paddle.device.is_compiled_with_cuda()` is `False`;
`paddle.device.cuda.device_count()` is `0`; `paddle.device.get_device()` is `'cpu'`. These work as
the spec assumes. The CUDA-build values are from the docs, not verified.

## NVIDIA install recipe (from the docs; not run)

- cu126: `pip install paddlepaddle-gpu==3.3.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/`,
  driver >= 550.54.14 (Linux and Windows).
- cu118: same with `.../cu118/`, driver >= 450.80.02 (Linux) or >= 452.39 (Windows).
- You need the driver, not the CUDA toolkit.
- NVIDIA 50-series on Windows needs specially built wheels (the docs link them); the normal
  wheels do not support them.
- `-i` replaces PyPI, so the other dependencies would not come from PyPI. `--extra-index-url`
  keeps PyPI: `uv pip compile` (Linux x86_64, Python 3.11) resolved `paddlepaddle-gpu==3.3.1` with
  both `--extra-index-url` and `-i` (resolved, not installed). So the README uses
  `--extra-index-url`. On this machine `uv` needed `--native-tls` to reach that host (its bundled
  certificates reported `UnknownIssuer`), and Python's `urllib` failed certificate verification
  there too; this looks specific to this network, and nothing was disabled.
- `uv` equivalent for a user: `uv pip install "gridkey[ocr-core]"` then
  `uv pip install paddlepaddle-gpu==3.3.1 --extra-index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/`
  (resolution verified; install not run). A `[tool.uv.sources]` entry with an explicit index
  for a project that depends on gridkey was not tried.
- `paddlepaddle-gpu` on PyPI is at 2.6.2 (verified against the PyPI JSON today).

## Differences from the spec

1. **`model_dir` is not a PaddleOCR argument.** PaddleOCR takes one directory per model. The
   plan: `OcrConfig.model_dir` is a folder with one subfolder per model, named like the model
   (the `~/.paddlex/official_models/` layout). The adapter passes `text_detection_model_dir`,
   `text_recognition_model_dir` and `textline_orientation_model_dir` from it, so it needs the
   model names: a small table for `lang="en"` (above), otherwise the user names the models;
   `OcrConfig` raises `ValueError` otherwise.
2. **Word boxes include the spaces** and have no per-word score. The adapter skips the
   whitespace entries and uses the line's score for its words.
3. **The OCR cache key does not need the resolved model names** (see above). It uses the names
   from the config when given.
4. **The textline orientation model is loaded by default** and adds about 6.6 MB to the
   download (about 139 MB total for the default models). Its default stays on: it rotates
   individual text lines, does not change page geometry, and the spec allows it.
5. **CPU speed is slow: about 55 s per page at 300 dpi.** The spec claimed no figure. The cache
   makes it a one-time cost; the real-OCR tests (task 010) will take minutes.
6. `paddlepaddle-gpu` 3.3.1 exists for the CPU pin's version, so the README recipe pins 3.3.1,
   not the 3.2.0 shown in the docs.
7. **`engine` values**: `None`, `"paddle"`, `"paddle_static"` and `"paddle_dynamic"` run on
   PaddlePaddle; `"transformers"` and `"onnxruntime"` do not. `device="auto"` passes no device
   only for the last two.
