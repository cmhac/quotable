"""OCR inside the pipeline: rescue, rejection messages, cache, API. Fake engine, no PaddleOCR."""

import asyncio
import random
import string
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest

from gridkey import OcrConfig, OcrUnavailableError, TextLayerError, extract_tables_async
from gridkey import extract_tables as public_extract_tables
from gridkey._paddle import PaddleEngine
from gridkey.extract import run_pipeline, usable_layers
from gridkey.ocr import OcrWord
from gridkey.text import load_layer
from tests.conftest import DATA, FakeClient, extract_tables
from tests.fake_ocr import ExplodingEngine, FakeEngine, native_as_ocr
from tests.fake_paddle import install
from tests.test_entrypoint import PDF as GOOD_PDF
from tests.test_entrypoint import Calls
from tests.test_senate_tables import recorded_model

GARBLED = DATA / "senate_expenditures_garbled.pdf"
FIXTURE = DATA / "senate_expenditures_paddleocr.pdf"
DPI = OcrConfig().dpi


def fixture_answers() -> list[list[OcrWord]]:
    """What a good OCR engine says for the three Senate pages (the hand-made OCR'd copy)."""
    return [native_as_ocr(FIXTURE, n, DPI) for n in (1, 2, 3)]


def run(pdf: Path, client: FakeClient, engine, tmp_path: Path, **options):
    return asyncio.run(
        run_pipeline(
            pdf,
            client,
            recheck=False,
            ocr=engine,
            ocr_config=OcrConfig(),
            cache_dir=tmp_path / "cache",
            **options,
        )
    )


def image_only_copy(source: Path, target: Path) -> Path:
    """Return a PDF whose pages are pictures of ``source``'s pages: no text layer at all."""
    with pymupdf.open(source) as document, pymupdf.open() as scanned:
        for page in document:
            new = scanned.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, pixmap=page.get_pixmap(dpi=200))
        scanned.save(target)
    return target


def random_words(seed: int) -> list[OcrWord]:
    rng = random.Random(seed)
    return [
        OcrWord(
            "".join(rng.choices(string.ascii_lowercase, k=6)),
            (i * 70.0, 10.0, i * 70.0 + 60, 40.0),
            0.9,
        )
        for i in range(120)
    ]


def test_the_garbled_senate_pdf_is_rescued_by_ocr_before_any_request(tmp_path):
    client = recorded_model()
    requests_at_ocr: list[int] = []

    class Spy(FakeEngine):
        def recognize(self, png: bytes) -> list[OcrWord]:
            requests_at_ocr.append(len(client.requests))
            return super().recognize(png)

    engine = Spy(*fixture_answers())
    summary, detail = run(GARBLED, client, engine, tmp_path)
    assert engine.calls == 3
    assert requests_at_ocr == [0, 0, 0]  # the first model request comes after OCR
    assert client.stages()[0] == "schema"
    assert summary.ocr_pages == (1,)
    assert detail.ocr_pages == (1, 2, 3)
    # grounded against the OCR text exactly as the hand-made fixture is
    reference = extract_tables(FIXTURE, recorded_model(), recheck=False)
    assert [r.values for r in detail.rows()] == [r.values for r in reference[1].rows()]
    assert detail.position == reference[1].position


def test_a_pdf_with_no_text_is_rescued_the_same_way(tmp_path):
    scanned = image_only_copy(FIXTURE, tmp_path / "scan.pdf")
    with pymupdf.open(scanned) as document:
        assert not any(page.get_text("words") for page in document)
    client = recorded_model()
    engine = FakeEngine(*fixture_answers())
    summary, detail = run(scanned, client, engine, tmp_path)
    assert engine.calls == 3
    assert (summary.ocr_pages, detail.ocr_pages) == ((1,), (1, 2, 3))


def test_only_the_bad_pages_of_a_mixed_pdf_are_ocrd_and_the_others_keep_their_layer(tmp_path):
    mixed = tmp_path / "mixed.pdf"
    with pymupdf.open(DATA / "fy22_ag_house_original.pdf") as good, pymupdf.open(GARBLED) as bad:
        with pymupdf.open() as both:
            both.insert_pdf(good)  # pages 1-4: readable
            both.insert_pdf(bad)  # pages 5-7: garbled
            both.save(mixed)
        native = {n: load_layer(good[n - 1]) for n in range(1, 5)}
    with pymupdf.open(mixed) as document:
        layers = {i + 1: load_layer(p) for i, p in enumerate(document)}
    engine = FakeEngine(*fixture_answers())
    merged, done = asyncio.run(usable_layers(mixed, layers, engine, OcrConfig(), tmp_path))
    assert done == (5, 6, 7)
    assert engine.calls == 3
    for n in range(1, 5):
        assert merged[n] is layers[n]  # untouched, same object
        assert len(merged[n].words) == len(native[n].words)
    assert all(merged[n] is not layers[n] for n in (5, 6, 7))


