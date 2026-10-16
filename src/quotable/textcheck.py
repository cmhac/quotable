"""
Check that a PDF's text layer is readable before anything is sent to a model.

Grounding compares every extracted value with the text layer, so a garbled layer (a broken
font encoding, bad OCR) or a missing one (a scan without OCR) makes verification
impossible. Each page's letters are scored against an English character-trigram model; the
document is rejected when too many scorable pages look like noise. A rejected document has
its bad pages OCR'd and is checked again (:func:`quotable.extract.usable_layers`); it is
rejected for good only if OCR is off, unavailable or does not help. There is no way to turn
this check off.
"""

import math
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from typing import Literal

from quotable.ngrams import letter_runs, load_counts, trigrams
from quotable.text import Layer

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

# The advice that ends a rejection, by why OCR did not rescue the document.
WHY_READABLE = "Extraction checks every value against the PDF's text layer, so it must be readable."
REMEDY_OCR_OFF = (
    f"{WHY_READABLE} OCR is turned off (`ocr=False`): enable it (the default), or OCR the PDF "
    "yourself: re-run OCR over the whole document, replacing the existing text layer (for "
    "example `ocrmypdf --force-ocr`), then try again."
)
REMEDY_OCR_FAILED = (
    f"{WHY_READABLE} Try a higher `dpi` or another `ocr_version` in `OcrConfig`, or re-run OCR "
    "over the whole document with another tool, replacing the existing text layer (for "
    "example `ocrmypdf --force-ocr`), then try again."
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


@dataclass(frozen=True)
class Assessment:
    """The result of checking a document's text layers, without raising."""

    pages: list[PageQuality]
    reason: str | None  # why the document is rejected, without advice (see the REMEDY_ texts)
    bad_pages: tuple[int, ...]  # garbled pages and pages with no words, in page order


def assess_text_layers(layers: dict[int, Layer]) -> Assessment:
    """
    Return each page's quality, whether the document is usable, and which pages are bad.

    Rejected (``reason`` is set): a document with no text on any page, or one where more
    than ``MAX_GARBLED_PAGE_SHARE`` of the scorable pages are garbled. A document that has
    text but no scorable page (for example only numbers) is accepted. ``bad_pages`` lists
    the pages judged garbled plus the pages with no words, whether or not the document is
    rejected.
    """
    results = [score_page(page, layers[page]) for page in sorted(layers)]
    garbled = [r for r in results if r.verdict == "garbled"]
    empty = [r.page for r in results if not layers[r.page].words]
    bad_pages = tuple(sorted({r.page for r in garbled} | set(empty)))
    if not any(layer.words for layer in layers.values()):
        reason = "The PDF has no text layer (it looks like a scan without OCR)."
        return Assessment(results, reason, bad_pages)
    assessed = [r for r in results if r.verdict != "unassessable"]
    reason = None
    if assessed and len(garbled) / len(assessed) > MAX_GARBLED_PAGE_SHARE:
        pages = [r.page for r in garbled]
        reason = (
            f"The PDF's text layer is garbled: {len(garbled)} of {len(assessed)} scorable "
            f"pages do not contain readable text (pages {_page_list(pages)}), "
            f"e.g. {_excerpt(layers[pages[0]])!r}."
        )
    return Assessment(results, reason, bad_pages)


def check_text_layers(layers: dict[int, Layer]) -> list[PageQuality]:
    """Return each page's quality, or raise ``TextLayerError`` if the document is unusable."""
    assessment = assess_text_layers(layers)
    if assessment.reason is not None:
        raise TextLayerError(f"{assessment.reason} {REMEDY_OCR_OFF}")
    return assessment.pages


def ocr_failed_message(
    before: Assessment, after: Assessment, pages: tuple[int, ...], by: str
) -> str:
    """
    Return the rejection for a document that is still unreadable after OCR.

    ``pages`` are the OCR'd pages, ``by`` describes the engine and device, ``before`` and
    ``after`` are the assessments of the original and the OCR-patched layers.
    """
    listed = _page_list(list(pages))
    return (
        f"{before.reason} quotable OCR'd page(s) {listed} with {by}, but the text layer is "
        f"still not usable: {after.reason} {REMEDY_OCR_FAILED}"
    )
