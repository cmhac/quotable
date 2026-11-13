"""Every page without text is OCR'd, however few or many (spec 019, story 5). Fake engine."""

import asyncio

import pymupdf
import pytest

from quotable import OcrConfig, TextLayerError
from quotable import extract_tables as public_extract_tables
from quotable.meter import RunMeter
from quotable.ocr.config import OcrWord
from quotable.pipeline import usable_layers
from quotable.progress import Reporter
from quotable.text.layer import Layer, load_layer
from quotable.text.quality import MAX_EMPTY_PAGE_SHARE, empty_pages_reason
from tests.fake_ocr import ExplodingEngine, FakeEngine
from tests.test_entrypoint import Calls
from tests.test_progress import RecordingSink

TEXT = [(72, 60, "Alpha"), (182, 60, "Beta"), (72, 90, "Gamma"), (182, 90, "$100")]


def scan(name: str) -> list[OcrWord]:
    return [OcrWord(name, (50.0, 50.0, 200.0, 90.0), 0.95)]


def layers_of(path) -> dict:
    with pymupdf.open(path) as document:
        return {i + 1: load_layer(p) for i, p in enumerate(document)}


def pdf_with_text_on(make_pdf, text_pages: set[int], total: int = 20):
    return make_pdf([TEXT if n in text_pages else [] for n in range(1, total + 1)])


def go(path, layers, engine, tmp_path, **options):
    return asyncio.run(usable_layers(path, layers, engine, OcrConfig(), tmp_path, **options))


# --- the share of empty pages (the rule with OCR off) -------------------------------------------
def test_more_than_a_tenth_of_the_pages_empty_is_too_many():
    assert MAX_EMPTY_PAGE_SHARE == 0.10

    def layers(empty: int, total: int = 20):
        words = load_layer_with_words()
        return {n: (Layer() if n <= empty else words) for n in range(1, total + 1)}

    assert empty_pages_reason(layers(2)) is None  # exactly 10%
    assert empty_pages_reason(layers(0)) is None
    reason = empty_pages_reason(layers(3))
    assert reason is not None and "no text on 3 of 20 pages" in reason


def load_layer_with_words():
    with pymupdf.open() as document:
        page = document.new_page(width=612, height=792)
        page.insert_text((72, 60), "Alpha Beta", fontsize=9)
        return load_layer(page)


# --- OCR on: exactly the empty pages ------------------------------------------------------------
def test_exactly_the_pages_with_no_words_are_ocrd_before_anything_else(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1, 2})
    layers = layers_of(path)
    engine = FakeEngine(*[scan(f"scan{n}") for n in range(3, 21)])

    merged, done = go(path, layers, engine, tmp_path)

    assert engine.calls == 18 and done == tuple(range(3, 21))
    assert merged[1] is layers[1] and merged[2] is layers[2]  # untouched
    assert [w.text for w in merged[3].words] == ["scan3"]
    assert [w.text for w in merged[20].words] == ["scan20"]


def test_one_empty_page_in_a_hundred_is_ocrd_too(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, set(range(1, 101)) - {37}, total=100)
    engine = FakeEngine(scan("scan37"))
    merged, done = go(path, layers_of(path), engine, tmp_path)
    assert engine.calls == 1 and done == (37,)
    assert [w.text for w in merged[37].words] == ["scan37"]


def test_a_page_where_ocr_finds_nothing_stays_empty_without_an_error(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1, 2})
    engine = FakeEngine(*[[] for _ in range(18)])
    merged, done = go(path, layers_of(path), engine, tmp_path)
    assert done == tuple(range(3, 21)) and merged[3].words == []


def test_a_pdf_with_no_words_after_ocr_is_rejected_as_before(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, set(), total=3)
    engine = FakeEngine(*[[] for _ in range(3)])
    with pytest.raises(TextLayerError, match="no text layer"):
        go(path, layers_of(path), engine, tmp_path)


def test_a_second_call_reads_the_ocr_from_the_cache(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1, 2})
    go(path, layers_of(path), FakeEngine(*[scan("x") for _ in range(18)]), tmp_path)
    merged, done = go(path, layers_of(path), ExplodingEngine(), tmp_path)
    assert done == tuple(range(3, 21)) and [w.text for w in merged[5].words] == ["x"]


# --- OCR off ------------------------------------------------------------------------------------
def test_with_ocr_off_a_tenth_empty_is_accepted_and_more_is_refused(make_pdf, tmp_path):
    ok = pdf_with_text_on(make_pdf, set(range(3, 21)))  # 2 of 20 empty
    layers = layers_of(ok)
    assert go(ok, layers, None, tmp_path) == (layers, ())
    many = pdf_with_text_on(make_pdf, set(range(4, 21)))  # 3 of 20 empty
    with pytest.raises(TextLayerError, match=r"no text on 3 of 20 pages") as error:
        go(many, layers_of(many), None, tmp_path)
    assert "ocr=False" in str(error.value)


def test_with_ocr_off_a_pdf_with_no_text_anywhere_keeps_its_message(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, set(), total=3)
    with pytest.raises(TextLayerError, match="no text layer"):
        go(path, layers_of(path), None, tmp_path)


def test_the_refusal_comes_before_any_model_request(make_pdf):
    path = pdf_with_text_on(make_pdf, set(range(4, 21)))
    calls = Calls()
    with pytest.raises(TextLayerError, match="3 of 20"):
        public_extract_tables(path, calls.model(), ocr=False)
    assert calls.count == 0


# --- progress -----------------------------------------------------------------------------------
def messages(sink: RecordingSink) -> list[str]:
    return [text for kind, text in sink.events if kind == "fixed"]


def test_ocr_of_more_than_five_pages_reports_its_progress(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1, 2})
    sink = RecordingSink()
    reporter = Reporter(sink, RunMeter(None))
    go(
        path,
        layers_of(path),
        FakeEngine(*[scan("x") for _ in range(18)]),
        tmp_path,
        reporter=reporter,
    )
    lines = messages(sink)
    assert lines[0] == "quotable: OCR of 18 pages (0 already in the cache)"
    assert lines[-2] == "quotable: OCR 18 of 18 pages"
    assert lines[-1].startswith("quotable: OCR done, 18 pages in ")
    assert len(lines) <= 13  # a line at each tenth, not one a page


def test_ocr_of_five_pages_or_fewer_prints_nothing(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1}, total=6)  # 5 empty pages
    sink = RecordingSink()
    go(
        path,
        layers_of(path),
        FakeEngine(*[scan("x") for _ in range(5)]),
        tmp_path,
        reporter=Reporter(sink, RunMeter(None)),
    )
    assert messages(sink) == []


def test_pages_already_in_the_cache_are_counted_in_the_first_line(make_pdf, tmp_path):
    path = pdf_with_text_on(make_pdf, {1, 2})
    go(path, layers_of(path), FakeEngine(*[scan("x") for _ in range(18)]), tmp_path)
    sink = RecordingSink()
    go(path, layers_of(path), ExplodingEngine(), tmp_path, reporter=Reporter(sink, RunMeter(None)))
    assert messages(sink)[0] == "quotable: OCR of 18 pages (18 already in the cache)"