def test_an_accepted_pdf_never_calls_the_engine_or_imports_paddleocr(tmp_path):
    sys.modules.pop("paddleocr", None)
    sample = DATA / "fy22_milcon_house_original.pdf"
    from tests.conftest import load_sample, replay  # noqa: PLC0415

    recorded = load_sample("fy22_milcon_house_original")
    run(sample, replay(recorded["columns"], recorded["pages"]), ExplodingEngine(), tmp_path)
    assert "paddleocr" not in sys.modules
    assert not (tmp_path / "cache").exists()  # no OCR folder either


def test_importing_gridkey_does_not_import_paddleocr():
    code = (
        "import gridkey, sys; assert 'paddleocr' not in sys.modules and 'paddle' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603


def test_ocr_that_returns_noise_is_rejected_naming_the_ocr_before_any_request(tmp_path):
    client = recorded_model()
    engine = FakeEngine(random_words(1), random_words(2), random_words(3))
    with pytest.raises(TextLayerError) as error:
        run(GARBLED, client, engine, tmp_path)
    message = str(error.value)
    assert "gridkey OCR'd page(s) 1, 2, 3" in message
    assert "still not usable" in message
    assert "dpi" in message
    assert not isinstance(error.value, OcrUnavailableError)
    assert client.requests == []


def test_ocr_that_finds_nothing_is_rejected_before_any_request(tmp_path):
    client = recorded_model()
    with pytest.raises(TextLayerError, match="no text layer"):
        run(GARBLED, client, FakeEngine([], [], []), tmp_path)
    assert client.requests == []


def test_with_ocr_off_the_old_rejection_is_raised_and_no_request_is_made(tmp_path):
    client = recorded_model()
    with pytest.raises(TextLayerError, match="garbled") as error:
        run(GARBLED, client, None, tmp_path)
    assert "OCR is turned off" in str(error.value)
    assert "OCR the PDF yourself" in str(error.value)
    assert client.requests == []


def test_the_public_function_with_ocr_false_makes_no_model_request():
    calls = Calls()
    with pytest.raises(TextLayerError, match="OCR is turned off"):
        public_extract_tables(GARBLED, calls.model(), ocr=False)
    assert calls.count == 0


def test_paddleocr_not_importable_gives_unavailable_with_the_install_command(monkeypatch):
    install(monkeypatch, paddleocr=False, paddle=False)
    calls = Calls()
    with pytest.raises(OcrUnavailableError) as error:
        public_extract_tables(GARBLED, calls.model())
    assert isinstance(error.value, TextLayerError)
    assert 'pip install "gridkey[ocr]"' in str(error.value)
    assert calls.count == 0


def test_a_populated_ocr_cache_rescues_the_document_without_the_engine_or_paddleocr(
    tmp_path, monkeypatch
):
    first = FakeEngine(*fixture_answers())
    run(GARBLED, recorded_model(), first, tmp_path)
    assert first.calls == 3
    install(monkeypatch, paddleocr=False, paddle=False)  # PaddleOCR cannot be imported now
    client = recorded_model()
    _, detail = run(GARBLED, client, PaddleEngine(OcrConfig()), tmp_path)
    assert detail.ocr_pages == (1, 2, 3)
    assert client.stages()[0] == "schema"


def test_the_event_loop_keeps_running_while_the_engine_blocks(tmp_path):
    engine = FakeEngine(*fixture_answers(), delay=0.2)
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async def main() -> None:
        task = asyncio.create_task(ticker())
        await run_pipeline(
            GARBLED,
            recorded_model(),
            recheck=False,
            ocr=engine,
            ocr_config=OcrConfig(),
            cache_dir=tmp_path / "cache",
        )
        task.cancel()

    asyncio.run(main())
    assert ticks > 20  # three pages at 0.2 s each: a blocked loop would tick about once


@pytest.mark.parametrize("ocr", [True, False, OcrConfig(dpi=200)])
def test_both_entrypoints_accept_true_false_and_a_config(ocr):
    calls = Calls()
    (table,) = public_extract_tables(GOOD_PDF, calls.model(), recheck=False, ocr=ocr)
    assert table.ocr_pages == ()
    (again,) = asyncio.run(extract_tables_async(GOOD_PDF, calls.model(), recheck=False, ocr=ocr))
    assert again.ocr_pages == ()


@pytest.mark.parametrize("bad", ["yes", 1, None, {"dpi": 200}])
def test_a_wrong_type_for_ocr_raises_type_error(bad):
    with pytest.raises(TypeError, match="ocr must be"):
        public_extract_tables(GOOD_PDF, Calls().model(), ocr=bad)
    with pytest.raises(TypeError, match="ocr must be"):
        asyncio.run(extract_tables_async(GOOD_PDF, Calls().model(), ocr=bad))
