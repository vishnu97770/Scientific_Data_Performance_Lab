"""Summary statistics derived from raw trials only (no benchmark is rerun).

Headline statistic: the median, with Q1/Q3/IQR, min, max, mean and standard deviation alongside.
Quantiles use linear interpolation between order statistics (NumPy's default, "R-7"); with n = 7
measured rounds that gives IQR = x[5] - x[3] (zero-based), and a different method would give a
different IQR, so the method is written into every row. There are no significance tests and no
automatic outlier removal: noisy trials are flagged, counted and kept. Throughput is reported in
two separate columns and never mixed: logical-payload (rows x 34 B / time) and on-disk
(file bytes / time).
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

QUANTILE_METHOD = "linear"
MB = 1_000_000.0
COLUMNS = (
    "rows",
    "variant",
    "operation",
    "n_total",
    "n_ok",
    "n_failed",
    "n_incorrect",
    "n_noisy_load",
    "n_outlier_flagged",
    "n_maxrss_floor_suspect",
    "quantile_method",
    "median_ms",
    "q1_ms",
    "q3_ms",
    "iqr_ms",
    "min_ms",
    "max_ms",
    "mean_ms",
    "stdev_ms",
    "median_ratio_vs_csv",
    "logical_bytes",
    "file_bytes",
    "logical_throughput_mb_s",
    "file_throughput_mb_s",
    "median_ru_maxrss_kib",
    "median_vm_hwm_kib",
    "median_vm_rss_baseline_kib",
    "estimated_workload_rss_kib_median",
    "median_subprocess_wall_ms",
    "median_non_operation_ms",
)


def quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted, non-empty list."""
    if not sorted_values:
        raise ValueError("quantile of an empty sample")
    pos = (len(sorted_values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def median(values: list[float]) -> float | None:
    return quantile(sorted(values), 0.5) if values else None


def stdev(values: list[float]) -> float | None:
    """Sample standard deviation (n - 1); None for fewer than two values."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _accepted(t: dict) -> bool:
    return t["phase"] == "measured" and t["status"] == "ok" and t["correct"] is True


def summarize(trials: list[dict], outlier_factor: float = 3.0) -> list[dict[str, Any]]:
    """One row per (rows, variant, operation) cell over the measured rounds."""
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for t in trials:
        if t["phase"] == "measured":
            cells[(t["dataset"]["rows"], t["variant"], t["operation"])].append(t)

    rows: list[dict[str, Any]] = []
    for (n_rows, variant, op), group in sorted(cells.items()):
        ok = [t for t in group if _accepted(t)]
        times = sorted(t["timing"]["elapsed_ns"] / 1e6 for t in ok)
        med = quantile(times, 0.5) if times else None
        flagged = sum(1 for v in times if med and v >= outlier_factor * med)

        def med_of(values: list[float]) -> float | None:
            return median([v for v in values if v is not None])

        hwm = [t["resources"]["vm_hwm_kib"] for t in ok]
        base = [t["resources"]["vm_rss_baseline_kib"] for t in ok]
        est = [
            max(h - b, 0) for h, b in zip(hwm, base, strict=True) if h is not None and b is not None
        ]
        file_bytes = med_of([t["sizes"].get("file_bytes") for t in ok])
        logical = n_rows * 34
        q1 = quantile(times, 0.25) if times else None
        q3 = quantile(times, 0.75) if times else None
        rows.append(
            {
                "rows": n_rows,
                "variant": variant,
                "operation": op,
                "n_total": len(group),
                "n_ok": len(ok),
                "n_failed": sum(1 for t in group if t["status"] != "ok"),
                "n_incorrect": sum(
                    1 for t in group if t["status"] == "ok" and t["correct"] is False
                ),
                "n_noisy_load": sum(1 for t in group if t["flags"]["noisy_load"]),
                "n_outlier_flagged": flagged,
                "n_maxrss_floor_suspect": sum(
                    1 for t in group if t["flags"]["maxrss_floor_suspect"]
                ),
                "quantile_method": QUANTILE_METHOD,
                "median_ms": med,
                "q1_ms": q1,
                "q3_ms": q3,
                "iqr_ms": (q3 - q1) if times else None,
                "min_ms": times[0] if times else None,
                "max_ms": times[-1] if times else None,
                "mean_ms": (sum(times) / len(times)) if times else None,
                "stdev_ms": stdev(times),
                "median_ratio_vs_csv": None,
                "logical_bytes": logical,
                "file_bytes": file_bytes,
                "logical_throughput_mb_s": (logical / MB) / (med / 1000.0) if med else None,
                "file_throughput_mb_s": (
                    (file_bytes / MB) / (med / 1000.0) if med and file_bytes else None
                ),
                "median_ru_maxrss_kib": med_of([t["resources"]["ru_maxrss_kib"] for t in ok]),
                "median_vm_hwm_kib": med_of(hwm),
                "median_vm_rss_baseline_kib": med_of(base),
                "estimated_workload_rss_kib_median": median(est),
                "median_subprocess_wall_ms": med_of(
                    [t["timing"]["subprocess_wall_ns"] / 1e6 for t in ok]
                ),
                "median_non_operation_ms": med_of(
                    [
                        (t["timing"]["subprocess_wall_ns"] - t["timing"]["elapsed_ns"]) / 1e6
                        for t in ok
                    ]
                ),
            }
        )

    baseline = {
        (r["rows"], r["operation"]): r["median_ms"]
        for r in rows
        if r["variant"] == "csv" and r["median_ms"]
    }
    for r in rows:
        base_ms = baseline.get((r["rows"], r["operation"]))
        if base_ms and r["median_ms"] is not None and r["variant"] != "in_memory":
            r["median_ratio_vs_csv"] = r["median_ms"] / base_ms
    return rows


def flag_outliers(trials: list[dict], outlier_factor: float) -> list[dict]:
    """Return the accepted measured trials at least ``outlier_factor`` x their cell median.

    These are flagged for the reader; they are never removed from any statistic.
    """
    by_cell: dict[tuple, list[dict]] = defaultdict(list)
    for t in trials:
        if _accepted(t):
            by_cell[(t["dataset"]["rows"], t["variant"], t["operation"])].append(t)
    flagged = []
    for group in by_cell.values():
        med = median([t["timing"]["elapsed_ns"] for t in group])
        flagged.extend(
            t for t in group if med and t["timing"]["elapsed_ns"] >= outlier_factor * med
        )
    return flagged


def write_summary_csv(rows: list[dict[str, Any]], path: str | Path) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if r[k] is None else r[k]) for k in COLUMNS})
