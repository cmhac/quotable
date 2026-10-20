"""The PaddleOCR adapter, against a fake ``paddleocr`` (the real one runs in tests/ocr)."""

import logging

import pytest

from quotable.errors import OcrUnavailableError
from quotable.ocr import paddle
from quotable.ocr.config import OcrConfig, OcrWord
from quotable.ocr.paddle import PaddleEngine, result_words
from tests.fake_paddle import FakePaddleOCR, install, png, result

LINE = [("NET FUNDS", 0.9, (10, 20, 100, 40))]


def answers(*results: dict):
    """Make the fake pipeline answer every page with these results."""
    FakePaddleOCR.answer = staticmethod(lambda self, image: list(results))


def test_constructing_the_engine_imports_nothing(monkeypatch):
    finder = install(monkeypatch)
    PaddleEngine(OcrConfig())
    assert finder.imported == []
    assert FakePaddleOCR.instances == []


def test_the_first_page_imports_builds_and_the_second_reuses_the_pipeline(monkeypatch):
    finder = install(monkeypatch)
    answers(result(LINE))
    engine = PaddleEngine(OcrConfig())
    engine.recognize(png())
    assert "paddleocr" in finder.imported
    engine.recognize(png())
    assert len(FakePaddleOCR.instances) == 1
    assert len(FakePaddleOCR.instances[0].predictions) == 2


def test_the_default_config_builds_the_documented_pipeline(monkeypatch):
    install(monkeypatch)
    answers(result(LINE))
    PaddleEngine(OcrConfig()).recognize(png())
    (pipeline,) = FakePaddleOCR.instances
    assert pipeline.kwargs == {
        "lang": "en",
        "ocr_version": "PP-OCRv6",
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "return_word_box": True,
        "text_rec_score_thresh": 0.0,
        "device": "cpu",
    }
    assert pipeline.predictions[0]["kwargs"] == {}
    assert pipeline.predictions[0]["shape"] == (8, 8, 3)


def test_a_customised_config_reaches_the_constructor_and_predict(monkeypatch, tmp_path):
    install(monkeypatch)
    (tmp_path / "PP-LCNet_x1_0_textline_ori").mkdir()
    answers(result(LINE))
    config = OcrConfig(
        device="cpu",
        engine="paddle",
        cpu_threads=3,
        min_confidence=0.4,
        text_detection_model="PP-OCRv6_small_det",
        text_recognition_model="PP-OCRv6_small_rec",
        model_dir=tmp_path,
        paddleocr_options={"text_det_thresh": 0.2, "use_doc_unwarping": False},
        predict_options={"text_det_limit_side_len": 64},
    )
    PaddleEngine(config).recognize(png())
    (pipeline,) = FakePaddleOCR.instances
    assert pipeline.kwargs == {
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "return_word_box": True,
        "text_rec_score_thresh": 0.4,
        "text_detection_model_name": "PP-OCRv6_small_det",
        "text_recognition_model_name": "PP-OCRv6_small_rec",
        "text_detection_model_dir": str(tmp_path / "PP-OCRv6_small_det"),
        "text_recognition_model_dir": str(tmp_path / "PP-OCRv6_small_rec"),
        "textline_orientation_model_dir": str(tmp_path / "PP-LCNet_x1_0_textline_ori"),
        "device": "cpu",
        "engine": "paddle",
        "cpu_threads": 3,
        "text_det_thresh": 0.2,
    }
    assert pipeline.predictions[0]["kwargs"] == {"text_det_limit_side_len": 64}


def test_orientation_and_unwarping_are_always_off(monkeypatch):
    install(monkeypatch)
    PaddleEngine(OcrConfig(paddleocr_options={"use_textline_orientation": False})).recognize(png())
    kwargs = FakePaddleOCR.instances[0].kwargs
    assert kwargs["use_doc_orientation_classify"] is False
    assert kwargs["use_doc_unwarping"] is False
    assert kwargs["use_textline_orientation"] is False


def test_word_boxes_become_ocr_words_without_the_spaces(monkeypatch):
    install(monkeypatch)
    answers(result([("NET FUNDS", 0.9, (10, 20, 100, 40)), ("YTD", 0.8, (10, 50, 40, 70))]))
    words = PaddleEngine(OcrConfig()).recognize(png())
    assert [w.text for w in words] == ["NET", "FUNDS", "YTD"]
    assert [w.score for w in words] == [0.9, 0.9, 0.8]
    assert words[0].box == pytest.approx((10.0, 20.0, 40.0, 40.0))  # a third of the 90 px line
    assert words[2].box == (10.0, 50.0, 40.0, 70.0)


