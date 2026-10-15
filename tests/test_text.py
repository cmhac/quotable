import pymupdf

from pdf_table_extract.text import load_layer, tokenize


def test_tokenize_normalises_the_way_pdf_text_and_model_values_need():
    assert tokenize("$1,250,000") == ["1250000"]
    assert tokenize("Hernández") == ["hernandez"]
    assert tokenize("Rehabilita-tion") == ["rehabilitation"]  # hyphens join
    assert tokenize("Fund—Save") == tokenize("Fund— Save") == ["fund", "save"]  # em dash splits
    assert tokenize("Roads") == tokenize("Road")  # plural s


def test_tokenize_joins_a_spacing_accent_to_its_letter():
    assert tokenize("Herna´ndez") == ["hernandez"]


def test_layer_words_are_upright_on_a_rotated_page(sample):
    with pymupdf.open(sample["pdf"]) as document:
        page = document[0]
        layer = load_layer(page)
        assert layer.words
        for word in layer.words:
            x0, y0, x1, y1 = word.bbox
            assert page.rect.x0 - 1 <= x0 < x1 <= page.rect.x1 + 1
            assert page.rect.y0 - 1 <= y0 < y1 <= page.rect.y1 + 1


def test_layer_finds_a_recorded_value_in_its_tokens(sample):
    first_row = sample["pages"][1][0]
    project = tokenize(first_row[sample["columns"][2]])
    with pymupdf.open(sample["pdf"]) as document:
        layer = load_layer(document[0])
    joined = " ".join(layer.tokens)
    assert " ".join(project[:3]) in joined


def test_line_end_hyphen_is_rejoined_with_the_next_line(make_pdf):
    path = make_pdf([[(72, 100, "Rehabilita-"), (72, 112, "tion of Road")]])
    with pymupdf.open(path) as document:
        layer = load_layer(document[0])
    assert "rehabilitation" in layer.tokens
    assert layer.text(0, 1) == "Rehabilitation"


def test_crop_keeps_the_words_centred_in_a_box_in_reading_order(make_pdf):
    path = make_pdf(
        [[(72, 100, "Alpha"), (200, 100, "Beta"), (72, 140, "Gamma"), (72, 112, "Delta")]]
    )
    with pymupdf.open(path) as document:
        layer = load_layer(document[0])
    assert layer.crop(90, 120, 0, 612).tokens == ["alpha", "beta", "delta"]
    assert layer.crop(90, 120, 150, 612).tokens == ["beta"]
    assert layer.crop(0, 50, 0, 612).tokens == []


def test_layer_maps_tokens_back_to_boxes(make_pdf):
    path = make_pdf([[(72, 100, "Alpha"), (200, 100, "Beta"), (72, 140, "Gamma")]])
    with pymupdf.open(path) as document:
        layer = load_layer(document[0])
    assert layer.tokens == ["alpha", "beta", "gamma"]
    x0, y0, x1, y1 = layer.bbox(0, 2)  # Alpha .. Beta
    assert x0 < 80 and x1 > 200 and y1 < 110
