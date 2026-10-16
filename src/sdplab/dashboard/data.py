"""Load, validate and shape recorded runs for display.

Single source of truth: runs are read with ``sdplab.results`` (schema-versioned readers),
checked with ``sdplab.results.validate_run`` (the same check as ``sdplab check-run``) and summarised
with ``sdplab.analysis.summarize``. Nothing scientific is recalculated here; this module only
selects, reshapes and labels recorded values.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from typing import Any

from sdplab.analysis import summarize
from sdplab.dashboard.discovery import ARTIFACT_LIMITS, RunRef, artifact_path, plot_paths
from sdplab.results import ResultsError, read_run_json, read_trials, validate_run

OPERATION_LABELS = {
    "write": "Write (no fsync)",
    "load": "Load",
    "preprocess": "Preprocess (in-memory data)",
    "load_preprocess": "Load + preprocess",
}
VARIANT_LABELS = {
    "csv": "CSV",
    "npy": "NPY",
    "npz": "NPZ (uncompressed)",
    "npz_compressed": "NPZ (compressed)",
    "in_memory": "In-memory (no file)",
}
VARIANT_ORDER = ["csv", "npy", "npz", "npz_compressed", "in_memory"]
_ABS_PATH = re.compile(r"(?:/[\w.\-]+){2,}")


class DashboardDataError(Exception):
    """A reason a run cannot be displayed, written for visitors (no paths, no tracebacks)."""


def scrub(text: str) -> str:
    """Remove absolute filesystem paths from a message before it reaches a visitor."""
    return _ABS_PATH.sub("<path>", text)


@dataclass(frozen=True)
class RunData:
    run_id: str
    run: dict
    trials: tuple[dict, ...]
    rows: tuple[dict, ...]
    problems: tuple[str, ...]
    summary_csv_matches: bool | None
    truncated: bool
    artifacts: tuple[str, ...]
    plots: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.problems and self.summary_csv_matches is not False

    @property
    def status(self) -> str:
        return str(self.run.get("status"))


def _summary_csv_matches(ref: RunRef, rows: tuple[dict, ...]) -> bool | None:
    """Does ``summary.csv`` agree with a recomputation from the raw trials? None if absent."""
    path = artifact_path(ref, "summary.csv")
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            recorded = {
                (int(r["rows"]), r["variant"], r["operation"]): r for r in csv.DictReader(fh)
            }
    except (OSError, ValueError, KeyError, csv.Error):
        return False
    if len(recorded) != len(rows):
        return False
    for r in rows:
        rec = recorded.get((r["rows"], r["variant"], r["operation"]))
        if rec is None or int(rec["n_ok"]) != r["n_ok"] or int(rec["n_total"]) != r["n_total"]:
            return False
        if r["median_ms"] is None:
            if rec["median_ms"] != "":
                return False
        elif rec["median_ms"] == "" or not math.isclose(
            float(rec["median_ms"]), r["median_ms"], rel_tol=1e-9
        ):
            return False
    return True


def load_run(ref: RunRef) -> RunData:
    """Read a run. Raises DashboardDataError when it cannot be read at all."""
    for name in ("run.json", "trials.jsonl"):
        if artifact_path(ref, name) is None:
            raise DashboardDataError(
                f"The run is missing {name}, or the file is too large to display."
            )
    try:
        run = read_run_json(ref.path / "run.json")
        trials, truncated = read_trials(ref.path / "trials.jsonl")
    except (ResultsError, OSError, ValueError) as exc:
        raise DashboardDataError(
            f"The run files could not be read as SDPLab results: {scrub(str(exc))}"
        ) from exc
    problems = tuple(scrub(p) for p in validate_run(ref.path))
    try:
        factor = run["config"]["noise"]["outlier_factor"]
        rows = tuple(summarize(trials, factor))
    except (KeyError, TypeError) as exc:
        raise DashboardDataError("run.json does not contain the expected configuration.") from exc
    return RunData(
        run_id=ref.run_id,
        run=run,
        trials=tuple(trials),
        rows=rows,
        problems=problems,
        summary_csv_matches=_summary_csv_matches(ref, rows),
        truncated=truncated,
        artifacts=tuple(n for n in ARTIFACT_LIMITS if artifact_path(ref, n) is not None),
        plots=tuple(p.name for p in plot_paths(ref)),
    )


# ------------------------------------------------------------------ numbers and labels


def fmt_num(x: float | None, digits: int = 3) -> str:
    """Three significant digits; thousands separators instead of scientific notation."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    if abs(x) >= 10**digits:
        return f"{round(x):,}"
    return f"{x:.{digits}g}"


