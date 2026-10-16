"""The single documented preprocessing workload.

mask = (pt > pt_cut) & (abs(eta) < eta_cut); outputs are the number of selected rows, the sum of
pt over the selection and the z-scored pt column (population std over the full column).
The reduction expressions are part of the contract: ``pt[mask].sum()`` and
``np.sum(pt, where=mask)`` can differ in the last bits. Results are bit-identical for
bit-identical inputs in one environment; they are not promised across NumPy versions.
"""

from __future__ import annotations

import hashlib
import struct
from typing import NamedTuple

import numpy as np

from sdplab.dataset import assert_canonical


class PreprocessResult(NamedTuple):
    n_selected: int
    sum_pt: float
    pt_z: np.ndarray


def preprocess(a: np.ndarray, pt_cut: float = 20.0, eta_cut: float = 2.4) -> PreprocessResult:
    assert_canonical(a)
    if a.shape[0] == 0:
        raise ValueError("cannot preprocess an empty array")
    pt = a["pt"]
    mask = (pt > pt_cut) & (np.abs(a["eta"]) < eta_cut)
    std = pt.std()
    if not std > 0:
        raise ValueError("pt column has zero standard deviation")
    return PreprocessResult(
        int(np.count_nonzero(mask)), float(pt[mask].sum()), (pt - pt.mean()) / std
    )


def digest(result: PreprocessResult) -> str:
    """SHA-256 over the three preprocessing outputs, bit for bit.

    The worker compares this digest with the one computed from the canonical dataset, so a
    preprocessing trial is checked against the result of the reference run.
    """
    h = hashlib.sha256()
    h.update(b"sdplab-preprocess-v1\0")
    h.update(struct.pack("<q", result.n_selected))
    h.update(struct.pack("<d", result.sum_pt))
    z = np.ascontiguousarray(result.pt_z)
    h.update(z.dtype.str.encode() + b"\0")
    h.update(struct.pack("<q", z.shape[0]))
    h.update(z)
    return h.hexdigest()
