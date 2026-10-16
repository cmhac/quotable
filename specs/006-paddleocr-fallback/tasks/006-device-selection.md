# 006 - Choosing the device

Spec: `../spec.md` (Requirements 7, 8; Design / Hardware). Depends on: task 001 (the Paddle
capability calls in `probe.md`), task 004 (`OcrUnavailableError`).

## Goal

The device decision is a set of pure functions, tested over a table of machine descriptions, so
no GPU, no PaddleOCR and no network are needed to test it.

## Steps

1. New `src/gridkey/ocr_device.py`:
   - `Capabilities` (frozen): `paddle_installed`, `paddle_cuda_build`, `paddle_cuda_devices`
     (count), `nvidia_present`.
   - `Choice` (frozen): `device` (a PaddleOCR device string, or `None` when PaddleOCR should
     decide) and `reason`, plus `warning: str | None`.
   - `choose_device(requested: str, engine: str | None, caps: Capabilities) -> Choice`
     implementing the spec's rules: `auto` uses `gpu:0` for a CUDA build with at least one
     device, else `cpu`; with an NVIDIA GPU present but unusable by PaddlePaddle it chooses
     `cpu` and sets a `warning` that names the cause (CPU-only build, or GPU build with no
     device) and gives the install pointer (README GPU section and the `ocr-core` extra); an
     explicit `device` is returned as given, except an impossible one (`gpu...` with
     `paddle_cuda_build` false, or with Paddle not installed) raises `OcrUnavailableError`
     saying so; when `engine` is not the PaddlePaddle default, `auto` returns `device=None`.
   - `detect_capabilities() -> Capabilities`: imports `paddle` inside a `try`, calls the
     functions confirmed in `probe.md`, and checks for `/dev/nvidia*` (glob) or `nvidia-smi` on
     `PATH` (`shutil.which`). No subprocess is started. Any exception while probing becomes
     "not installed" / "no device", never an error.
2. Tests in `tests/test_ocr_device.py`, a table over `Capabilities`: CUDA build with a device;
   CUDA build with none (and `nvidia_present` true / false); CPU build on a machine with
   `nvidia_present`; Paddle not installed; explicit `cpu`; explicit `gpu:1` with a CUDA build;
   explicit `gpu` with a CPU build (raises); a non-default `engine`. The warning text is
   asserted to contain the cause and the install pointer. `detect_capabilities` is tested with
   `paddle` blocked (all false) and with `shutil.which` / the glob monkeypatched.
3. `ruff check`, `ruff format`, `ty check`, `just test`.

## Done when

The table test covers every row above and `ocr_device.py` imports no third-party package at
module level.
