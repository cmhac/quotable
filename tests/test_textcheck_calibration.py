"""
Calibration of the text-layer check on real PDFs (spec 001, task 003).

Measured page scores (mean log-probability per trigram):

    fy22_ag_house_original        -2.54 -2.55 -2.50 -2.60
    fy22_milcon_house_original    -2.48
    fy24_milcon_house_original    -2.45 -2.45
    senate_expenditures_garbled   -4.87 -4.77 -4.85

The ranges do not overlap, so the threshold (-3.7) sits in the gap with about 1.1 to spare on
each side. Ten legitimate pages from three documents is a small sample; if a legitimate
document is ever rejected, add it here and recalibrate rather than adding a bypass.
"""

from pathlib import Path

import pymupdf
import pytest

from quotable.text import load_layer
from quotable.textcheck import (
    GARBLED_SCORE_THRESHOLD,
    TextLayerError,
    check_text_layers,
    score_page,
)

DATA = Path(__file__).parent / "data"
LEGITIMATE = [
    "fy22_ag_house_original.pdf",
    "fy22_milcon_house_original.pdf",
    "fy24_milcon_house_original.pdf",
]
GARBLED = "senate_expenditures_garbled.pdf"
MARGIN = 1.0  # required distance between the threshold and the nearest page score


def layers_of(name: str) -> dict:
    with pymupdf.open(DATA / name) as document:
        return {i: load_layer(page) for i, page in enumerate(document, 1)}


@pytest.mark.parametrize("name", LEGITIMATE)
def test_legitimate_documents_are_accepted(name):
    results = check_text_layers(layers_of(name))
    assert results
    assert all(r.verdict == "ok" for r in results)


def test_garbled_senate_document_is_rejected():
    with pytest.raises(TextLayerError, match="garbled") as error:
        check_text_layers(layers_of(GARBLED))
    assert "3 of 3" in str(error.value)
    assert "re-run OCR" in str(error.value)


def scores_of(name: str) -> list[float]:
    scores = [score_page(n, layer).score for n, layer in layers_of(name).items()]
    return [s for s in scores if s is not None]


def test_threshold_is_in_the_gap_with_margin():
    legitimate = [s for name in LEGITIMATE for s in scores_of(name)]
    garbled = scores_of(GARBLED)
    assert len(legitimate) == 7  # every legitimate page is scorable
    assert len(garbled) == 3
    assert min(legitimate) - GARBLED_SCORE_THRESHOLD >= MARGIN
    assert GARBLED_SCORE_THRESHOLD - max(garbled) >= MARGIN