def variant_label(variant: str) -> str:
    return VARIANT_LABELS.get(variant, variant)


def operation_label(operation: str) -> str:
    return OPERATION_LABELS.get(operation, operation)


# ------------------------------------------------------------------ overview facts


def overview_facts(data: RunData) -> dict[str, Any]:
    """Counts and identifiers read from the recorded run (nothing hardcoded)."""
    trials = data.trials
    measured = [t for t in trials if t["phase"] == "measured"]
    datasets = data.run.get("datasets", {})
    versions = {d.get("dataset", {}).get("generator_version") for d in datasets.values()}
    versions.discard(None)
    formats = sorted(
        {t["variant"] for t in trials if t["variant"] != "in_memory"},
        key=lambda v: VARIANT_ORDER.index(v) if v in VARIANT_ORDER else 99,
    )
    return {
        "run_id": data.run_id,
        "status": data.status,
        "formats": formats,
        "sizes": sorted(int(n) for n in datasets),
        "operations": sorted({t["operation"] for t in trials}),
        "trials_total": len(trials),
        "trials_measured": len(measured),
        "trials_warmup": len(trials) - len(measured),
        "failed": sum(1 for t in trials if t["status"] != "ok"),
        "incorrect": sum(1 for t in trials if t["status"] == "ok" and t["correct"] is False),
        "generator_versions": sorted(versions),
        "numpy": data.run.get("environment", {}).get("numpy"),
        "warmup_rounds": data.run["config"]["trials"]["warmup_rounds"],
        "measured_rounds": data.run["config"]["trials"]["measured_rounds"],
    }


# ------------------------------------------------------------------ frames and tables


def summary_frame(data: RunData):
    """Per (rows, variant, operation) recorded summary as a DataFrame (missing values are NaN)."""
    import pandas as pd

    df = pd.DataFrame(list(data.rows))
    df["variant_label"] = df["variant"].map(variant_label)
    df["operation_label"] = df["operation"].map(operation_label)
    return df


def trials_frame(data: RunData):
    """One row per recorded trial with the fields a reviewer needs (times in milliseconds)."""
    import pandas as pd

    def ms(ns: int | None) -> float | None:
        return None if ns is None else ns / 1e6

    records = []
    for t in data.trials:
        res, timing, flags = t["resources"], t["timing"], t["flags"]
        records.append(
            {
                "rows": t["dataset"]["rows"],
                "variant": t["variant"],
                "operation": t["operation"],
                "phase": t["phase"],
                "round": t["round"],
                "position": t["position"],
                "status": t["status"],
                "correct": t["correct"],
                "elapsed_ms": ms(timing["elapsed_ns"]),
                "process_cpu_ms": ms(timing["process_time_ns"]),
                "subprocess_wall_ms": ms(timing["subprocess_wall_ns"]),
                "file_bytes": (t["sizes"] or {}).get("file_bytes"),
                "ru_maxrss_kib": res.get("ru_maxrss_kib"),
                "vm_hwm_kib": res.get("vm_hwm_kib"),
                "vm_rss_baseline_kib": res.get("vm_rss_baseline_kib"),
                "noisy_load": flags["noisy_load"],
                "maxrss_floor_suspect": flags["maxrss_floor_suspect"],
                "error": t["error"],
            }
        )
    return pd.DataFrame(records)


