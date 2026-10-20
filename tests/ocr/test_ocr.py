"""OcrConfig, OCR words, and their conversion to a Layer (no OCR engine needed)."""

from typing import Any

import pymupdf
import pytest

from quotable.errors import OcrUnavailableError, TextLayerError
from quotable.ocr.config import OcrConfig, OcrWord, words_to_layer

PAGE = (612.0, 792.0)


def word(text: str, box: tuple[float, float, float, float], score: float = 0.99) -> OcrWord:
    return OcrWord(text, box, score)


def test_the_defaults():
    config = OcrConfig()
    assert config.lang == "en"
    assert config.ocr_version == "PP-OCRv6"
    assert config.dpi == 300
    assert config.device == "auto"
    assert config.engine is None
    assert config.cpu_threads is None
    assert config.min_confidence == 0.0
    assert config.text_detection_model is None
    assert config.text_recognition_model is None
    assert config.model_dir is None
    assert config.paddleocr_options == {}
    assert config.predict_options == {}


def test_the_option_dictionaries_are_not_shared_between_configs():
    assert OcrConfig().paddleocr_options is not OcrConfig().paddleocr_options


def test_the_unavailable_error_is_a_text_layer_error():
    assert issubclass(OcrUnavailableError, TextLayerError)


@pytest.mark.parametrize("dpi", [71, 601, 0, -300])
def test_dpi_outside_the_range_is_rejected(dpi):
    with pytest.raises(ValueError, match="dpi"):
        OcrConfig(dpi=dpi)


@pytest.mark.parametrize("dpi", [72, 150, 600])
def test_dpi_inside_the_range_is_accepted(dpi):
    assert OcrConfig(dpi=dpi).dpi == dpi


@pytest.mark.parametrize("value", [-0.1, 1.1])
def test_min_confidence_outside_zero_to_one_is_rejected(value):
    with pytest.raises(ValueError, match="min_confidence"):
        OcrConfig(min_confidence=value)


@pytest.mark.parametrize("name", ["use_doc_orientation_classify", "use_doc_unwarping"])
@pytest.mark.parametrize("where", ["paddleocr_options", "predict_options"])
def test_options_that_change_the_image_geometry_are_rejected(name, where):
    options: dict[str, Any] = {where: {name: True}}
    with pytest.raises(ValueError, match="geometry"):
        OcrConfig(**options)


def test_switching_those_options_off_is_harmless():
    OcrConfig(paddleocr_options={"use_doc_unwarping": False})


@pytest.mark.parametrize(
    ("option", "field"),
    [
        ("lang", "lang"),
        ("ocr_version", "ocr_version"),
        ("device", "device"),
        ("cpu_threads", "cpu_threads"),
        ("text_rec_score_thresh", "min_confidence"),
        ("text_detection_model_name", "text_detection_model"),
        ("text_recognition_model_dir", "model_dir"),
        ("return_word_box", "always on"),
    ],
)
def test_an_option_that_a_field_sets_is_rejected_with_the_field_named(option, field):
    with pytest.raises(ValueError, match=field):
        OcrConfig(paddleocr_options={option: "x"})
    with pytest.raises(ValueError, match=field):
        OcrConfig(predict_options={option: "x"})


def test_other_options_pass_through():
    config = OcrConfig(
        paddleocr_options={"text_det_thresh": 0.2}, predict_options={"text_det_limit_side_len": 64}
    )
    assert config.paddleocr_options == {"text_det_thresh": 0.2}


def test_model_dir_needs_known_or_given_model_names():
    assert OcrConfig(model_dir="models").model_dir == "models"  # en + PP-OCRv6 is known
    with pytest.raises(ValueError, match="need both model names"):
        OcrConfig(model_dir="models", lang="fr")
    OcrConfig(
        model_dir="models",
        lang="fr",
        text_detection_model="PP-OCRv5_server_det",
        text_recognition_model="latin_PP-OCRv5_mobile_rec",
    )


def test_naming_one_model_needs_the_other_to_be_known():
    OcrConfig(text_detection_model="PP-OCRv6_small_det")  # the recognition default is known
    with pytest.raises(ValueError, match="need both model names"):
        OcrConfig(lang="fr", text_detection_model="PP-OCRv5_server_det")


