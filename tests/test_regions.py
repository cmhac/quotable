import pymupdf
import pytest

from gridkey.regions import locate, table_layers
from gridkey.schema import ExtractionError
from gridkey.text import load_layer

# Two stacked tables that share the header word "Amount" and the amount "$100".
TITLE = [(72, 40, "Quarterly"), (160, 40, "Report")]
A = [
    (72, 70, "Item"),
    (200, 70, "Amount"),
    (72, 90, "Alpha"),
    (200, 90, "$100"),
    (72, 104, "Beta"),
    (200, 104, "$250"),
]
B = [
    (72, 150, "Name"),
    (200, 150, "Amount"),
    (300, 150, "Note"),
    (72, 170, "Gamma"),
    (200, 170, "$100"),
    (300, 170, "red"),
    (72, 184, "Delta"),
    (200, 184, "$900"),
    (300, 184, "blue"),
]
TABLES = [("A", "Alpha $100", "Beta $250"), ("B", "Gamma $100 red", "Delta $900 blue")]


def layer_of(path):
    with pymupdf.open(path) as document:
        return load_layer(document[0])


def words(layer):
    return [w.text for w in layer.words]


def test_a_single_table_keeps_the_whole_page_layer(make_pdf):
    layer = layer_of(make_pdf([TITLE + A]))
    (only,) = table_layers(1, layer, [TABLES[0]])
    assert only is layer


def test_each_table_gets_only_its_own_band(make_pdf):
    layer = layer_of(make_pdf([TITLE + A + B]))
    a, b = table_layers(1, layer, TABLES)
    assert words(a) == ["Alpha", "$100", "Beta", "$250"]
    assert words(b) == ["Gamma", "$100", "red", "Delta", "$900", "blue"]
    assert len(layer.words) == len(TITLE + A + B)  # the page layer itself is untouched


def test_a_first_row_that_is_not_in_the_text_layer_raises(make_pdf):
    layer = layer_of(make_pdf([TITLE + A + B]))
    tables = [TABLES[0], ("B", "Omega 1", "Delta $900 blue")]
    with pytest.raises(ExtractionError, match=r"page 3: table 'B': its first row was not found"):
        table_layers(3, layer, tables)


def test_a_last_row_that_is_not_in_the_text_layer_raises(make_pdf):
    layer = layer_of(make_pdf([TITLE + A + B]))
    tables = [("A", "Alpha $100", "Omega 1"), TABLES[1]]
    with pytest.raises(ExtractionError, match=r"table 'A': its last row was not found"):
        table_layers(1, layer, tables)


def test_a_last_row_above_the_first_row_raises(make_pdf):
    layer = layer_of(make_pdf([TITLE + A + B]))
    tables = [("A", "Beta $250", "Alpha $100"), TABLES[1]]
    with pytest.raises(ExtractionError, match="last row is above its first row"):
        table_layers(1, layer, tables)


def test_overlapping_bands_raise_naming_both_tables(make_pdf):
    layer = layer_of(make_pdf([TITLE + A + B]))
    tables = [("A", "Alpha $100", "Delta $900 blue"), TABLES[1]]
    with pytest.raises(ExtractionError, match=r"'A' and 'B' overlap vertically"):
        table_layers(1, layer, tables)


def test_the_first_row_takes_the_topmost_match_and_the_last_row_the_bottommost(make_pdf):
    repeated = [(72, 90, "Total"), (200, 90, "$5"), (72, 190, "Total"), (200, 190, "$5")]
    layer = layer_of(make_pdf([repeated]))
    top, _ = locate(layer, "Total $5", "first") or (0, 0)
    _, bottom = locate(layer, "Total $5", "last") or (0, 0)
    assert top < 90  # the line at y=90, not the one at y=190
    assert bottom > 190  # the line at y=190, not the one at y=90


def test_text_that_is_not_there_is_not_located(make_pdf):
    layer = layer_of(make_pdf([TITLE]))
    assert locate(layer, "Nothing here", "first") is None
    assert locate(layer, "", "first") is None
