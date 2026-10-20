import pymupdf

from quotable.steps.layout import find_header, page_layouts
from quotable.text.layer import load_layer

COLUMNS = ["Account", "Location", "Project", "Amount"]


def _layers(path):
    with pymupdf.open(path) as document:
        return [load_layer(page) for page in document]


def _header_words(names, y=60):
    return [(72 + 110 * i, y, name) for i, name in enumerate(names)]


def _row(y):
    return [(72, y, "Army"), (182, y, "Fort Bragg"), (292, y, "Barracks"), (402, y, "$100")]


def test_a_line_of_column_names_is_a_header(make_pdf):
    (layer,) = _layers(make_pdf([[*_header_words(COLUMNS), *_row(90)]]))
    header = find_header(COLUMNS, layer)
    assert header is not None
    assert set(header.x) == set(COLUMNS)
    assert header.x["Account"] < header.x["Location"] < header.x["Project"] < header.x["Amount"]


def test_header_words_scattered_in_a_sentence_are_not_a_header(make_pdf):
    prose = [
        (72, 60, "The"),
        (100, 60, "Account"),
        (150, 60, "and"),
        (180, 60, "Location"),
        (240, 60, "were"),
        (280, 60, "changed"),
        (340, 60, "by"),
        (360, 60, "the"),
        (390, 60, "committee"),
    ]
    (layer,) = _layers(make_pdf([[*prose, *_row(90)]]))
    assert find_header(COLUMNS, layer) is None


def test_a_two_level_header_is_found_by_its_leaf_names(make_pdf):
    columns = ["Account", "Amount.House", "Amount.Senate", "Project"]
    words = [
        (72, 50, "Account"),
        (182, 40, "Amount"),
        (182, 50, "House"),
        (292, 50, "Senate"),
        (402, 50, "Project"),
        *_row(90),
    ]
    (layer,) = _layers(make_pdf([words]))
    header = find_header(columns, layer)
    assert header is not None
    assert set(header.x) == set(columns)


def test_a_page_prints_the_columns_its_header_shows(make_pdf):
    path = make_pdf(
        [
            [*_header_words(COLUMNS), *_row(90)],
            [*_header_words(["Account", "Location", "Project"]), *_row(90)],
        ]
    )
    first, second = page_layouts(COLUMNS, _layers(path))
    assert first.columns == tuple(COLUMNS) and first.source == "header"
    assert second.columns == ("Account", "Location", "Project") and second.source == "header"


def test_a_page_without_a_header_inherits_the_previous_layout(make_pdf):
    path = make_pdf(
        [
            [*_header_words(COLUMNS), *_row(90)],
            [*_header_words(["Account", "Location", "Project"]), *_row(90)],
            [*_row(60), *_row(80)],
        ]
    )
    *_, third = page_layouts(COLUMNS, _layers(path))
    assert third.columns == ("Account", "Location", "Project")
    assert third.source == "inherited"


def test_leading_pages_without_a_header_take_the_first_layout(make_pdf):
    path = make_pdf([[*_row(60)], [*_header_words(COLUMNS), *_row(90)]])
    first, second = page_layouts(COLUMNS, _layers(path))
    assert first.columns == second.columns == tuple(COLUMNS)
    assert first.source == "inherited"


def test_a_column_no_header_shows_is_a_detection_gap_not_an_absent_column(make_pdf):
    columns = [*COLUMNS, "Requestor(s)"]  # never printed in any header
    path = make_pdf([[*_header_words(COLUMNS), *_row(90)]])
    (layout,) = page_layouts(columns, _layers(path))
    assert layout.columns == tuple(columns)


def test_a_document_without_headers_is_one_layout_with_every_column(make_pdf):
    path = make_pdf([[*_row(60)], [*_row(60)]])
    layouts = page_layouts(COLUMNS, _layers(path))
    assert [lay.columns for lay in layouts] == [tuple(COLUMNS)] * 2


def test_every_page_of_the_samples_prints_every_column(sample):
    with pymupdf.open(sample["pdf"]) as document:
        layers = [load_layer(page) for page in document]
    for layout in page_layouts(sample["columns"], layers):
        assert layout.columns == tuple(sample["columns"])
