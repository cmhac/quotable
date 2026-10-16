"""
The PaddleOCR adapter: the only module that imports ``paddleocr``.

``PaddleEngine`` implements :class:`quotable.ocr.OcrEngine`. Building it imports nothing; the
first ``recognize`` does the work (import PaddleOCR, detect the hardware, choose the device,
build the pipeline), so a run whose pages are all in the OCR cache never gets here. An
automatically chosen GPU that fails on the first page is replaced by the CPU, once; an
explicitly requested device is never retried.
"""

import logging
import platform
import sys
from pathlib import Path
from typing import Any, NoReturn

from quotable import ocr_device
from quotable.ocr import TEXTLINE_ORIENTATION_MODEL, OcrConfig, OcrUnavailableError, OcrWord
from quotable.ocr_device import Choice

log = logging.getLogger("quotable.ocr")

INSTALL = 'pip install "quotable[ocr]"'
README_GPU = "for an NVIDIA GPU see 'OCR on an NVIDIA GPU' in the README"
OCR_YOURSELF = "OCR the PDF yourself (for example `ocrmypdf --force-ocr`) and try again"


def _no_wheel_note() -> str:
    """Say so if PaddlePaddle publishes no wheel for this platform (so the extra cannot install)."""
    system, machine = platform.system(), platform.machine().lower()
    supported = (
        (system == "Darwin" and machine == "arm64")
        or (system == "Linux" and machine in {"x86_64", "amd64"})
        or (system == "Windows" and machine in {"x86_64", "amd64"})
    )
    if sys.version_info >= (3, 14):
        return (
            f" PaddlePaddle publishes no wheel for Python {sys.version_info[0]}."
            f"{sys.version_info[1]}, so the extra cannot be installed here; {OCR_YOURSELF}."
        )
    if not supported:
        return (
            f" PaddlePaddle publishes no wheel for {system} {machine}, so the extra cannot be "
            f"installed here; {OCR_YOURSELF}."
        )
    return ""


def _not_installed() -> OcrUnavailableError:
    msg = (
        "This document needs OCR, but PaddleOCR is not installed. Install it with "
        f"`{INSTALL}` ({README_GPU}) and run again; no model request was made."
        f"{_no_wheel_note()}"
    )
    return OcrUnavailableError(msg)


def _no_paddlepaddle() -> OcrUnavailableError:
    msg = (
        "This document needs OCR, but PaddlePaddle (the inference engine) is not installed: "
        "the `quotable[ocr-core]` extra installs PaddleOCR only. Install a PaddlePaddle build "
        f"({README_GPU}), or use `{INSTALL}` for the CPU build."
    )
    return OcrUnavailableError(msg)


def _constructor_arguments(config: OcrConfig, device: str | None) -> dict[str, Any]:
    """Return the keyword arguments for ``PaddleOCR(...)`` (names confirmed in probe.md)."""
    detection, recognition = config.model_names()
    named = (
        config.model_dir is not None
        or config.text_detection_model
        or (config.text_recognition_model)
    )
    arguments: dict[str, Any] = {
        "use_doc_orientation_classify": False,  # these change the geometry (see OcrConfig)
        "use_doc_unwarping": False,
        "return_word_box": True,
        "text_rec_score_thresh": config.min_confidence,
    }
    if named:  # PaddleOCR ignores lang and ocr_version once a model is named
        arguments["text_detection_model_name"] = detection
        arguments["text_recognition_model_name"] = recognition
    else:
        arguments["lang"] = config.lang
        arguments["ocr_version"] = config.ocr_version
    if config.model_dir is not None:
        root = Path(config.model_dir)
        arguments["text_detection_model_dir"] = str(root / str(detection))
        arguments["text_recognition_model_dir"] = str(root / str(recognition))
        orientation = root / TEXTLINE_ORIENTATION_MODEL
        if orientation.is_dir():
            arguments["textline_orientation_model_dir"] = str(orientation)
    if device is not None:
        arguments["device"] = device
    if config.engine is not None:
        arguments["engine"] = config.engine
    if config.cpu_threads is not None:
        arguments["cpu_threads"] = config.cpu_threads
    arguments.update(config.paddleocr_options)
    return arguments


def _decode(png: bytes) -> Any:  # noqa: ANN401  (a numpy array; numpy is a PaddleOCR dependency)
    import cv2  # noqa: PLC0415
    import numpy  # noqa: PLC0415

    image = cv2.imdecode(numpy.frombuffer(png, numpy.uint8), cv2.IMREAD_COLOR)
    if image is None:
        msg = "the rendered page could not be decoded as a PNG"
        raise ValueError(msg)
    return image


def _box(values: Any) -> tuple[float, float, float, float]:  # noqa: ANN401
    x0, y0, x1, y1 = (float(v) for v in values)
    return (x0, y0, x1, y1)