def test_pieces_split_at_punctuation_are_joined_into_one_word():
    # What PaddleOCR 3.7.0 really returned (tests/ocr checks the shape): it splits at commas, and
    # a piece can carry the space that follows it.
    result = {
        "rec_texts": ["$15,142,000.00", "SALARIES, OFFICERS"],
        "rec_scores": [0.9, 0.8],
        "rec_boxes": None,
        "text_word": [["$", "15", ",", "142", ",", "000.00"], ["SALARIES", ", ", "OFFICERS"]],
        "text_word_boxes": [
            [[0, 0, 4, 9], [10, 0, 28, 9], [30, 0, 34, 9], [40, 0, 70, 9], [72, 0, 76, 9]]
            + [[80, 1, 110, 10]],
            [[0, 20, 80, 29], [82, 20, 90, 29], [100, 20, 160, 29]],
        ],
    }
    words = result_words(result)
    assert [w.text for w in words] == ["$15,142,000.00", "SALARIES,", "OFFICERS"]
    assert words[0].box == (0.0, 0.0, 110.0, 10.0)  # the union of the six pieces' boxes
    assert words[1].box == (0.0, 20.0, 90.0, 29.0)
    assert words[2].score == 0.8


def test_a_line_only_result_is_returned_as_whole_lines():
    words = result_words(result([("NET FUNDS", 0.9, (10, 20, 100, 40))], words=False))
    assert words == [OcrWord("NET FUNDS", (10.0, 20.0, 100.0, 40.0), 0.9)]


def test_an_empty_result_is_no_words():
    assert result_words({"rec_texts": [], "rec_scores": [], "rec_boxes": None}) == []


def test_results_of_several_images_are_joined(monkeypatch):
    install(monkeypatch)
    answers(result(LINE), result([("YTD", 0.8, (1, 2, 30, 12))]))
    assert [w.text for w in PaddleEngine(OcrConfig()).recognize(png())] == ["NET", "FUNDS", "YTD"]


def test_paddleocr_not_importable_gives_unavailable_with_the_install_command(monkeypatch):
    install(monkeypatch, paddleocr=False, paddle=False)
    with pytest.raises(OcrUnavailableError) as error:
        PaddleEngine(OcrConfig()).recognize(png())
    message = str(error.value)
    assert 'pip install "quotable[ocr]"' in message
    assert "NVIDIA" in message
    assert isinstance(error.value.__cause__, ImportError)


@pytest.mark.parametrize(
    ("system", "machine", "mentioned"),
    [("Darwin", "x86_64", "Darwin x86_64"), ("Linux", "aarch64", "Linux aarch64")],
)
def test_a_platform_without_a_paddlepaddle_wheel_is_named(monkeypatch, system, machine, mentioned):
    install(monkeypatch, paddleocr=False, paddle=False)
    monkeypatch.setattr(paddle.platform, "system", lambda: system)
    monkeypatch.setattr(paddle.platform, "machine", lambda: machine)
    with pytest.raises(OcrUnavailableError, match="publishes no wheel") as error:
        PaddleEngine(OcrConfig()).recognize(png())
    assert mentioned in str(error.value)
    assert "OCR the PDF yourself" in str(error.value)


def test_a_supported_platform_gets_no_wheel_note(monkeypatch):
    install(monkeypatch, paddleocr=False, paddle=False)
    monkeypatch.setattr(paddle.platform, "system", lambda: "Linux")
    monkeypatch.setattr(paddle.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(paddle.sys, "version_info", (3, 12, 0, "final", 0))
    with pytest.raises(OcrUnavailableError) as error:
        PaddleEngine(OcrConfig()).recognize(png())
    assert "publishes no wheel" not in str(error.value)


def test_python_without_a_wheel_is_named(monkeypatch):
    install(monkeypatch, paddleocr=False, paddle=False)
    monkeypatch.setattr(paddle.sys, "version_info", (3, 14, 0, "final", 0))
    with pytest.raises(OcrUnavailableError, match="Python 3.14"):
        PaddleEngine(OcrConfig()).recognize(png())


def test_paddleocr_without_paddlepaddle_names_the_missing_package(monkeypatch):
    install(monkeypatch, paddle=False)
    with pytest.raises(OcrUnavailableError, match="PaddlePaddle") as error:
        PaddleEngine(OcrConfig()).recognize(png())
    assert "quotable[ocr-core]" in str(error.value)
    assert FakePaddleOCR.instances == []


def test_another_engine_does_not_need_paddlepaddle(monkeypatch):
    install(monkeypatch, paddle=False)
    answers(result(LINE))
    PaddleEngine(OcrConfig(engine="onnxruntime")).recognize(png())
    assert "device" not in FakePaddleOCR.instances[0].kwargs  # PaddleOCR decides


def test_the_device_choice_is_logged_and_the_gpu_warning_too(monkeypatch, caplog):
    install(monkeypatch, cuda=False, nvidia=True)
    answers(result(LINE))
    with caplog.at_level(logging.INFO, logger="quotable.ocr"):
        PaddleEngine(OcrConfig()).recognize(png())
    messages = [(r.levelno, r.getMessage()) for r in caplog.records]
    assert any(level == logging.INFO and "OCR device: cpu" in text for level, text in messages)
    assert any(
        level == logging.WARNING and "NVIDIA GPU was found" in text for level, text in messages
    )
    assert FakePaddleOCR.instances[0].kwargs["device"] == "cpu"


def test_auto_uses_the_gpu_when_paddlepaddle_can(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)
    answers(result(LINE))
    PaddleEngine(OcrConfig()).recognize(png())
    assert FakePaddleOCR.instances[0].kwargs["device"] == "gpu:0"


def test_an_auto_gpu_that_fails_to_build_falls_back_to_the_cpu_once(monkeypatch, caplog):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)

    def build_error(kwargs):
        return MemoryError("out of memory") if kwargs.get("device") == "gpu:0" else None

    FakePaddleOCR.build_error = staticmethod(build_error)
    answers(result(LINE))
    with caplog.at_level(logging.WARNING, logger="quotable.ocr"):
        words = PaddleEngine(OcrConfig()).recognize(png())
    assert [w.text for w in words] == ["NET", "FUNDS"]
    assert [i.kwargs["device"] for i in FakePaddleOCR.instances] == ["cpu"]
    assert any("trying again on the CPU" in r.getMessage() for r in caplog.records)


