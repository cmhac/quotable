"""The OCR cache: keys, round trip, misses. PaddleOCR is never importable here."""

import builtins
import json
import sys
from dataclasses import replace

import pytest

from quotable.ocr import OcrConfig, OcrWord
from quotable.ocr_cache import file_sha256, fingerprint, ocr_key, read_page, write_page

WORDS = [
    OcrWord("Hello", (1.0, 2.0, 30.5, 40.0), 0.97),
    OcrWord("World", (40.0, 2.0, 80.0, 40.0), 0.5),
]


@pytest.fixture(autouse=True)
def _paddleocr_cannot_be_imported(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split(".")[0] in {"paddleocr", "paddle"}:
            msg = f"{name} must not be imported by the OCR cache"
            raise AssertionError(msg)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    for name in [m for m in sys.modules if m.split(".")[0] in {"paddleocr", "paddle"}]:
        monkeypatch.delitem(sys.modules, name)


def key_for(config: OcrConfig, pdf: str = "abc", page: int = 1) -> str:
    return ocr_key(pdf, page, fingerprint(config, version="3.7.0"))


def test_words_round_trip(tmp_path):
    key = key_for(OcrConfig())
    write_page(tmp_path, key, WORDS, fingerprint(OcrConfig(), version="3.7.0"))
    assert read_page(tmp_path, key) == WORDS
    assert (tmp_path / "ocr" / f"{key}.json").is_file()


def test_an_empty_page_round_trips_as_empty_not_as_a_miss(tmp_path):
    key = key_for(OcrConfig())
    write_page(tmp_path, key, [], {})
    assert read_page(tmp_path, key) == []


@pytest.mark.parametrize(
    "change",
    [
        {"dpi": 200},
        {"lang": "fr"},
        {"ocr_version": "PP-OCRv5"},
        {"text_detection_model": "PP-OCRv6_small_det"},
        {"text_recognition_model": "PP-OCRv6_small_rec"},
        {"min_confidence": 0.5},
        {"engine": "onnxruntime"},
        {"paddleocr_options": {"text_det_thresh": 0.2}},
        {"predict_options": {"text_det_limit_side_len": 64}},
    ],
)
def test_each_setting_that_changes_the_output_changes_the_key(change):
    assert key_for(OcrConfig()) != key_for(OcrConfig(**change))


def test_the_paddleocr_version_changes_the_key():
    config = OcrConfig()
    assert ocr_key("abc", 1, fingerprint(config, version="3.7.0")) != ocr_key(
        "abc", 1, fingerprint(config, version="3.8.0")
    )


def test_the_device_and_threads_do_not_change_the_key():
    base = OcrConfig()
    assert key_for(base) == key_for(replace(base, device="cpu"))
    assert key_for(base) == key_for(replace(base, device="gpu:1", cpu_threads=2))


def test_option_order_does_not_change_the_key():
    a = OcrConfig(paddleocr_options={"text_det_thresh": 0.2, "text_det_box_thresh": 0.5})
    b = OcrConfig(paddleocr_options={"text_det_box_thresh": 0.5, "text_det_thresh": 0.2})
    assert key_for(a) == key_for(b)


def test_different_pdfs_and_pages_never_share_a_key():
    config = OcrConfig()
    assert key_for(config, "pdf-a") != key_for(config, "pdf-b")
    assert key_for(config, page=1) != key_for(config, page=2)


def test_the_file_hash_depends_on_the_bytes_only(tmp_path):
    a, b = tmp_path / "a.pdf", tmp_path / "b.pdf"
    a.write_bytes(b"same" * 1_000_000)
    b.write_bytes(b"same" * 1_000_000)
    assert file_sha256(a) == file_sha256(b)
    b.write_bytes(b"other")
    assert file_sha256(a) != file_sha256(b)


def test_a_missing_file_is_a_miss(tmp_path):
    assert read_page(tmp_path, "nothing") is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"format": 1, "key": "k", "words": [{"text": "Hel',  # truncated
        '{"format": 99, "key": "k", "words": []}',  # wrong format version
        '{"format": 1, "key": "other", "words": []}',  # file belongs to another key
        '{"format": 1, "key": "k", "words": [{"text": "x"}]}',  # a word without a box
        "[]",
    ],
)
def test_an_unusable_file_is_a_miss_and_is_not_deleted_by_the_read(tmp_path, content):
    path = tmp_path / "ocr" / "k.json"
    path.parent.mkdir()
    path.write_text(content)
    assert read_page(tmp_path, "k") is None
    assert path.read_text() == content


def test_a_new_write_replaces_a_corrupt_file_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "ocr" / "k.json"
    path.parent.mkdir()
    path.write_text("{not json")
    write_page(tmp_path, "k", WORDS, {})
    assert read_page(tmp_path, "k") == WORDS
    assert sorted(p.name for p in path.parent.iterdir()) == ["k.json"]
    assert json.loads(path.read_text())["format"] == 1