def _join_pieces(
    pieces: list[str],
    boxes: Any,  # noqa: ANN401
) -> list[tuple[str, tuple[float, float, float, float]]]:
    """
    Join a line's pieces into words: a word is a run of pieces with no whitespace between them.

    PaddleOCR splits at punctuation as well as at spaces, so ``$15,142,000.00`` arrives as
    ``['$', '15', ',', '142', ',', '000.00']`` and ``SALARIES, OFFICERS`` as ``['SALARIES',
    ', ', 'OFFICERS']`` (a piece may carry the space that follows it). Keeping every piece as a
    word would break numbers at their thousands commas and so fail grounding.
    """
    words: list[tuple[str, tuple[float, float, float, float]]] = []
    text = ""
    box: tuple[float, float, float, float] | None = None

    def flush() -> None:
        nonlocal text, box
        if box is not None and text:
            words.append((text, box))
        text, box = "", None

    for piece, raw in zip(pieces, boxes, strict=True):
        if piece[:1].isspace():
            flush()
        if piece.strip():
            b = _box(raw)
            text += piece.strip()
            box = (
                b
                if box is None
                else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
            )
        if piece[-1:].isspace():
            flush()
    flush()
    return words


def result_words(result: Any) -> list[OcrWord]:  # noqa: ANN401
    """
    Turn one PaddleOCR result into words, in pixels of the image passed in.

    With word boxes, ``text_word[i]`` lists line ``i``'s words (and the spaces between them)
    and ``text_word_boxes[i]`` their ``[x0, y0, x1, y1]`` boxes, one to one; there is no
    per-word score, so a word takes its line's. A line without word boxes is returned whole.
    """
    texts = result.get("rec_texts") or []
    scores = result.get("rec_scores") or []
    line_boxes = result.get("rec_boxes")
    line_boxes = [] if line_boxes is None else line_boxes
    pieces = result.get("text_word") or []
    piece_boxes = result.get("text_word_boxes") or []
    words: list[OcrWord] = []
    for i, text in enumerate(texts):
        score = float(scores[i]) if i < len(scores) else 0.0
        if i < len(pieces) and i < len(piece_boxes) and len(pieces[i]) == len(piece_boxes[i]):
            words.extend(
                OcrWord(word, box, score) for word, box in _join_pieces(pieces[i], piece_boxes[i])
            )
        elif text.strip() and i < len(line_boxes):
            words.append(OcrWord(text, _box(line_boxes[i]), score))
    return words


class PaddleEngine:
    """An ``OcrEngine`` backed by PaddleOCR; nothing is imported until the first page."""

    def __init__(self, config: OcrConfig) -> None:
        """Remember the configuration; do no work."""
        self.config = config
        self.choice: Choice | None = None
        self._pipeline: Any = None
        self._succeeded = False

    @property
    def description(self) -> str:
        """Return the engine and device, for messages."""
        device = self.choice.device if self.choice and self.choice.device else "its default device"
        return f"PaddleOCR ({self.config.ocr_version}) on {device}"

    def recognize(self, png: bytes) -> list[OcrWord]:
        """Return the words on a rendered page; on first use import, choose a device, build."""
        image = _decode(png)
        if self._pipeline is None:
            self._start()
        try:
            words = self._predict(image)
        except Exception as err:
            if not self._may_fall_back():
                self._fail(err)
            self._fall_back(err)
            words = self._predict(image)
        self._succeeded = True
        return words

    def _start(self) -> None:
        try:
            import paddleocr  # noqa: F401, PLC0415  (optional dependency)
        except ImportError as err:
            raise _not_installed() from err
        caps = ocr_device.detect_capabilities()
        if not caps.paddle_installed and self.config.engine in ocr_device.PADDLE_ENGINES:
            raise _no_paddlepaddle()
        self.choice = ocr_device.choose_device(self.config.device, self.config.engine, caps)
        log.info(
            "OCR device: %s (%s)", self.choice.device or "chosen by PaddleOCR", self.choice.reason
        )
        if self.choice.warning:
            log.warning(self.choice.warning)
        try:
            self._pipeline = self._build(self.choice.device)
        except Exception as err:
            if not self._may_fall_back():
                self._fail(err)
            self._fall_back(err)

    def _build(self, device: str | None) -> Any:  # noqa: ANN401
        from paddleocr import PaddleOCR  # noqa: PLC0415

        return PaddleOCR(**_constructor_arguments(self.config, device))

    def _predict(self, image: Any) -> list[OcrWord]:  # noqa: ANN401
        results = self._pipeline.predict(image, **dict(self.config.predict_options))
        return [word for result in results for word in result_words(result)]

    def _may_fall_back(self) -> bool:
        choice = self.choice
        return bool(choice and choice.automatic and choice.is_gpu and not self._succeeded)

    def _fall_back(self, err: Exception) -> None:
        log.warning("OCR on the GPU failed (%s); trying again on the CPU", err)
        self.choice = Choice("cpu", f"fell back from the GPU: {err}")
        self._pipeline = self._build("cpu")

    def _fail(self, err: Exception) -> NoReturn:
        """Re-raise ``err``; an explicitly requested GPU that fails to load is "unavailable"."""
        choice = self.choice
        if choice is not None and choice.is_gpu and not choice.automatic and not self._succeeded:
            msg = f"OCR could not run on the requested device {choice.device!r}: {err}"
            raise OcrUnavailableError(msg) from err
        raise err
