"""
Tests that run the real PaddleOCR models on the CPU. They are slow (about a minute per full
page at 300 dpi), download the models on first use (about 140 MB, through PaddleOCR) and cost
no money: no model client is called. They are deselected by default (``-m 'not ocr'``).

Run them with:  just test-ocr
"""

import asyncio
import re
import time
from pathlib import Path

import pymupdf
import pytest

from gridkey import OcrConfig
from gridkey._paddle import PaddleEngine, _constructor_arguments, _decode, result_words
from gridkey.extract import run_pipeline, usable_layers
from gridkey.models import WindowTables
from gridkey.ocr import OcrWord
from gridkey.ocr_pages import ocr_pages
from gridkey.text import load_layer
from tests.conftest import DATA, FakeClient, replay
from tests.fake_ocr import ExplodingEngine
from tests.test_senate_tables import RECORDED

pytestmark = pytest.mark.ocr

GARBLED = DATA / "senate_expenditures_garbled.pdf"
HOUSE = DATA / "fy22_ag_house_original.pdf"
MODELS = Path.home() / ".paddlex" / "official_models"


class Timed:
    """Wraps an engine: records seconds per page and how many model requests came before."""

    def __init__(self, inner: PaddleEngine, client: FakeClient | None = None) -> None:
        self.inner = inner
        self.client = client
        self.seconds: list[float] = []
        self.requests_before: list[int] = []

    @property
    def description(self) -> str:
        return self.inner.description

    def recognize(self, png: bytes) -> list[OcrWord]:
        self.requests_before.append(0 if self.client is None else len(self.client.requests))
        started = time.perf_counter()
        words = self.inner.recognize(png)
        self.seconds.append(time.perf_counter() - started)
        return words


def detail_model() -> FakeClient:
    """A fake model that returns the recorded detail-table rows, whatever the OCR text says.

    The recorded discovery answer names the first and last row of each table as the hand-made
    OCR copy spelled them, which a fresh OCR run need not reproduce, so the two tables are not
    separated by band here: the model reports the detail table alone, on every page.
    """
    discovery = WindowTables.model_validate(RECORDED["discovery"])
    tables = [t for page in discovery.pages for t in page.tables if t.label == "Expenditure detail"]
    columns = [c.name for c in tables[0].columns]
    (detail,) = [t for t in RECORDED["tables"] if t["label"] == "Expenditure detail"]
    return replay(columns, {int(p): rows for p, rows in detail["pages"].items()})


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("ocr-cache")


@pytest.fixture(scope="module")
def rescued(cache: Path):
    """The garbled Senate PDF through the whole pipeline with the real OCR (once per run)."""
    client = detail_model()
    config = OcrConfig()
    engine = Timed(PaddleEngine(config), client)
    tables = asyncio.run(
        run_pipeline(GARBLED, client, recheck=False, ocr=engine, ocr_config=config, cache_dir=cache)
    )
    return client, engine, tables


def test_the_garbled_senate_pdf_is_rescued_before_any_model_request(rescued):
    client, engine, tables = rescued
    (detail,) = tables
    assert engine.requests_before == [0, 0, 0]  # OCR finished before the first request
    assert client.stages()[0] == "schema"
    assert detail.ocr_pages == (1, 2, 3)
    assert sum(len(r.rows) for r in detail.pages) == 124
    print(f"\nseconds per page on the CPU: {[round(s, 1) for s in engine.seconds]}")
    print(f"engine: {engine.description}")


def test_the_ocr_text_grounds_the_detail_table_except_for_the_known_comma_misreads(rescued):
    _, _, (detail,) = rescued
    rows = detail.rows()
    descriptions = [row.cells["DESCRIPTION"].status for row in rows]
    assert descriptions.count("exact") == len(rows)  # every description is read correctly
    # The OCR reads thousands commas as periods (68,027.74 -> 68.027.74), so many amounts are
    # ungrounded. Measured here: 61 of 124 ungrounded, 62 exact, 1 misplaced (the total row).
    ungrounded = [r for r in rows if r.cells["AMOUNT ($)"].status == "ungrounded"]
    misread = [
        r
        for r in ungrounded
        if r.values["AMOUNT ($)"].replace(",", ".")
        in " ".join(w.text for w in detail.layers[r.page].words)
    ]
    assert len(misread) >= 0.9 * len(ungrounded)
    exact = sum(r.cells["AMOUNT ($)"].status == "exact" for r in rows)
    assert len(rows) - exact - len(ungrounded) <= 2  # measured: 1 (misplaced)


