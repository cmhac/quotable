"""ocr_pages: cache first, render and recognise only on a miss, layers in points."""

from dataclasses import replace

import pymupdf
import pytest

from quotable.ocr import OcrConfig, OcrWord
from quotable.ocr_pages import ocr_pages
from quotable.text import load_layer
from tests.conftest import DATA
from tests.fake_ocr import FakeEngine, native_as_ocr

SENATE = DATA / "senate_expenditures_garbled.pdf"
ROTATED = DATA / "fy24_milcon_house_original.pdf"
UNROTATED = DATA / "fy22_ag_house_original.pdf"


class FailingEngine:
    def recognize(self, png: bytes) -> list[OcrWord]:
        msg = "engine crashed"
        raise RuntimeError(msg)


def words(text: str) -> list[OcrWord]:
    return [OcrWord(text, (10.0, 10.0, 200.0, 40.0), 0.9)]


def test_a_second_call_makes_no_engine_call_and_returns_equal_layers(tmp_path):
    config = OcrConfig()
    first = FakeEngine(words("alpha beta"), words("gamma"))
    layers = ocr_pages(SENATE, [1, 2], config, first, tmp_path)
    assert first.calls == 2
    second = FakeEngine()
    again = ocr_pages(SENATE, [1, 2], config, second, tmp_path)
    assert second.calls == 0
    assert {n: [w.text for w in layer.words] for n, layer in layers.items()} == {
        n: [w.text for w in layer.words] for n, layer in again.items()
    }
    assert [w.bbox for w in again[1].words] == [w.bbox for w in layers[1].words]


def test_changing_the_dpi_misses_the_cache(tmp_path):
    ocr_pages(SENATE, [1], OcrConfig(dpi=150), FakeEngine(words("a")), tmp_path)
    engine = FakeEngine(words("a"))
    ocr_pages(SENATE, [1], OcrConfig(dpi=200), engine, tmp_path)
    assert engine.calls == 1


def test_only_the_pages_asked_for_are_rendered_and_recognised(tmp_path):
    engine = FakeEngine(words("only"))
    layers = ocr_pages(SENATE, [2], OcrConfig(), engine, tmp_path)
    assert list(layers) == [2]
    assert engine.calls == 1
    assert len(list((tmp_path / "ocr").iterdir())) == 1


@pytest.mark.parametrize("dpi", [100, 300])
def test_the_page_is_rendered_at_the_configured_dpi(tmp_path, dpi):
    engine = FakeEngine(words("x"))
    ocr_pages(SENATE, [1], OcrConfig(dpi=dpi), engine, tmp_path)
    with pymupdf.open(SENATE) as document:
        rect = document[0].rect
    ((width, height),) = engine.png_sizes
    assert width == pytest.approx(rect.width * dpi / 72, abs=1)  # the pixmap rounds up
    assert height == pytest.approx(rect.height * dpi / 72, abs=1)


@pytest.mark.parametrize("pdf", [UNROTATED, ROTATED], ids=["unrotated", "rotated 90"])
def test_ocr_words_land_on_the_native_words_boxes(tmp_path, pdf):
    config = OcrConfig(dpi=300)
    engine = FakeEngine(native_as_ocr(pdf, 1, config.dpi))
    layer = ocr_pages(pdf, [1], config, engine, tmp_path)[1]
    with pymupdf.open(pdf) as document:
        native = load_layer(document[0])
    assert len(layer.words) == len(native.words) > 50
    for ocr_word, native_word in zip(layer.words, native.words, strict=True):
        assert ocr_word.text == native_word.text
        assert ocr_word.bbox == pytest.approx(native_word.bbox, abs=0.01)


def test_a_blank_page_gets_an_empty_layer_and_a_cache_file(tmp_path):
    engine = FakeEngine([])
    layers = ocr_pages(SENATE, [1], OcrConfig(), engine, tmp_path)
    assert layers[1].words == []
    assert len(list((tmp_path / "ocr").iterdir())) == 1
    again = FakeEngine()
    assert ocr_pages(SENATE, [1], OcrConfig(), again, tmp_path)[1].words == []
    assert again.calls == 0


def test_min_confidence_is_applied_to_the_cached_words(tmp_path):
    engine = FakeEngine(
        [OcrWord("sure", (0, 0, 50, 20), 0.9), OcrWord("doubt", (60, 0, 110, 20), 0.2)]
    )
    ocr_pages(SENATE, [1], OcrConfig(min_confidence=0.5), engine, tmp_path)
    layer = ocr_pages(SENATE, [1], OcrConfig(min_confidence=0.5), FakeEngine(), tmp_path)[1]
    assert [w.text for w in layer.words] == ["sure"]


def test_an_engine_error_propagates_and_leaves_no_cache_file_for_that_page(tmp_path):
    with pytest.raises(RuntimeError, match="engine crashed"):
        ocr_pages(SENATE, [1], OcrConfig(), FailingEngine(), tmp_path)
    assert not (tmp_path / "ocr").exists() or not any((tmp_path / "ocr").iterdir())


def test_pages_before_a_failure_stay_cached(tmp_path):
    class FailsOnSecond:
        calls = 0

        def recognize(self, png: bytes) -> list[OcrWord]:
            self.calls += 1
            if self.calls == 2:
                msg = "engine crashed"
                raise RuntimeError(msg)
            return words("kept")

    config = OcrConfig()
    with pytest.raises(RuntimeError):
        ocr_pages(SENATE, [1, 2], config, FailsOnSecond(), tmp_path)
    assert len(list((tmp_path / "ocr").iterdir())) == 1
    engine = FakeEngine(words("second"))
    ocr_pages(SENATE, [1, 2], replace(config), engine, tmp_path)
    assert engine.calls == 1  # only page 2 is recognised now
