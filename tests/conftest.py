"""Shared fixtures: a small canonical dataset and helpers for building non-canonical look-alikes."""

from __future__ import annotations

import numpy as np
import pytest

from sdplab.dataset import EVENT_DTYPE, generate

ALIGNED_DTYPE = np.dtype(
    [("event_id", "<i8"), ("pt", "<f8"), ("eta", "<f8"), ("phi", "<f8"), ("category_code", "<i2")],
    align=True,
)


@pytest.fixture
def events_small() -> np.ndarray:
    return generate(64, 4242)


@pytest.fixture
def aligned_copy():
    """Return a function that copies a canonical array into the aligned (padded) dtype."""

    def make(a: np.ndarray, pad: int = 0) -> np.ndarray:
        out = np.zeros(a.shape[0], dtype=ALIGNED_DTYPE)
        for name in EVENT_DTYPE.names:
            out[name] = a[name]
        raw = out.view(np.uint8).reshape(a.shape[0], ALIGNED_DTYPE.itemsize)
        raw[:, EVENT_DTYPE.itemsize :] = pad
        return out

    return make
