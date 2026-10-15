"""
Check that a PDF's text layer is readable before anything is sent to a model.

Grounding compares every extracted value with the text layer, so a garbled layer (a broken
font encoding, bad OCR) or a missing one (a scan without OCR) makes verification
impossible. Each page's letters are scored against an English character-trigram model; the
document is rejected when too many scorable pages look like noise. There is no way to turn
this check off.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import Literal

from pdf_table_extract.ngrams import letter_runs, load_counts, trigrams
from pdf_table_extract.text import Layer

# Calibrated on real pages (tests/test_textcheck_calibration.py): the legitimate House
# appropriations tables score -2.60 or higher, the garbled Senate pages -4.77 or lower; the
# threshold sits in the middle of that gap. Every legitimate page had 506+ letters and every
# garbled page 873+, so MIN_LETTERS only has to keep tiny, noisy samples from being scored.
MIN_LETTERS = 100  # fewer letters than this and a page is not scored
GARBLED_SCORE_THRESHOLD = -3.7  # mean log-probability per trigram below this is garbled
MAX_GARBLED_PAGE_SHARE = 0.10  # of the scorable pages

ALPHA = 0.5  # additive smoothing for unseen trigrams
ALPHABET = 27  # 26 letters plus the end marker
EXCERPT_CHARS = 40
LISTED_PAGES = 5

Verdict = Literal["ok", "garbled", "unassessable"]

REMEDY = (
    "Extraction checks every value against the PDF's text layer, so that layer must be "
    "readable. Improve the PDF's OCR: re-run OCR over the whole document, replacing the "
    "existing text layer (for example `ocrmypdf --force-ocr`), then try again."
)


class TextLayerError(RuntimeError):
    """The PDF's text layer is garbled or missing, so values cannot be verified."""


@dataclass(frozen=True)
class PageQuality:
    """The text-layer verdict for one page."""

    page: int
    verdict: Verdict
    score: float | None  # mean log-probability per trigram; None when unassessable
    letters: int


@dataclass(frozen=True)
class _Model:
    counts: dict[str, int]
    context_totals: dict[str, int]


@cache
def _model() -> _Model:
    counts = load_counts()
    totals: dict[str, int] = defaultdict(int)
    for gram, n in counts.items():
        totals[gram[:2]] += n
    return _Model(counts, dict(totals))


def _log_probability(gram: str, model: _Model) -> float:
    seen = model.counts.get(gram, 0)
    total = model.context_totals.get(gram[:2], 0)
    return math.log((seen + ALPHA) / (total + ALPHA * ALPHABET))


def page_text(layer: Layer) -> str:
    """Return the page's words as one string."""
    return " ".join(w.text for w in layer.words)


def score_page(page: int, layer: Layer) -> PageQuality:
    """Score one page's text layer against the English trigram model."""
    runs = letter_runs(page_text(layer))
    letters = sum(len(r) for r in runs)
    if letters < MIN_LETTERS:
        return PageQuality(page, "unassessable", None, letters)
    model = _model()
    grams = [g for run in runs for g in trigrams(run)]
    score = sum(_log_probability(g, model) for g in grams) / len(grams)
    verdict: Verdict = "garbled" if score < GARBLED_SCORE_THRESHOLD else "ok"
    return PageQuality(page, verdict, score, letters)


def _page_list(pages: list[int]) -> str:
    shown = ", ".join(str(p) for p in pages[:LISTED_PAGES])
    more = len(pages) - LISTED_PAGES
    return f"{shown} and {more} more" if more > 0 else shown


def _excerpt(layer: Layer) -> str:
    return " ".join(page_text(layer).split())[:EXCERPT_CHARS]


def check_text_layers(layers: dict[int, Layer]) -> list[PageQuality]:
    """
    Return each page's quality, or raise ``TextLayerError`` if the document is unusable.

    Rejected: a document with no text on any page, or one where more than
    ``MAX_GARBLED_PAGE_SHARE`` of the scorable pages are garbled. A document that has
    text but no scorable page (for example only numbers) is accepted.
    """
    if not any(layer.words for layer in layers.values()):
        msg = f"The PDF has no text layer (it looks like a scan without OCR). {REMEDY}"
        raise TextLayerError(msg)
    results = [score_page(page, layers[page]) for page in sorted(layers)]
    assessed = [r for r in results if r.verdict != "unassessable"]
    garbled = [r for r in assessed if r.verdict == "garbled"]
    if assessed and len(garbled) / len(assessed) > MAX_GARBLED_PAGE_SHARE:
        pages = [r.page for r in garbled]
        msg = (
            f"The PDF's text layer is garbled: {len(garbled)} of {len(assessed)} scorable "
            f"pages do not contain readable text (pages {_page_list(pages)}), "
            f"e.g. {_excerpt(layers[pages[0]])!r}. {REMEDY}"
        )
        raise TextLayerError(msg)
    return results
