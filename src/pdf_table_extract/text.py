"""Tokenising and the text layer of a PDF page."""

import re
import statistics
import unicodedata
from dataclasses import dataclass, field

import pymupdf

Bbox = tuple[float, float, float, float]

# Hyphens join the words around them (a line-wrap hyphen is not part of the word);
# en and em dashes separate words (``Fund—Save`` and ``Fund— Save`` are the same).
_DASHES = "-\u2010\u2011\u2012\u2015\u2212"
_SEPARATING_DASHES = "[\u2013\u2014]"
# Some PDFs store an accent as a separate spacing character after its letter
# (``Herna´ndez``). NFKD would turn that into a space plus a combining mark, which
# splits the word, so they are dropped first, but only directly after a letter.
_SPACING_ACCENTS = re.compile(
    "(?<=[^\\W\\d_])[\u00b4\u02dc\u00a8\u02c6\u02c7\u00b8\u02d8\u02d9\u02da\u02db\u02dd\u00af]"
)
_MIN_STEM_LENGTH = 3


def _stem(token: str) -> str:
    """Strip a plural ``s`` (langextract's ``_normalize_token``)."""
    if len(token) > _MIN_STEM_LENGTH and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """
    Normalise text into comparison tokens (applied to PDF text and to values alike).

    ASCII-folds and lowercases, drops ``$``, hyphens, apostrophes and spacing
    accents, removes thousands separators, and splits on everything else,
    including en and em dashes. Only the comparison tokens change; no text is
    rewritten.
    """
    text = _SPACING_ACCENTS.sub("", text).replace("\u0131", "i")
    text = unicodedata.normalize("NFKD", text).lower()
    text = re.sub(_SEPARATING_DASHES, " ", text)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,250,000 -> 1250000
    text = re.sub(rf"[{_DASHES}'\u2019`$]", "", text)
    text = text.encode("ascii", "ignore").decode()
    return [_stem(t) for t in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text)]


@dataclass
class SrcWord:
    """One text-layer word (line-end hyphen breaks joined), in upright coordinates."""

    id: int
    text: str
    bbox: Bbox


@dataclass
class Layer:
    """Tokenised text layer of one page."""

    words: list[SrcWord] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    tok_word: list[int] = field(default_factory=list)  # token index -> word id

    def add(self, text: str, bbox: Bbox) -> None:
        """Append a word and its tokens."""
        word = SrcWord(len(self.words), text, bbox)
        self.words.append(word)
        for token in tokenize(text):
            self.tokens.append(token)
            self.tok_word.append(word.id)

    def crop(self, y0: float, y1: float, x0: float, x1: float, line_tol: float = 2.0) -> "Layer":
        """Return the words centred in the box as a new layer, in reading order."""
        inside = [
            w
            for w in self.words
            if y0 <= (w.bbox[1] + w.bbox[3]) / 2 <= y1 and x0 <= (w.bbox[0] + w.bbox[2]) / 2 <= x1
        ]
        inside.sort(key=lambda w: (w.bbox[1] + w.bbox[3]) / 2)
        lines: list[list[SrcWord]] = []
        for w in inside:
            top = lines[-1][0] if lines else None
            if top and (w.bbox[1] + w.bbox[3]) / 2 - (top.bbox[1] + top.bbox[3]) / 2 <= line_tol:
                lines[-1].append(w)
            else:
                lines.append([w])
        cropped = Layer()
        for line in lines:
            for w in sorted(line, key=lambda w: w.bbox[0]):
                cropped.add(w.text, w.bbox)
        return cropped

    def _words_of(self, start: int, end: int) -> list[SrcWord]:
        ids = sorted({self.tok_word[t] for t in range(start, end)})
        return [self.words[i] for i in ids]

    def yc(self, start: int, end: int) -> float:
        """Return the mean vertical centre of tokens ``start:end``."""
        return statistics.fmean(
            (self.words[self.tok_word[t]].bbox[1] + self.words[self.tok_word[t]].bbox[3]) / 2
            for t in range(start, end)
        )

    def bbox(self, start: int, end: int) -> Bbox:
        """Return the union box of the words holding tokens ``start:end``."""
        boxes = [w.bbox for w in self._words_of(start, end)]
        return (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )

    def text(self, start: int, end: int) -> str:
        """Return the page text of the words holding tokens ``start:end``."""
        return " ".join(w.text for w in self._words_of(start, end))


def load_layer(page: pymupdf.Page) -> Layer:
    """
    Read a page's text layer into a ``Layer``.

    ``get_text('words')`` is in unrotated page space, so every rectangle is mapped
    through ``page.rotation_matrix``. A word ending in ``-`` is joined to the next
    word when that one sits on a lower line and does not start further right (a
    wrapped word such as ``Rehabilita-`` / ``tion``).
    """
    rotation = page.rotation_matrix
    raw = page.get_text("words")
    layer = Layer()
    i = 0
    while i < len(raw):
        text = raw[i][4]
        rect = pymupdf.Rect(*raw[i][:4]) * rotation
        if text.endswith("-") and len(text) > 1 and i + 1 < len(raw):
            following = pymupdf.Rect(*raw[i + 1][:4]) * rotation
            if following.y0 >= rect.y1 - 1 and following.x0 <= rect.x0 + 0.5:
                rect |= following
                text = text[:-1] + raw[i + 1][4]
                i += 1
        layer.add(text, (rect.x0, rect.y0, rect.x1, rect.y1))
        i += 1
    return layer
