"""The four storage variants of the same structured array: csv, npy, npz, npz_compressed.

Every variant stores the canonical EVENT_DTYPE array and ``load`` returns a plain in-memory
C-contiguous ndarray of that dtype (never a memmap or a lazy archive member).

Loaders validate the *schema* of what they read and raise ``FormatError`` for anything that is
not the expected layout: wrong dtype, wrong dimensionality, wrong CSV header or column count,
unparseable or silently-castable values, extra or missing archive members, pickled objects,
corrupt or truncated files. They never cast or repair. A missing file raises FileNotFoundError.
Loaders do not compare *values* to a reference: bit-exact correctness is judged by
``sdplab.validate`` against the regenerated dataset.

Representation notes (these differences are part of what the benchmark measures):
  csv             text; header row + one row per event; ints as %d, float64 as %.17g (enough digits
                  to round-trip every finite float64); parsed by numpy.loadtxt with an explicit
                  dtype. Deprecation warnings from the parser (for example "1.0" in an integer
                  column, or an out-of-range int16 that older NumPy wraps) are treated as errors
                  so behaviour does not depend on the NumPy version.
  npy             one .npy file holding the structured array.
  npz             ZIP archive (stored) with one member, ``events``.
  npz_compressed  ZIP archive (DEFLATE, zlib default level) with one member, ``events``.
Limits: NaN payloads are not preserved by CSV (the dataset contains no NaN). Pickled/object
arrays are refused (``allow_pickle=False``).
"""

from __future__ import annotations

import warnings
import zipfile
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sdplab.dataset import EVENT_DTYPE

CSV_HEADER = ",".join(EVENT_DTYPE.names)
_CSV_FORMATS = ("%d", "%.17g", "%.17g", "%.17g", "%d")
NPZ_MEMBER = "events"
_LOW_LEVEL_ERRORS = (ValueError, EOFError, OSError, zipfile.BadZipFile, zlib.error, KeyError)


class FormatError(ValueError):
    """A file does not hold the canonical dataset in the expected layout."""


@contextmanager
def _reading(path: str | Path, kind: str) -> Iterator[None]:
    """Turn parser/archive failures into FormatError; let a missing file propagate unchanged."""
    try:
        yield
    except FileNotFoundError:
        raise
    except FormatError:
        raise
    except _LOW_LEVEL_ERRORS as exc:
        raise FormatError(f"{kind} file {path}: {type(exc).__name__}: {exc}") from exc
    except DeprecationWarning as exc:  # raised as an error inside the strict CSV parse
        raise FormatError(f"{kind} file {path}: value would be silently cast ({exc})") from exc


def _require_schema(arr: object, path: str | Path, kind: str) -> np.ndarray:
    if type(arr) is not np.ndarray:
        raise FormatError(f"{kind} file {path}: expected an ndarray, got {type(arr).__name__}")
    if arr.dtype != EVENT_DTYPE:
        raise FormatError(f"{kind} file {path}: dtype {arr.dtype} is not the canonical EVENT_DTYPE")
    if arr.ndim != 1:
        raise FormatError(f"{kind} file {path}: expected a 1-D array, got ndim={arr.ndim}")
    return np.ascontiguousarray(arr)


def write_csv(path: str | Path, a: np.ndarray) -> None:
    np.savetxt(
        path,
        a,
        fmt=_CSV_FORMATS,
        delimiter=",",
        newline="\n",
        header=CSV_HEADER,
        comments="",
        encoding="utf-8",
    )


def load_csv(path: str | Path) -> np.ndarray:
    with _reading(path, "csv"):
        with open(path, encoding="utf-8", newline="") as fh:
            header = fh.readline().rstrip("\r\n")
        if header != CSV_HEADER:
            raise FormatError(f"csv file {path}: header {header!r} != {CSV_HEADER!r}")
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            # A header-only file means zero rows; loadtxt warns about it instead of failing.
            warnings.filterwarnings(
                "ignore", message=".*input contained no data.*", category=UserWarning
            )
            out = np.loadtxt(
                path, dtype=EVENT_DTYPE, delimiter=",", skiprows=1, ndmin=1, encoding="utf-8"
            )
        return _require_schema(out, path, "csv")


def write_npy(path: str | Path, a: np.ndarray) -> None:
    # A file object avoids numpy appending its own extension to the path.
    with open(path, "wb") as fh:
        np.save(fh, a, allow_pickle=False)


def load_npy(path: str | Path) -> np.ndarray:
    with _reading(path, "npy"):
        # Own the handle: np.load leaks it when the file is corrupt or truncated.
        with open(path, "rb") as fh:
            arr = np.load(fh, allow_pickle=False)
        return _require_schema(arr, path, "npy")


def write_npz(path: str | Path, a: np.ndarray) -> None:
    # Never pass allow_pickle to savez: NumPy 2.1 stores it as an extra array member.
    with open(path, "wb") as fh:
        np.savez(fh, **{NPZ_MEMBER: a})


def write_npz_compressed(path: str | Path, a: np.ndarray) -> None:
    with open(path, "wb") as fh:
        np.savez_compressed(fh, **{NPZ_MEMBER: a})


def load_npz(path: str | Path) -> np.ndarray:
    with _reading(path, "npz"):
        with open(path, "rb") as fh:  # own the handle: np.load leaks it on corrupt input
            archive = np.load(fh, allow_pickle=False)
            if type(archive) is not np.lib.npyio.NpzFile:  # for example a plain .npy file
                raise FormatError(f"npz file {path}: not a zip archive of arrays")
            try:
                if archive.files != [NPZ_MEMBER]:
                    found = archive.files
                    raise FormatError(
                        f"npz file {path}: expected one member {NPZ_MEMBER!r}, found {found}"
                    )
                member = archive[NPZ_MEMBER]  # read once, inside the open handle
            finally:
                archive.close()
        return _require_schema(member, path, "npz")


@dataclass(frozen=True)
class Variant:
    name: str
    extension: str
    write: Callable[[str | Path, np.ndarray], None]
    load: Callable[[str | Path], np.ndarray]


VARIANTS: dict[str, Variant] = {
    v.name: v
    for v in (
        Variant("csv", ".csv", write_csv, load_csv),
        Variant("npy", ".npy", write_npy, load_npy),
        Variant("npz", ".npz", write_npz, load_npz),
        Variant("npz_compressed", ".npz", write_npz_compressed, load_npz),
    )
}


def variant_filename(variant: str, rows: int) -> str:
    """Stable file name for one variant and size, e.g. ``events_1000_npz_compressed.npz``."""
    return f"events_{rows}_{variant}{VARIANTS[variant].extension}"