def test_a_second_run_is_served_from_the_cache(rescued, cache):
    _ = rescued  # the first run has filled the cache
    layers = ocr_pages(GARBLED, [1, 2, 3], OcrConfig(), ExplodingEngine(), cache)
    assert all(layer.words for layer in layers.values())


def test_an_image_only_pdf_is_rescued(tmp_path):
    scanned = tmp_path / "scan.pdf"
    with pymupdf.open(GARBLED) as source, pymupdf.open() as scan:
        page = source[0]
        new = scan.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=page.get_pixmap(dpi=200))
        scan.save(scanned)  # only the first page: a page costs about a minute on the CPU
    with pymupdf.open(scanned) as document:
        assert not document[0].get_text("words")
        layers = {1: load_layer(document[0])}
    config = OcrConfig()
    merged, done = asyncio.run(
        usable_layers(scanned, layers, PaddleEngine(config), config, tmp_path / "cache")
    )
    assert done == (1,)
    assert len(merged[1].words) > 100


def test_ocr_boxes_land_on_the_native_words_boxes(tmp_path):
    config = OcrConfig(dpi=200)  # cheaper than 300 and a different scale from the default
    layer = ocr_pages(HOUSE, [1], config, PaddleEngine(config), tmp_path)[1]
    with pymupdf.open(HOUSE) as document:
        native = load_layer(document[0])
    matches = []
    for word in native.words:
        if len(word.text) < 4 or not word.text.isalpha():
            continue
        cx, cy = (word.bbox[0] + word.bbox[2]) / 2, (word.bbox[1] + word.bbox[3]) / 2
        near = [
            w
            for w in layer.words
            if w.text.lower() == word.text.lower()
            and abs((w.bbox[0] + w.bbox[2]) / 2 - cx) <= TOLERANCE
            and abs((w.bbox[1] + w.bbox[3]) / 2 - cy) <= TOLERANCE
        ]
        matches.append(bool(near))
    assert len(matches) > 50
    assert sum(matches) / len(matches) > 0.8, f"{sum(matches)} of {len(matches)} words aligned"


# Centres of the same word must be within 3 pt: a 9 pt font is about 9 pt tall, so 3 pt (a third
# of a line) tolerates detector box padding and is far below the 6.5 pt line spacing at which
# a wrong scale or a shifted origin would make a word land on its neighbour.
TOLERANCE = 3.0


@pytest.fixture(scope="module")
def strip_result():
    """A real PaddleOCR result for the top strip of a page, with the same arguments gridkey uses."""
    from paddleocr import PaddleOCR  # noqa: PLC0415

    with pymupdf.open(GARBLED) as document:
        page = document[0]
        clip = pymupdf.Rect(0, 0, page.rect.width, 120)
        png = page.get_pixmap(dpi=200, clip=clip).tobytes("png")
    pipeline = PaddleOCR(**_constructor_arguments(OcrConfig(), "cpu"))
    (result,) = pipeline.predict(_decode(png))
    return result


def test_numbers_with_thousands_commas_come_out_as_one_word(strip_result):
    # PaddleOCR splits "$15,142,000.00" into '$', '15', ',', '142', ',', '000.00' (no spaces);
    # result_words must join them, or no such number could ever be grounded.
    words = [w.text for w in result_words(strip_result)]
    assert "," not in words
    assert any(re.fullmatch(r"\$?\d{1,3}(,\d{3})+\.\d\d", w) for w in words), words


def test_the_word_box_keys_exist_and_line_up(strip_result):
    for key in ("rec_texts", "rec_scores", "rec_boxes", "text_word", "text_word_boxes"):
        assert key in strip_result, key
    lines = len(strip_result["rec_texts"])
    assert lines > 0
    assert len(strip_result["text_word"]) == len(strip_result["text_word_boxes"]) == lines
    for pieces, boxes in zip(
        strip_result["text_word"], strip_result["text_word_boxes"], strict=True
    ):
        assert len(pieces) == len(boxes)
        assert all(len(box) == 4 for box in boxes)  # [x0, y0, x1, y1]
    assert strip_result["model_settings"]["use_doc_preprocessor"] is False


@pytest.mark.skipif(not MODELS.is_dir(), reason="no downloaded models in ~/.paddlex to point at")
def test_model_dir_loads_the_models_from_a_folder(tmp_path):
    config = OcrConfig(model_dir=MODELS, dpi=100)
    with pymupdf.open(GARBLED) as document:
        png = document[0].get_pixmap(dpi=100, clip=pymupdf.Rect(0, 0, 657, 120)).tobytes("png")
    words = PaddleEngine(config).recognize(png)
    assert any(w.text.isalpha() for w in words)
