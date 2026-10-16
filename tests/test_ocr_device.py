"""Device choice over a table of machine descriptions; no GPU, PaddlePaddle or network."""

import builtins
import sys
from pathlib import Path

import pytest

from quotable import ocr_device
from quotable.ocr import OcrUnavailableError
from quotable.ocr_device import Capabilities, choose_device, detect_capabilities

NOTHING = Capabilities(False, False, 0, False)
CPU_BUILD = Capabilities(True, False, 0, False)
CPU_BUILD_ON_GPU_MACHINE = Capabilities(True, False, 0, True)
CUDA_WITH_DEVICE = Capabilities(True, True, 2, True)
CUDA_WITHOUT_DEVICE = Capabilities(True, True, 0, True)
CUDA_WITHOUT_DEVICE_NO_NVIDIA = Capabilities(True, True, 0, False)


@pytest.mark.parametrize(
    ("caps", "device", "warns"),
    [
        (CUDA_WITH_DEVICE, "gpu:0", False),
        (CUDA_WITHOUT_DEVICE, "cpu", True),
        (CUDA_WITHOUT_DEVICE_NO_NVIDIA, "cpu", False),
        (CPU_BUILD_ON_GPU_MACHINE, "cpu", True),
        (CPU_BUILD, "cpu", False),
        (NOTHING, "cpu", False),
        (Capabilities(False, False, 0, True), "cpu", False),  # GPU machine, no PaddlePaddle yet
    ],
)
def test_auto(caps, device, warns):
    choice = choose_device("auto", None, caps)
    assert choice.device == device
    assert (choice.warning is not None) is warns
    assert choice.automatic
    assert choice.is_gpu is (device == "gpu:0")
    assert choice.reason


def test_the_warning_for_a_cpu_build_names_the_cause_and_the_install():
    warning = choose_device("auto", None, CPU_BUILD_ON_GPU_MACHINE).warning
    assert warning is not None
    assert "NVIDIA GPU was found" in warning
    assert "CPU-only build" in warning
    assert "quotable[ocr-core]" in warning
    assert "README" in warning


def test_the_warning_for_a_cuda_build_without_a_device_names_that_cause():
    warning = choose_device("auto", None, CUDA_WITHOUT_DEVICE).warning
    assert warning is not None
    assert "cannot see a CUDA device" in warning
    assert "quotable[ocr-core]" in warning


@pytest.mark.parametrize("caps", [NOTHING, CPU_BUILD, CUDA_WITH_DEVICE])
def test_an_explicit_cpu_is_always_returned_as_given(caps):
    choice = choose_device("cpu", None, caps)
    assert (choice.device, choice.automatic, choice.warning) == ("cpu", False, None)


@pytest.mark.parametrize("requested", ["gpu", "gpu:1"])
def test_an_explicit_gpu_with_a_cuda_build_is_returned_as_given(requested):
    choice = choose_device(requested, None, CUDA_WITH_DEVICE)
    assert choice.device == requested
    assert not choice.automatic
    assert choice.is_gpu


@pytest.mark.parametrize(
    ("caps", "cause"),
    [
        (CPU_BUILD, "CPU-only build"),
        (NOTHING, "not installed"),
        (CUDA_WITHOUT_DEVICE, "cannot see a CUDA device"),
    ],
)
def test_an_impossible_explicit_gpu_raises_and_says_why(caps, cause):
    with pytest.raises(OcrUnavailableError, match=cause) as error:
        choose_device("gpu", None, caps)
    assert "quotable[ocr-core]" in str(error.value)


@pytest.mark.parametrize("engine", [None, "paddle", "paddle_static", "paddle_dynamic"])
def test_paddle_engines_are_treated_as_the_default(engine):
    assert choose_device("auto", engine, CUDA_WITH_DEVICE).device == "gpu:0"


@pytest.mark.parametrize("engine", ["transformers", "onnxruntime"])
def test_another_engine_decides_for_itself_under_auto(engine):
    choice = choose_device("auto", engine, CPU_BUILD_ON_GPU_MACHINE)
    assert choice.device is None
    assert choice.warning is None
    assert not choice.automatic


def test_another_engine_still_gets_an_explicit_device():
    assert choose_device("gpu:0", "onnxruntime", NOTHING).device == "gpu:0"


@pytest.fixture
def block_paddle(monkeypatch):
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split(".")[0] == "paddle":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    for name in [m for m in sys.modules if m.split(".")[0] == "paddle"]:
        monkeypatch.delitem(sys.modules, name)


def test_detection_without_paddle_reports_nothing_installed(block_paddle, monkeypatch):
    monkeypatch.setattr(ocr_device, "nvidia_device_files", lambda: [])
    monkeypatch.setattr(ocr_device.shutil, "which", lambda name: None)
    assert detect_capabilities() == NOTHING


def test_detection_sees_nvidia_by_device_file_or_nvidia_smi(block_paddle, monkeypatch):
    monkeypatch.setattr(ocr_device.shutil, "which", lambda name: None)
    monkeypatch.setattr(ocr_device, "nvidia_device_files", lambda: [Path("/dev/nvidia0")])
    assert detect_capabilities().nvidia_present
    monkeypatch.setattr(ocr_device, "nvidia_device_files", lambda: [])
    assert not detect_capabilities().nvidia_present
    monkeypatch.setattr(ocr_device.shutil, "which", lambda name: "/usr/bin/nvidia-smi")
    assert detect_capabilities().nvidia_present


def test_detection_reads_a_fake_paddle(monkeypatch):
    class Cuda:
        @staticmethod
        def device_count() -> int:
            return 3

    class Device:
        cuda = Cuda()

        @staticmethod
        def is_compiled_with_cuda() -> bool:
            return True

    class Paddle:
        device = Device()

    monkeypatch.setitem(sys.modules, "paddle", Paddle())
    monkeypatch.setattr(ocr_device, "nvidia_device_files", lambda: [])
    monkeypatch.setattr(ocr_device.shutil, "which", lambda name: None)
    assert detect_capabilities() == Capabilities(True, True, 3, False)


def test_a_paddle_that_raises_while_probing_counts_as_unusable(monkeypatch):
    class Broken:
        @property
        def device(self) -> object:
            msg = "driver mismatch"
            raise RuntimeError(msg)

    monkeypatch.setitem(sys.modules, "paddle", Broken())
    monkeypatch.setattr(ocr_device, "nvidia_device_files", lambda: [])
    monkeypatch.setattr(ocr_device.shutil, "which", lambda name: None)
    assert detect_capabilities() == NOTHING