def test_model_names_prefer_the_configured_ones():
    assert OcrConfig().model_names() == ("PP-OCRv6_medium_det", "PP-OCRv6_medium_rec")
    config = OcrConfig(text_detection_model="PP-OCRv6_small_det")
    assert config.model_names() == ("PP-OCRv6_small_det", "PP-OCRv6_medium_rec")


def test_pixels_become_points_at_300_dpi():
    layer = words_to_layer([word("Hello", (300.0, 600.0, 900.0, 750.0))], 300, PAGE)
    (w,) = layer.words
    assert w.text == "Hello"
    assert w.bbox == pytest.approx((72.0, 144.0, 216.0, 180.0))
    assert layer.tokens == ["hello"]


def test_the_same_pixels_at_150_dpi_are_twice_the_points():
    box = (300.0, 600.0, 900.0, 750.0)
    at_300 = words_to_layer([word("Hello", box)], 300, PAGE).words[0].bbox
    at_150 = words_to_layer([word("Hello", box)], 150, PAGE).words[0].bbox
    assert at_150 == pytest.approx(tuple(2 * v for v in at_300))


def test_a_line_box_splits_into_words_that_tile_the_line_in_order():
    line = word("NET FUNDS AVAILABLE", (0.0, 100.0, 1900.0, 150.0))
    layer = words_to_layer([line], 72, (2000.0, 2000.0))  # 72 dpi: points equal pixels
    assert [w.text for w in layer.words] == ["NET", "FUNDS", "AVAILABLE"]
    boxes = [w.bbox for w in layer.words]
    assert boxes[0][0] == pytest.approx(0.0)
    assert boxes[-1][2] == pytest.approx(1900.0)
    for left, right in zip(boxes, boxes[1:], strict=False):
        assert left[2] < right[0]  # in order, separated by the gap
    widths = [b[2] - b[0] for b in boxes]
    assert widths[1] / widths[0] == pytest.approx(5 / 3)  # FUNDS vs NET: by character count
    assert all(b[1] == 100.0 and b[3] == 150.0 for b in boxes)


def test_words_come_out_in_the_order_given():
    words = [
        word("one", (0, 0, 10, 10)),
        word("two", (20, 0, 30, 10)),
        word("three", (0, 20, 50, 30)),
    ]
    layer = words_to_layer(words, 72, PAGE)
    assert [w.text for w in layer.words] == ["one", "two", "three"]


def test_low_confidence_empty_and_degenerate_words_are_dropped():
    words = [
        word("keep", (0, 0, 10, 10), 0.9),
        word("weak", (20, 0, 30, 10), 0.4),
        word("   ", (40, 0, 50, 10), 0.99),
        word("flat", (60, 5, 70, 5), 0.99),
        word("inverted", (90, 0, 80, 10), 0.99),
    ]
    layer = words_to_layer(words, 72, PAGE, min_confidence=0.5)
    assert [w.text for w in layer.words] == ["keep"]
    assert [w.text for w in words_to_layer(words, 72, PAGE).words] == ["keep", "weak"]


def test_boxes_are_clipped_to_the_page_and_words_outside_it_are_dropped():
    words = [word("edge", (-20, 700, 40, 900)), word("gone", (700, 10, 800, 20))]
    layer = words_to_layer(words, 72, PAGE)
    assert [w.bbox for w in layer.words] == [(0.0, 700.0, 40.0, 792.0)]


def test_a_rotated_page_keeps_upright_coordinates():
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.set_rotation(90)
    upright = (page.rect.width, page.rect.height)
    assert upright == (792.0, 612.0)
    pixmap = page.get_pixmap(dpi=300)
    assert (pixmap.width, pixmap.height) == (3300, 2550)  # the render is upright too
    layer = words_to_layer([word("Top", (3000.0, 100.0, 3300.0, 200.0))], 300, upright)
    assert layer.words[0].bbox == pytest.approx((720.0, 24.0, 792.0, 48.0))
    document.close()