def test_an_auto_gpu_that_fails_on_the_first_page_retries_that_page_on_the_cpu(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)

    def answer(pipeline, image):
        if pipeline.kwargs["device"] == "gpu:0":
            msg = "CUDA error"
            raise RuntimeError(msg)
        return [result(LINE)]

    FakePaddleOCR.answer = staticmethod(answer)
    engine = PaddleEngine(OcrConfig())
    assert [w.text for w in engine.recognize(png())] == ["NET", "FUNDS"]
    assert [i.kwargs["device"] for i in FakePaddleOCR.instances] == ["gpu:0", "cpu"]
    engine.recognize(png())  # the CPU pipeline is kept
    assert len(FakePaddleOCR.instances) == 2


def test_a_failure_on_the_cpu_after_the_fallback_is_raised(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)

    def answer(pipeline, image):
        msg = "broken"
        raise RuntimeError(msg)

    FakePaddleOCR.answer = staticmethod(answer)
    with pytest.raises(RuntimeError, match="broken"):
        PaddleEngine(OcrConfig()).recognize(png())
    assert [i.kwargs["device"] for i in FakePaddleOCR.instances] == ["gpu:0", "cpu"]  # once


def test_a_later_gpu_failure_is_not_retried(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)
    calls = {"n": 0}

    def answer(pipeline, image):
        calls["n"] += 1
        if calls["n"] == 2:
            msg = "late failure"
            raise RuntimeError(msg)
        return [result(LINE)]

    FakePaddleOCR.answer = staticmethod(answer)
    engine = PaddleEngine(OcrConfig())
    engine.recognize(png())
    with pytest.raises(RuntimeError, match="late failure"):
        engine.recognize(png())
    assert len(FakePaddleOCR.instances) == 1


def test_an_explicit_gpu_that_fails_to_load_is_raised_without_a_retry(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)
    FakePaddleOCR.build_error = staticmethod(lambda kwargs: MemoryError("out of memory"))
    with pytest.raises(OcrUnavailableError, match="requested device 'gpu:0'") as error:
        PaddleEngine(OcrConfig(device="gpu:0")).recognize(png())
    assert isinstance(error.value.__cause__, MemoryError)
    assert FakePaddleOCR.instances == []


def test_an_explicit_gpu_that_fails_on_the_first_page_is_raised_without_a_retry(monkeypatch):
    install(monkeypatch, cuda=True, devices=1, nvidia=True)

    def answer(pipeline, image):
        msg = "CUDA error"
        raise RuntimeError(msg)

    FakePaddleOCR.answer = staticmethod(answer)
    with pytest.raises(OcrUnavailableError, match="CUDA error"):
        PaddleEngine(OcrConfig(device="gpu")).recognize(png())
    assert len(FakePaddleOCR.instances) == 1


def test_an_explicit_gpu_with_a_cpu_build_is_unavailable_before_anything_is_built(monkeypatch):
    install(monkeypatch, cuda=False, nvidia=True)
    with pytest.raises(OcrUnavailableError, match="CPU-only build"):
        PaddleEngine(OcrConfig(device="gpu")).recognize(png())
    assert FakePaddleOCR.instances == []


def test_an_error_on_the_cpu_is_raised_as_it_is(monkeypatch):
    install(monkeypatch)
    FakePaddleOCR.build_error = staticmethod(lambda kwargs: ValueError("bad model name"))
    with pytest.raises(ValueError, match="bad model name"):
        PaddleEngine(OcrConfig()).recognize(png())
