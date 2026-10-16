"""
Choosing the device OCR runs on: the CPU, or an NVIDIA GPU when one can be used.

The decision (:func:`choose_device`) is a pure function of what the machine can do
(:class:`Capabilities`), so it is tested without a GPU, PaddlePaddle or a network.
:func:`detect_capabilities` fills the description in, and imports ``paddle`` only inside a
``try``: it is called only when a page misses the OCR cache.

Only NVIDIA GPUs and the CPU are supported. An AMD machine runs on the CPU.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path

from quotable.ocr import OcrUnavailableError

PADDLE_ENGINES = (None, "paddle", "paddle_static", "paddle_dynamic")  # run on PaddlePaddle
GPU_INSTALL = (
    "To use the GPU, install `quotable[ocr-core]` and a GPU build of PaddlePaddle "
    "(see 'OCR on an NVIDIA GPU' in the README)."
)


@dataclass(frozen=True)
class Capabilities:
    """What this machine and environment can do."""

    paddle_installed: bool
    paddle_cuda_build: bool  # the installed PaddlePaddle is compiled with CUDA
    paddle_cuda_devices: int  # CUDA devices that PaddlePaddle can see
    nvidia_present: bool  # an NVIDIA GPU is on the machine (/dev/nvidia* or nvidia-smi)


@dataclass(frozen=True)
class Choice:
    """The device to use (``None``: let PaddleOCR decide), why, and a warning to log."""

    device: str | None
    reason: str
    warning: str | None = None
    automatic: bool = False  # chosen by "auto", so a GPU failure may fall back to the CPU

    @property
    def is_gpu(self) -> bool:
        """Return whether the chosen device is a GPU."""
        return self.device is not None and self.device.startswith("gpu")


def _gpu_problem(caps: Capabilities) -> str | None:
    if not caps.paddle_installed:
        return "PaddlePaddle is not installed"
    if not caps.paddle_cuda_build:
        return "the installed PaddlePaddle is a CPU-only build"
    if caps.paddle_cuda_devices < 1:
        return "the installed PaddlePaddle is a GPU build but cannot see a CUDA device"
    return None


def choose_device(requested: str, engine: str | None, caps: Capabilities) -> Choice:
    """
    Return the device to run OCR on.

    ``"auto"`` uses ``gpu:0`` when PaddlePaddle is a CUDA build that sees a device, else the
    CPU; if an NVIDIA GPU is present but unusable it chooses the CPU and warns, naming the
    cause. An explicit device is returned as given, except a GPU that cannot work with the
    installed PaddlePaddle, which raises ``OcrUnavailableError``. With an engine that does
    not run on PaddlePaddle, ``"auto"`` passes no device and PaddleOCR decides.
    """
    if engine not in PADDLE_ENGINES:
        if requested == "auto":
            return Choice(None, f"engine {engine!r} chooses its own device")
        return Choice(requested, f"device {requested!r} was requested")
    if requested != "auto":
        problem = _gpu_problem(caps) if requested.startswith("gpu") else None
        if problem is not None:
            msg = f"device={requested!r} was requested but {problem}. {GPU_INSTALL}"
            raise OcrUnavailableError(msg)
        return Choice(requested, f"device {requested!r} was requested")
    problem = _gpu_problem(caps)
    if problem is None:
        return Choice(
            "gpu:0",
            f"PaddlePaddle sees {caps.paddle_cuda_devices} CUDA device(s)",
            automatic=True,
        )
    if caps.nvidia_present and caps.paddle_installed:
        warning = (
            f"An NVIDIA GPU was found but {problem}, so OCR runs on the CPU (slow). {GPU_INSTALL}"
        )
        return Choice("cpu", problem, warning, automatic=True)
    return Choice("cpu", "no usable GPU", automatic=True)


def nvidia_device_files() -> list[Path]:
    """Return the NVIDIA device files (``/dev/nvidia*``), if any."""
    return list(Path("/dev").glob("nvidia*"))


def detect_capabilities() -> Capabilities:
    """
    Describe this machine. Never raises: a failed probe means "not installed" / "no device".

    Imports ``paddle`` (slow, about a second) and looks for ``/dev/nvidia*`` or ``nvidia-smi``
    on ``PATH``; no subprocess is started.
    """
    nvidia = bool(nvidia_device_files()) or shutil.which("nvidia-smi") is not None
    try:
        import paddle  # noqa: PLC0415  (optional dependency, imported only when needed)

        cuda_build = bool(paddle.device.is_compiled_with_cuda())
        devices = int(paddle.device.cuda.device_count()) if cuda_build else 0
    except Exception:  # noqa: BLE001  (any failure to probe means "cannot use it")
        return Capabilities(False, False, 0, nvidia)
    return Capabilities(True, cuda_build, devices, nvidia)
