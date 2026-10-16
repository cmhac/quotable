# 001 - The OCR extras, and a probe of PaddleOCR

Spec: `../spec.md` (Requirement 9; Design / Words, Hardware, Dependencies). Depends on: nothing.

## Goal

`pyproject.toml` has the two OCR extras and the dev group can run PaddleOCR on the CPU. The
facts the spec marks "task 001 decides" are settled by running things, and the later tasks
build on those facts instead of the spec's assumptions.

## Steps

1. `pyproject.toml`:
   - `[project.optional-dependencies]`: `ocr = ["paddleocr==3.7.0", "paddlepaddle==3.3.1"]` and
     `ocr-core = ["paddleocr==3.7.0"]`. If the probe in step 3 shows a different working pair,
     use that pair and say so in the report.
   - Dev dependency group: `paddleocr` and `paddlepaddle` at the same pins, so `uv sync` gives
     `ty` the imports and the real-OCR tests run on the CPU.
   - Do not add `[tool.uv] conflicts`, environment markers, or anything to `dependencies`.
2. `uv lock` (never edit `uv.lock` by hand), then `uv sync`. Check `uv pip list` for torch,
   triton, tensorflow and `nvidia-*`; if any is present, stop and tell the user.
3. Probe, in a scratch directory under `$KIROCREW_SCRATCH`, with `tests/data/` pages (render one
   page of `senate_expenditures_paddleocr.pdf` and one of `fy22_ag_house_original.pdf` to PNG
   with PyMuPDF at 300 dpi). Record, for each question, the answer and the command that gave it:
   - What `PaddleOCR(lang="en", ocr_version="PP-OCRv6", ...).predict(...)` returns, and the
     exact result keys for text, score and box. Which argument turns on word boxes
     (`return_word_box=True`?), the key that holds the word boxes, and their shape (4-point
     polygon or `[x0, y0, x1, y1]`). Whether the result is in pixels of the image passed in.
   - The constructor and `predict` argument names for: models (`text_detection_model_name`,
     `text_recognition_model_name`, or other), model directories, `device`, `cpu_threads`,
     `engine`, the score threshold (`text_rec_score_thresh`?), and turning off document
     orientation, unwarping (and which are on by default).
   - Whether a bare `PaddleOCR(...)` with the default `ocr_version` loads PP-OCRv6 medium, and
     the model names it resolved (needed for the cache key).
   - Where models are downloaded and their total size; time of a first run and a warm run of
     one page on this Mac's CPU (report, do not optimise).
   - `paddle.device.is_compiled_with_cuda()`, `paddle.device.cuda.device_count()` and
     `paddle.__version__` work as the spec assumes on the CPU build (these feed task 006).
   - Import time of `import paddleocr` and `import paddle` (`python -X importtime`).
   - From Paddle's install docs (read, do not install a GPU build): the exact `paddlepaddle-gpu`
     version for the CPU pin's counterpart, the index URL for cu126 and cu118, the driver
     minimums, and whether `--extra-index-url` works as well as `-i`. Mark anything not
     verified on a machine as "from the docs".
   - The `uv` recipe for a user to use the GPU wheel (an explicit index plus
     `[tool.uv.sources]` or `override-dependencies`); mark it verified or not.
4. Record the size of `.venv/lib/python*/site-packages` (`du -sh`) and the package count before
   and after, as spec 005 task 001 did.
5. Write the findings into a new `specs/006-paddleocr-fallback/probe.md` (the command, the
   answer, verified or "from the docs"). Where an answer differs from the spec, list it under
   "Differences from the spec" and tell the user; do not edit the spec.
6. Delete the scratch files.

## Done when

`uv sync` works from a clean lock, no heavy unwanted package appears, `probe.md` answers every
question above, and the report lists the differences from the spec.
