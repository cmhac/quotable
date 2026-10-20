"""
The PaddleOCR adapter: the only module that imports ``paddleocr``.

``PaddleEngine`` implements :class:`quotable.ocr.config.OcrEngine`. Building it imports nothing; the
first ``recognize`` does the work (import PaddleOCR, detect the hardware, choose the device,
build the pipeline), so a run whose pages are all in the OCR cache never gets here. An
automatically chosen GPU that fails on the first page is replaced by the CPU, once; an
explicitly requested device is never retried.

The device it runs on (:func:`choose_device`, at the end of this module) is the CPU, or an
NVIDIA GPU when one can be used. The decision is a pure function of what the machine can do
(:class:`Capabilities`), so it is tested without a GPU, PaddlePaddle or a network.
:func:`detect_capabilities` fills the description in, and imports ``paddle`` only inside a
``try``: it is called only when a page misses the OCR cache. Only NVIDIA GPUs and the CPU are
supported; an AMD machine runs on the CPU.
"""

import logging
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from quotable.errors import OcrUnavailableError
from quotable.ocr.config import TEXTLINE_ORIENTATION_MODEL, OcrConfig, OcrWord

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
        caps = detect_capabilities()
        if not caps.paddle_installed and self.config.engine in PADDLE_ENGINES:
            raise _no_paddlepaddle()
        self.choice = choose_device(self.config.device, self.config.engine, caps)
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


PADDLE_ENGINES = (None, "paddle", "paddle_static", "paddle_dynamic")  # run on PaddlePaddle
GPU_INSTALL = (
    "To use the GPU, install `quotable[ocr-core]` and a GPU build of PaddlePaddle "
    "(see 'OCR on an NVIDIA GPU' in the README)."
)


@dataclass(frozen=True)
class Capabilities:
    """What this machine and environment can do."""

    paddle_installed: bool
    paddle_cuda_build: bool  # the installed PaddlePaddle is compiled with CUDA
    paddle_cuda_devices: int  # CUDA devices that PaddlePaddle can see
    nvidia_present: bool  # an NVIDIA GPU is on the machine (/dev/nvidia* or nvidia-smi)


@dataclass(frozen=True)
class Choice:
    """The device to use (``None``: let PaddleOCR decide), why, and a warning to log."""

    device: str | None
    reason: str
    warning: str | None = None
    automatic: bool = False  # chosen by "auto", so a GPU failure may fall back to the CPU

    @property
    def is_gpu(self) -> bool:
        """Return whether the chosen device is a GPU."""
        return self.device is not None and self.device.startswith("gpu")


def _gpu_problem(caps: Capabilities) -> str | None:
    if not caps.paddle_installed:
        return "PaddlePaddle is not installed"
    if not caps.paddle_cuda_build:
        return "the installed PaddlePaddle is a CPU-only build"
    if caps.paddle_cuda_devices < 1:
        return "the installed PaddlePaddle is a GPU build but cannot see a CUDA device"
    return None


def choose_device(requested: str, engine: str | None, caps: Capabilities) -> Choice:
    """
    Return the device to run OCR on.

    ``"auto"`` uses ``gpu:0`` when PaddlePaddle is a CUDA build that sees a device, else the
    CPU; if an NVIDIA GPU is present but unusable it chooses the CPU and warns, naming the
    cause. An explicit device is returned as given, except a GPU that cannot work with the
    installed PaddlePaddle, which raises ``OcrUnavailableError``. With an engine that does
    not run on PaddlePaddle, ``"auto"`` passes no device and PaddleOCR decides.
    """
    if engine not in PADDLE_ENGINES:
        if requested == "auto":
            return Choice(None, f"engine {engine!r} chooses its own device")
        return Choice(requested, f"device {requested!r} was requested")
    if requested != "auto":
        problem = _gpu_problem(caps) if requested.startswith("gpu") else None
        if problem is not None:
            msg = f"device={requested!r} was requested but {problem}. {GPU_INSTALL}"
            raise OcrUnavailableError(msg)
        return Choice(requested, f"device {requested!r} was requested")
    problem = _gpu_problem(caps)
    if problem is None:
        return Choice(
            "gpu:0",
            f"PaddlePaddle sees {caps.paddle_cuda_devices} CUDA device(s)",
            automatic=True,
        )
    if caps.nvidia_present and caps.paddle_installed:
        warning = (
            f"An NVIDIA GPU was found but {problem}, so OCR runs on the CPU (slow). {GPU_INSTALL}"
        )
        return Choice("cpu", problem, warning, automatic=True)
    return Choice("cpu", "no usable GPU", automatic=True)


def nvidia_device_files() -> list[Path]:
    """Return the NVIDIA device files (``/dev/nvidia*``), if any."""
    return list(Path("/dev").glob("nvidia*"))


def detect_capabilities() -> Capabilities:
    """
    Describe this machine. Never raises: a failed probe means "not installed" / "no device".

    Imports ``paddle`` (slow, about a second) and looks for ``/dev/nvidia*`` or ``nvidia-smi``
    on ``PATH``; no subprocess is started.
    """
    nvidia = bool(nvidia_device_files()) or shutil.which("nvidia-smi") is not None
    try:
        import paddle  # noqa: PLC0415  (optional dependency, imported only when needed)

        cuda_build = bool(paddle.device.is_compiled_with_cuda())
        devices = int(paddle.device.cuda.device_count()) if cuda_build else 0
    except Exception:  # noqa: BLE001  (any failure to probe means "cannot use it")
        return Capabilities(False, False, 0, nvidia)
    return Capabilities(True, cuda_build, devices, nvidia)
