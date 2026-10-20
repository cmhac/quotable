"""A fake ``paddleocr`` and ``paddle`` for tests: shaped like the real ones (see probe.md)."""

import importlib.abc
import importlib.machinery
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cv2
import numpy
import pytest

from quotable.ocr import paddle as ocr_paddle


def png(width: int = 8, height: int = 8) -> bytes:
    """Return a small PNG (what the pipeline hands an engine)."""
    ok, encoded = cv2.imencode(".png", numpy.full((height, width, 3), 255, numpy.uint8))
    assert ok
    return encoded.tobytes()


def result(
    lines: list[tuple[str, float, tuple[int, int, int, int]]], *, words: bool = True
) -> dict:
    """
    A PaddleOCR result for ``lines`` of (text, score, box), with word boxes if ``words``.

    Words are the line split on spaces, each with a box of equal width, and the separating
    spaces are entries of their own, as the real result has them.
    """
    out: dict[str, Any] = {
        "rec_texts": [t for t, _, _ in lines],
        "rec_scores": [s for _, s, _ in lines],
        "rec_boxes": numpy.array([b for _, _, b in lines], dtype=numpy.int16).reshape(-1, 4),
    }
    if words:
        text_word, text_word_boxes = [], []
        for text, _, (x0, y0, x1, y1) in lines:
            parts: list[str] = []
            for i, word in enumerate(text.split(" ")):
                if i:
                    parts.append(" ")
                parts.append(word)
            step = (x1 - x0) / len(parts)
            text_word.append(parts)
            text_word_boxes.append(
                numpy.array(
                    [[x0 + i * step, y0, x0 + (i + 1) * step, y1] for i in range(len(parts))]
                )
            )
        out["text_word"] = text_word
        out["text_word_boxes"] = text_word_boxes
    return out


class FakePaddleOCR:
    """Records its constructor arguments and every predict call; answers from ``answer``."""

    instances: list["FakePaddleOCR"] = []  # noqa: RUF012
    answer: Callable[["FakePaddleOCR", Any], list[dict]] = staticmethod(lambda self, image: [])
    build_error: Callable[[dict], Exception | None] = staticmethod(lambda kwargs: None)

    def __init__(self, **kwargs: Any) -> None:  # noqa: ANN401
        self.kwargs = kwargs
        error = type(self).build_error(kwargs)
        if error is not None:
            raise error
        self.predictions: list[dict] = []
        type(self).instances.append(self)

    def predict(self, image: Any, **kwargs: Any) -> list[dict]:  # noqa: ANN401
        self.predictions.append({"shape": image.shape, "kwargs": kwargs})
        return type(self).answer(self, image)


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves the fake modules and counts how often they were imported."""

    def __init__(self, modules: dict[str, types.ModuleType]) -> None:
        self.modules = modules
        self.imported: list[str] = []

    def find_spec(self, name: str, path: object, target: object = None):  # noqa: ANN201, ARG002
        if name in self.modules:
            return importlib.machinery.ModuleSpec(name, self)
        return None

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> types.ModuleType:
        self.imported.append(spec.name)
        return self.modules[spec.name]

    def exec_module(self, module: types.ModuleType) -> None:
        return None


def _fake_paddle(cuda: bool, devices: int) -> types.ModuleType:
    paddle = types.ModuleType("paddle")
    paddle.device = types.SimpleNamespace(  # ty: ignore[unresolved-attribute]
        is_compiled_with_cuda=lambda: cuda,
        cuda=types.SimpleNamespace(device_count=lambda: devices),
    )
    return paddle


def install(  # noqa: PLR0913
    monkeypatch: pytest.MonkeyPatch,
    *,
    paddleocr: bool = True,
    paddle: bool = True,
    cuda: bool = False,
    devices: int = 0,
    nvidia: bool = False,
) -> _Finder:
    """Make ``import paddleocr`` / ``import paddle`` serve fakes (or fail), and reset them."""
    FakePaddleOCR.instances = []
    FakePaddleOCR.answer = staticmethod(lambda self, image: [])
    FakePaddleOCR.build_error = staticmethod(lambda kwargs: None)
    modules: dict[str, types.ModuleType] = {}
    if paddleocr:
        module = types.ModuleType("paddleocr")
        module.PaddleOCR = FakePaddleOCR  # ty: ignore[unresolved-attribute]
        modules["paddleocr"] = module
    if paddle:
        modules["paddle"] = _fake_paddle(cuda, devices)
    finder = _Finder(modules)
    for name in ("paddleocr", "paddle"):
        monkeypatch.delitem(sys.modules, name, raising=False)
        if name not in modules:
            monkeypatch.setitem(sys.modules, name, None)  # import raises ImportError
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])
    monkeypatch.setattr(
        ocr_paddle, "nvidia_device_files", lambda: [Path("/dev/nvidia0")] if nvidia else []
    )
    monkeypatch.setattr(ocr_paddle.shutil, "which", lambda name: None)
    return finder
