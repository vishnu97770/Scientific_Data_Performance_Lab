"""Dataset: EVENT_DTYPE, deterministic generator and a shape-aware identity hash.

The canonical in-memory form is a 1-D C-contiguous structured array of EVENT_DTYPE
(little-endian, packed, 34 bytes per row).

Reproducibility: the same (seed, row count, GENERATOR_VERSION) gives byte-identical data within
one NumPy version and platform. NumPy does not promise identical random streams across versions,
so every dataset record stores the NumPy version and a content hash, and a regenerated hash that
differs from a recorded one is reported as "dataset differs". GENERATOR_VERSION is bumped
whenever a distribution parameter or draw order in ``generate`` changes.
"""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np

EVENT_DTYPE = np.dtype(
    [("event_id", "<i8"), ("pt", "<f8"), ("eta", "<f8"), ("phi", "<f8"), ("category_code", "<i2")]
)
ROW_BYTES = 34
GENERATOR_VERSION = 1
CATEGORY_CODES = (0, 1, 2, 3, 4)
CATEGORY_WEIGHTS = (0.40, 0.30, 0.15, 0.10, 0.05)
ETA_LIMIT = 2.5
_HASH_DOMAIN = b"sdplab-array-v1"


def dtype_description(dt: np.dtype) -> str:
    """Canonical text of a structured dtype.

    Built from names, format strings, offsets and itemsize, because ``dtype.descr`` raises for
    out-of-order fields and ``str``/``repr`` text varies between NumPy versions.
    """
    if dt.names is None:
        raise TypeError("structured dtype required")
    return json.dumps(
        {
            "names": list(dt.names),
            "formats": [dt.fields[n][0].str for n in dt.names],
            "offsets": [dt.fields[n][1] for n in dt.names],
            "itemsize": dt.itemsize,
        },
        separators=(",", ":"),
    )


EXPECTED_DESCRIPTION = dtype_description(EVENT_DTYPE)


class NotCanonicalError(ValueError):
    """The array is not the canonical 1-D C-contiguous packed little-endian EVENT_DTYPE array."""


def assert_canonical(a: object) -> None:
    """Raise NotCanonicalError unless ``a`` is a canonical dataset array."""
    if type(a) is not np.ndarray:
        raise NotCanonicalError(f"type {type(a).__name__} is not a plain numpy.ndarray")
    if a.dtype != EVENT_DTYPE or dtype_description(a.dtype) != EXPECTED_DESCRIPTION:
        raise NotCanonicalError("dtype differs from EVENT_DTYPE")
    if a.dtype.isalignedstruct or a.dtype.itemsize != ROW_BYTES:
        raise NotCanonicalError("dtype is aligned or padded")
    if a.ndim != 1:
        raise NotCanonicalError(f"expected a 1-D array, got ndim={a.ndim}")
    if not a.flags.c_contiguous:
        raise NotCanonicalError("array is not C-contiguous")


def identity_sha256(a: np.ndarray) -> str:
    """SHA-256 over domain tag, dtype description, shape and raw bytes.

    No canonical-form requirement, so tests can show that the hash distinguishes packed from
    aligned dtypes, byte orders, renamed fields and shapes.
    """
    if not a.flags.c_contiguous:
        raise NotCanonicalError("array is not C-contiguous")
    h = hashlib.sha256()
    h.update(_HASH_DOMAIN + b"\0")
    h.update(dtype_description(a.dtype).encode() + b"\0")
    h.update(json.dumps(list(a.shape)).encode() + b"\0")
    h.update(a)
    return h.hexdigest()


def array_sha256(a: np.ndarray) -> str:
    """Dataset identity hash: canonical-form check, then ``identity_sha256``."""
    assert_canonical(a)
    return identity_sha256(a)


def generate(n: int, seed: int) -> np.ndarray:
    """Generate ``n`` synthetic HEP-inspired events deterministically from ``seed``.

    One independent random stream per column (``SeedSequence.spawn``), each drawn in a single
    call, so adding a column cannot change the others. Only lognormal, normal, uniform and
    random draws are used.
    """
    if type(n) is not int or n < 0:
        raise ValueError("n must be a non-negative int")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a non-negative int")
    _, c_pt, c_eta, c_phi, c_cat = np.random.SeedSequence(seed).spawn(5)
    out = np.zeros(n, dtype=EVENT_DTYPE)
    out["event_id"] = np.arange(n, dtype="<i8")
    out["pt"] = np.random.default_rng(c_pt).lognormal(mean=3.0, sigma=0.8, size=n)
    out["eta"] = np.clip(
        np.random.default_rng(c_eta).normal(0.0, 1.5, size=n), -ETA_LIMIT, ETA_LIMIT
    )
    out["phi"] = np.random.default_rng(c_phi).uniform(-math.pi, math.pi, size=n)
    cdf = np.cumsum(np.asarray(CATEGORY_WEIGHTS))
    cdf[-1] = 1.0
    u = np.random.default_rng(c_cat).random(n)
    codes = np.asarray(CATEGORY_CODES, dtype="<i2")
    out["category_code"] = codes[np.searchsorted(cdf, u, side="right")]
    return out


def dataset_record(seed: int, a: np.ndarray) -> dict:
    """Record identifying exactly what was generated: seed, rows, versions, dtype, hash."""
    return {
        "seed": seed,
        "rows": int(a.shape[0]),
        "generator_version": GENERATOR_VERSION,
        "numpy_version": np.__version__,
        "dtype": json.loads(dtype_description(a.dtype)),
        "sha256": array_sha256(a),
    }
