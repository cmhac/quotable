import random
import string

import pytest

from pdf_table_extract.text import Layer
from pdf_table_extract.textcheck import (
    MAX_GARBLED_PAGE_SHARE,
    MIN_LETTERS,
    TextLayerError,
    check_text_layers,
    score_page,
)

ENGLISH = (
    "The committee reviewed the proposed funding for the construction of a new community "
    "center and the renovation of the existing library, and the members agreed that the "
    "project would serve the residents of the county for many years to come."
)


def layer_of(text: str) -> Layer:
    layer = Layer()
    for i, word in enumerate(text.split()):
        layer.add(word, (float(i), 0.0, float(i) + 1.0, 10.0))
    return layer


def random_letters(seed: int, words: int = 60) -> str:
    rng = random.Random(seed)
    return " ".join("".join(rng.choices(string.ascii_lowercase, k=6)) for _ in range(words))


def test_english_page_is_ok():
    quality = score_page(1, layer_of(ENGLISH))
    assert quality.verdict == "ok"
    assert quality.score is not None


def test_random_letters_page_is_garbled():
    quality = score_page(1, layer_of(random_letters(0)))
    assert quality.verdict == "garbled"


def test_numbers_only_page_is_unassessable():
    quality = score_page(1, layer_of("1,250,000 $4.00 12/31/2021 " * 40))
    assert quality.verdict == "unassessable"
    assert quality.score is None
    assert quality.letters < MIN_LETTERS


def test_clean_document_returns_every_page():
    results = check_text_layers({1: layer_of(ENGLISH), 2: layer_of(ENGLISH)})
    assert [r.page for r in results] == [1, 2]
    assert all(r.verdict == "ok" for r in results)


def test_document_without_text_is_rejected_as_missing():
    with pytest.raises(TextLayerError, match="no text layer") as error:
        check_text_layers({1: Layer(), 2: Layer()})
    assert "OCR" in str(error.value)


def test_document_with_only_numbers_is_accepted():
    results = check_text_layers({1: layer_of("1,250,000 $4.00 " * 40)})
    assert [r.verdict for r in results] == ["unassessable"]


def test_unassessable_pages_do_not_count():
    layers = {n: layer_of("1 2 3 4 5") for n in range(1, 21)}
    layers[21] = layer_of(ENGLISH)
    layers[22] = layer_of(random_letters(0))
    # 1 of 2 scorable pages is garbled; counted over all 22 pages it would be under the limit
    with pytest.raises(TextLayerError, match="1 of 2"):
        check_text_layers(layers)


def test_garbled_share_at_the_limit_is_accepted_and_above_is_rejected():
    pages = round(1 / MAX_GARBLED_PAGE_SHARE)  # 10 pages: one garbled is exactly at the limit
    layers = {n: layer_of(ENGLISH) for n in range(1, pages + 1)}
    layers[3] = layer_of(random_letters(1))
    assert check_text_layers(layers)[2].verdict == "garbled"
    layers[7] = layer_of(random_letters(2))  # two of ten is above the limit
    with pytest.raises(TextLayerError):
        check_text_layers(layers)


def test_message_names_reason_pages_excerpt_and_remedy():
    layers = {n: layer_of(random_letters(n)) for n in range(1, 8)}
    with pytest.raises(TextLayerError) as error:
        check_text_layers(layers)
    message = str(error.value)
    assert "garbled" in message
    assert "7 of 7" in message
    assert "pages 1, 2, 3, 4, 5 and 2 more" in message
    assert repr(" ".join(random_letters(1).split())[:40]) in message
    assert "re-run OCR" in message
