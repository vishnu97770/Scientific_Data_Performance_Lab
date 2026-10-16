"""Bit-exact validation. There is no tolerance: any difference is a Mismatch.

``np.array_equal`` is not used as the gate because it treats 0.0 and -0.0 as equal and ignores
dtype layout, byte order and padding.
"""

from __future__ import annotations

import struct
from typing import Any

import numpy as np

from sdplab.dataset import dtype_description, identity_sha256


class Mismatch(AssertionError):
    """Two values that must be identical are not. ``aspect`` names what differs."""

    def __init__(self, aspect: str, detail: str):
        self.aspect = aspect
        self.detail = detail
        super().__init__(f"{aspect} differs: {detail}")


def assert_arrays_identical(expected: np.ndarray, actual: object) -> None:
    """Require identical type, dtype description, shape and bytes (via SHA-256)."""
    if type(actual) is not np.ndarray:
        raise Mismatch("type", type(actual).__name__)
    if actual.dtype != expected.dtype or dtype_description(actual.dtype) != dtype_description(
        expected.dtype
    ):
        raise Mismatch(
            "dtype", f"{dtype_description(expected.dtype)} vs {dtype_description(actual.dtype)}"
        )
    if actual.shape != expected.shape:
        raise Mismatch("shape", f"{expected.shape} vs {actual.shape}")
    if not (actual.flags.c_contiguous and expected.flags.c_contiguous):
        raise Mismatch("layout", "arrays must be C-contiguous")
    if identity_sha256(expected) != identity_sha256(actual):
        raise Mismatch("bytes", "SHA-256 of the array bytes differs")


def _bits(x: float) -> bytes:
    return struct.pack("<d", x)


def assert_preprocess_identical(expected: Any, actual: Any) -> None:
    """Compare preprocessing outputs (n_selected, sum_pt, pt_z) bit for bit."""
    if int(expected.n_selected) != int(actual.n_selected):
        raise Mismatch("n_selected", f"{expected.n_selected} vs {actual.n_selected}")
    if _bits(float(expected.sum_pt)) != _bits(float(actual.sum_pt)):
        raise Mismatch("sum_pt", f"{expected.sum_pt!r} vs {actual.sum_pt!r}")
    e, a = expected.pt_z, actual.pt_z
    if type(a) is not np.ndarray or a.dtype != e.dtype or a.shape != e.shape:
        raise Mismatch("pt_z", "type, dtype or shape differs")
    if np.ascontiguousarray(e).tobytes() != np.ascontiguousarray(a).tobytes():
        raise Mismatch("pt_z", "bytes differ")


def check_dataset_record(recorded: dict, regenerated: dict) -> None:
    """Raise Mismatch('dataset', ...) when a regenerated hash differs from the recorded one."""
    if recorded["sha256"] != regenerated["sha256"]:
        raise Mismatch(
            "dataset",
            f"recorded with numpy {recorded['numpy_version']} / generator "
            f"{recorded.get('generator_version')}, regenerated with numpy "
            f"{regenerated['numpy_version']} / generator {regenerated.get('generator_version')}",
        )
