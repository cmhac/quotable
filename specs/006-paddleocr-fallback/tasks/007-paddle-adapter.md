# 007 - The PaddleOCR adapter

Spec: `../spec.md` (Requirements 6, 8, 9, 14; Design / Modules `_paddle.py`, Words, Limits).
Depends on: tasks 001, 004, 006.

## Goal

`_paddle.py` is the only module that imports `paddleocr`. It turns an `OcrConfig` into a
working engine (`OcrEngine`), picks the device, falls back from an auto-chosen GPU to the CPU
once, and returns `OcrWord`s. It is tested against a fake `paddleocr` module, and for real in
task 010.

## Steps

1. New `src/gridkey/_paddle.py` with `PaddleEngine(config: OcrConfig)` implementing
   `OcrEngine`. Constructing it imports nothing; the first `recognize` call does the work, so a
   run whose pages are all cached never imports PaddleOCR or chooses a device.
2. On first use:
   - `import paddleocr` inside a `try`; on `ImportError` raise `OcrUnavailableError` whose
     message gives `pip install "gridkey[ocr]"`, the NVIDIA pointer, and (when the platform is
     one PaddlePaddle has no wheel for: Intel Mac, Linux ARM, Python 3.14) a sentence saying so
     and suggesting OCR'ing the PDF yourself. A missing `paddle` (the `ocr-core` extra without a
     PaddlePaddle build) gets its own message naming the missing package.
   - Call `ocr_device.detect_capabilities()` and `choose_device(...)`; log the choice and the
     reason at INFO on the `gridkey.ocr` logger and the warning (if any) at WARNING.
   - Build the pipeline with `lang`, `ocr_version`, the model names, `model_dir`, `device`,
     `engine`, `cpu_threads`, the score threshold, document orientation and unwarping explicitly
     off, text-line orientation as PaddleOCR defaults, and word boxes on, using the argument
     names in `probe.md`. `paddleocr_options` is applied last on the constructor, and
     `predict_options` on `predict`.
3. `recognize(png)`: decode the PNG to the array type `predict` takes, call `predict`, convert
   the result to `OcrWord`s using the keys in `probe.md` (pixels, `(x0, y0, x1, y1)` from the
   polygon's bounds). If the result has lines but no word boxes, return the lines as words
   (task 004 splits them). Apply no confidence filtering here; `words_to_layer` does.
4. GPU fallback: if the device came from `auto` and was a GPU, and building the pipeline or the
   first `recognize` raises, log a WARNING with the error, rebuild on `cpu`, and retry that page
   once. Later failures are not retried. An explicit device is never retried; its error is
   raised, as an `OcrUnavailableError` with the original as `__cause__` for load failures that
   are about the device and as the original error otherwise.
5. The fake module for tests lives in `tests/` (a small fixture that puts a fake `paddleocr`
   and `paddle` in `sys.modules`), shaped like the real result from `probe.md`. Tests in
   `tests/test_paddle_adapter.py`: nothing imported at construction; first call imports; the
   constructor receives the expected arguments for the default config and for a fully
   customised one (including passthrough options and that orientation/unwarping are off);
   result conversion to `OcrWord`s, including a line-only result; `ImportError` gives
   `OcrUnavailableError` with the install command; auto GPU failure retries on CPU once and
   warns; explicit GPU failure raises without retry; a second `recognize` reuses the pipeline.
6. `ruff check`, `ruff format`, `ty check`, `just test`. If `ty` needs `paddleocr` types it
   cannot find, use a narrow `# type: ignore[...]` on the import with a comment, not a
   blanket ignore.

## Done when

The fake-module tests pass, no other module imports `paddleocr` (`grep -rn "import paddle"
src/` shows only `_paddle.py` and `ocr_device.py`'s guarded `paddle` probe), and importing
`gridkey` still does not import PaddleOCR.