def file_size_frame(data: RunData):
    """Recorded on-disk size of each variant's file per dataset size (MB, decimal)."""
    import pandas as pd

    records = [
        {
            "rows": int(n),
            "variant": v,
            "variant_label": variant_label(v),
            "file_mb": size / 1e6,
        }
        for n, d in data.run.get("datasets", {}).items()
        for v, size in d.get("file_bytes", {}).items()
    ]
    return pd.DataFrame(records)


def comparison_table(summary, data: RunData, operation: str, rows: int, formats: list[str]):
    """Display table for one operation and size; every value is a recorded or derived-by-analysis one."""
    import pandas as pd

    sel = summary[
        (summary["operation"] == operation)
        & (summary["rows"] == rows)
        & (summary["variant"].isin(formats))
    ].copy()
    sizes = data.run.get("datasets", {}).get(str(rows), {}).get("file_bytes", {})
    sel["file_mb"] = sel["variant"].map(lambda v: sizes[v] / 1e6 if v in sizes else math.nan)
    sel["order"] = sel["variant"].map(
        lambda v: VARIANT_ORDER.index(v) if v in VARIANT_ORDER else 99
    )
    sel = sel.sort_values("order")
    return pd.DataFrame(
        {
            "Format": sel["variant_label"].to_list(),
            "variant": sel["variant"].to_list(),
            "Median (ms)": sel["median_ms"].to_list(),
            "Q1 (ms)": sel["q1_ms"].to_list(),
            "Q3 (ms)": sel["q3_ms"].to_list(),
            "IQR (ms)": sel["iqr_ms"].to_list(),
            "File size (MB)": sel["file_mb"].to_list(),
            "Logical throughput (MB/s)": sel["logical_throughput_mb_s"].to_list(),
            "File throughput (MB/s)": sel["file_throughput_mb_s"].to_list(),
            "Accepted / total trials": [
                f"{a}/{b}" for a, b in zip(sel["n_ok"], sel["n_total"], strict=True)
            ],
            "Failed": sel["n_failed"].to_list(),
            "Incorrect": sel["n_incorrect"].to_list(),
            "Flagged (load / outlier)": [
                f"{a} / {b}"
                for a, b in zip(sel["n_noisy_load"], sel["n_outlier_flagged"], strict=True)
            ],
            "Estimated workload memory (KiB, estimate)": sel[
                "estimated_workload_rss_kib_median"
            ].to_list(),
        }
    )


def scoped_findings(table, operation: str, rows: int) -> list[str]:
    """Plain statements scoped to one operation, size and run; never a universal ranking."""
    scope = f"for {operation_label(operation).lower()} at {rows:,} rows in this run"
    timed = table[table["Median (ms)"].notna()].sort_values("Median (ms)")
    out: list[str] = []
    if len(timed) >= 1:
        best = timed.iloc[0]
        text = (
            f"Lowest median time {scope}: **{best['Format']}** "
            f"({fmt_num(best['Median (ms)'])} ms, IQR {fmt_num(best['Q1 (ms)'])}-{fmt_num(best['Q3 (ms)'])})."
        )
        if len(timed) >= 2:
            second = timed.iloc[1]
            if second["Q1 (ms)"] <= best["Q3 (ms)"]:
                text += f" Its interquartile range overlaps {second['Format']}'s, so they are not clearly separated."
        out.append(text)
    if len(table) and (table["Failed"].sum() or table["Incorrect"].sum()):
        out.append(
            "Some trials failed or were incorrect; those cells use only the accepted trials."
        )
    sized = table[table["File size (MB)"].notna()]
    if operation != "preprocess" and len(sized):
        small = sized.sort_values("File size (MB)").iloc[0]
        out.append(
            f"Smallest file at {rows:,} rows in this run: **{small['Format']}** ({fmt_num(small['File size (MB)'])} MB)."
        )
    return out


def docs_markdown(markdown: str, repo_url: str | None) -> str:
    """Drop the title and rewrite relative links so they resolve on GitHub (or to plain text)."""
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    text = "\n".join(lines)

    def link(m: re.Match[str]) -> str:
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "#", "mailto:")):
            return m.group(0)
        if repo_url:
            return f"[{label}]({repo_url.rstrip('/')}/blob/main/docs/{target})"
        return label

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)
