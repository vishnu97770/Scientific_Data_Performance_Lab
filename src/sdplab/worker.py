"""One timed operation per fresh process (``python -m sdplab.worker``).

Protocol: a JSON request on stdin, exactly one JSON object on stdout, nothing else on stdout.
The operation is timed with ``time.perf_counter_ns`` *inside* this process, so interpreter
start-up and imports are excluded. Order inside a trial:

    setup (untimed) -> baseline counters -> timer -> operation -> timer -> peak counters
    -> correctness check (untimed)

Memory counters are read before the correctness check so hashing cannot inflate them. They are
process-wide high-water marks and Linux-only; see docs/adr/ADR-005.md.

Two jobs: ``trial`` (one operation on one variant) and ``prepare`` (generate the canonical
dataset, write every variant, and validate each by loading it back; untimed).
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from sdplab.dataset import array_sha256, dataset_record, generate
from sdplab.formats import VARIANTS, variant_filename
from sdplab.preprocess import digest, preprocess
from sdplab.validate import Mismatch, assert_arrays_identical, assert_preprocess_identical

OPERATIONS = ("write", "load", "preprocess", "load_preprocess")
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _proc_status() -> dict[str, int | None]:
    """VmHWM and VmRSS in KiB from /proc/self/status (Linux); None when unavailable."""
    out: dict[str, int | None] = {"VmHWM": None, "VmRSS": None}
    try:
        text = Path("/proc/self/status").read_text(encoding="utf-8")
    except OSError:
        return out
    for key in out:
        m = re.search(rf"^{key}:\s+(\d+) kB", text, flags=re.M)
        if m:
            out[key] = int(m.group(1))
    return out


def _reset_hwm() -> bool:
    """Best effort: reset VmHWM to the current RSS so the peak reflects the timed region."""
    try:
        Path("/proc/self/clear_refs").write_text("5", encoding="utf-8")
    except OSError:
        return False
    return True


def _ru_maxrss_kib() -> int | None:
    try:
        import resource  # Unix only, so imported here and not at module level
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)  # KiB on Linux


def _canonical_path(req: dict) -> Path:
    return Path(req["data_dir"]) / variant_filename(req["variant"], req["rows"])


def _prime(op: str, variant, req: dict) -> None:
    """Untimed: run the operation once on a tiny array.

    Lazy imports (for example ``zipfile`` inside ``np.load`` on an .npz) and first-call code
    paths would otherwise be paid inside the timed region of a fresh process, which would
    measure module import, not data work. The tiny file is separate from the data under test, so
    this does not warm the page cache for it.
    """
    tiny = generate(8, req["seed"])
    if op == "preprocess":
        preprocess(tiny, req["pt_cut"], req["eta_cut"])
        return
    scratch = Path(req["scratch_dir"])
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / f"prime_{req['variant']}{variant.extension}"
    variant.write(path, tiny)
    if op != "write":
        loaded = variant.load(path)
        if op == "load_preprocess":
            preprocess(loaded, req["pt_cut"], req["eta_cut"])
    path.unlink(missing_ok=True)


def run_trial(req: dict) -> dict:
    op = req["operation"]
    if op not in OPERATIONS:
        raise ValueError(f"unknown operation {op!r}")
    # preprocess runs on in-memory data and does not depend on a storage variant
    variant = None if op == "preprocess" else VARIANTS[req["variant"]]
    pt_cut, eta_cut = req["pt_cut"], req["eta_cut"]
    expected = req["expected"]

    # ---- setup (untimed)
    array = None
    path = None if op == "preprocess" else _canonical_path(req)
    if op in ("write", "preprocess"):
        array = generate(req["rows"], req["seed"])
    if op == "write":
        scratch = Path(req["scratch_dir"])
        scratch.mkdir(parents=True, exist_ok=True)
        path = scratch / variant_filename(req["variant"], req["rows"])
        path.unlink(missing_ok=True)

    _prime(op, variant, req)
    hwm_reset = _reset_hwm()
    before = _proc_status()
    cpu0, t0 = time.process_time_ns(), time.perf_counter_ns()

    # ---- timed region
    if op == "write":
        variant.write(path, array)
    elif op == "load":
        loaded = variant.load(path)
    elif op == "preprocess":
        result = preprocess(array, pt_cut, eta_cut)
    else:  # load_preprocess
        loaded = variant.load(path)
        result = preprocess(loaded, pt_cut, eta_cut)

    t1, cpu1 = time.perf_counter_ns(), time.process_time_ns()
    after = _proc_status()
    ru_maxrss = _ru_maxrss_kib()

    # ---- correctness (untimed, after the counters were read)
    if op == "write":
        check = "write_read_back_hash"
        correct = array_sha256(variant.load(path)) == expected["array_sha256"]
        file_bytes = path.stat().st_size
    elif op == "load":
        check = "hash_of_loaded_array"
        correct = array_sha256(loaded) == expected["array_sha256"]
        file_bytes = path.stat().st_size
    elif op == "preprocess":
        check = "preprocess_digest"
        correct = digest(result) == expected["preprocess_digest"]
        file_bytes = None
    else:
        check = "hash_and_preprocess_digest"
        correct = (
            array_sha256(loaded) == expected["array_sha256"]
            and digest(result) == expected["preprocess_digest"]
        )
        file_bytes = path.stat().st_size

    return {
        "status": "ok",
        "correct": bool(correct),
        "correctness_check": check,
        "timing": {"elapsed_ns": t1 - t0, "process_time_ns": cpu1 - cpu0},
        "resources": {
            "ru_maxrss_kib": ru_maxrss,
            "vm_hwm_kib": after["VmHWM"],
            "vm_rss_baseline_kib": before["VmRSS"],
            "vm_hwm_baseline_kib": before["VmHWM"],
            "hwm_reset": hwm_reset,
        },
        "primed": True,
        "sizes": {"logical_bytes": req["rows"] * 34, "file_bytes": file_bytes},
        "thread_env": {name: os.environ.get(name) for name in THREAD_VARIABLES},
    }


def run_prepare(req: dict, *, write: bool = True) -> dict:
    """Generate the dataset and validate each requested variant against it.

    With ``write`` the variant files are (re)written first (job ``prepare``); without it the
    existing files are only loaded and compared (job ``validate``). Untimed.
    """
    rows, seed = req["rows"], req["seed"]
    data_dir = Path(req["data_dir"])
    if write:
        data_dir.mkdir(parents=True, exist_ok=True)
    canonical = generate(rows, seed)
    record = dataset_record(seed, canonical)
    reference = preprocess(canonical, req["pt_cut"], req["eta_cut"])
    files: dict[str, int] = {}
    problems: list[dict] = []
    for name in req["variants"]:
        path = data_dir / variant_filename(name, rows)
        if write:
            VARIANTS[name].write(path, canonical)
        elif not path.is_file():
            problems.append({"variant": name, "aspect": "missing", "detail": str(path)})
            continue
        files[name] = path.stat().st_size
        try:
            loaded = VARIANTS[name].load(path)
            assert_arrays_identical(canonical, loaded)
            assert_preprocess_identical(
                reference, preprocess(loaded, req["pt_cut"], req["eta_cut"])
            )
        except Mismatch as exc:
            problems.append({"variant": name, "aspect": exc.aspect, "detail": exc.detail})
    return {
        "status": "ok" if not problems else "mismatch",
        "dataset": record,
        "array_sha256": record["sha256"],
        "preprocess_digest": digest(reference),
        "files": files,
        "problems": problems,
    }


def handle(req: dict) -> dict:
    job = req.get("job", "trial")
    if job == "trial":
        return run_trial(req)
    if job == "prepare":
        return run_prepare(req)
    if job == "validate":
        return run_prepare(req, write=False)
    raise ValueError(f"unknown job {job!r}")


def main() -> int:
    try:
        req = json.loads(sys.stdin.read())
        out = handle(req)
    except Exception as exc:  # every failure becomes a recorded failed trial
        out = {
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=8),
        }
    sys.stdout.write(json.dumps(out, allow_nan=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
