"""Plots and a markdown report generated from raw result files only.

This is the only module that imports matplotlib (Agg backend: files, no display). Nothing here
re-runs a benchmark. The report states what was measured and the conditions, never a ranking
verdict; the caveat block is always included.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from sdplab.analysis import (
    QUANTILE_METHOD,
    flag_outliers,
    summarize,
    write_summary_csv,
)
from sdplab.results import read_run_json, read_trials

CAVEATS = (
    "These results come from a synthetic, HEP-inspired dataset (not real detector data) measured "
    "on one machine, with a warm OS page cache (a process restart does not clear the page cache), "
    "using CPython and NumPy. They are not representative of CERN-scale or production workloads, "
    "and this project is independent: it is not affiliated with or endorsed by CERN or CERN-HSF. "
    "Laptop power state, thermal throttling and background load affect timings; flagged trials "
    "are kept and counted, never removed. Memory figures are Linux-only process high-water marks; "
    "any figure labelled an estimate is not exact workload memory. No format is claimed to be "
    "universally fastest."
)
PALETTE = {
    "csv": ("#D55E00", "o"),
    "npy": ("#0072B2", "s"),
    "npz": ("#009E73", "^"),
    "npz_compressed": ("#CC79A7", "D"),
    "in_memory": ("#555555", "P"),
}
OPERATION_TITLES = {
    "write": "Write (no fsync)",
    "load": "Load",
    "preprocess": "Preprocess (in-memory data)",
    "load_preprocess": "Load + preprocess",
}


def _fmt(x: float | None, digits: int = 3) -> str:
    """Three significant digits; thousands separators instead of scientific notation."""
    if x is None:
        return "-"
    if abs(x) >= 10**digits:
        return f"{round(x):,}"
    return f"{x:.{digits}g}"


def _footer(run: dict) -> str:
    return f"run {run['run_id']} - synthetic data, one machine, warm cache"


def _style(variant: str) -> tuple[str, str]:
    return PALETTE.get(variant, ("#000000", "x"))


def plot_file_sizes(run: dict, out: Path) -> Path | None:
    datasets = run.get("datasets") or {}
    sizes = sorted(datasets, key=int)
    variants = sorted({v for d in datasets.values() for v in d["file_bytes"]})
    if not sizes or not variants:
        return None
    fig, ax = plt.subplots(figsize=(7, 4.2))
    width = 0.8 / len(variants)
    for i, v in enumerate(variants):
        xs = [k + i * width for k in range(len(sizes))]
        ys = [datasets[s]["file_bytes"].get(v, 0) / 1e6 for s in sizes]
        ax.bar(xs, ys, width=width, color=_style(v)[0], label=v)
    ax.set_xticks([k + 0.4 - width / 2 for k in range(len(sizes))], [f"{int(s):,}" for s in sizes])
    ax.set_yscale("log")
    ax.set_xlabel("rows")
    ax.set_ylabel("file size on disk (MB, decimal)")
    ax.set_title("File size by storage variant")
    ax.legend(frameon=False)
    fig.text(0.01, 0.01, _footer(run), fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _series(rows: list[dict], operation: str, value: str) -> dict[str, list[tuple[int, float]]]:
    series: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        if r["operation"] == operation and r[value] is not None:
            series.setdefault(r["variant"], []).append((r["rows"], r[value]))
    return {k: sorted(v) for k, v in series.items()}


def plot_time(
    run: dict, rows: list[dict], trials: list[dict], operation: str, out: Path
) -> Path | None:
    cells = [r for r in rows if r["operation"] == operation and r["median_ms"] is not None]
    if not cells:
        return None
    fig, ax = plt.subplots(figsize=(7, 4.4))
    for variant in sorted({r["variant"] for r in cells}):
        color, marker = _style(variant)
        mine = sorted((r for r in cells if r["variant"] == variant), key=lambda r: r["rows"])
        xs = [r["rows"] for r in mine]
        med = [r["median_ms"] for r in mine]
        lo = [r["median_ms"] - r["q1_ms"] for r in mine]
        hi = [r["q3_ms"] - r["median_ms"] for r in mine]
        ax.errorbar(xs, med, yerr=[lo, hi], color=color, marker=marker, capsize=3, label=variant)
        raw = [
            (t["dataset"]["rows"], t["timing"]["elapsed_ns"] / 1e6)
            for t in trials
            if t["phase"] == "measured"
            and t["variant"] == variant
            and t["operation"] == operation
            and t["status"] == "ok"
            and t["correct"] is True
        ]
        ax.scatter([a for a, _ in raw], [b for _, b in raw], color=color, alpha=0.25, s=12)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("rows")
    ax.set_ylabel("elapsed time (ms)")
    ax.set_title(f"{OPERATION_TITLES.get(operation, operation)}: median, IQR bars, raw trials")
    ax.legend(frameon=False)
    fig.text(0.01, 0.01, _footer(run), fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def plot_metric(
    run: dict, rows: list[dict], operation: str, column: str, title: str, ylabel: str, out: Path
) -> Path | None:
    series = _series(rows, operation, column)
    if not series:
        return None
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for variant, points in series.items():
        color, marker = _style(variant)
        ax.plot(
            [p[0] for p in points],
            [p[1] for p in points],
            color=color,
            marker=marker,
            label=variant,
        )
    ax.set_xscale("log")
    ax.set_xlabel("rows")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False)
    fig.text(0.01, 0.01, _footer(run), fontsize=7, color="#555555")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def _table(headers: list[str], body: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def render_markdown(
    run: dict, trials: list[dict], rows: list[dict], plots: dict[str, Path], truncated: bool
) -> str:
    cfg = run["config"]
    env = run["environment"]
    counts = run.get("counts", {})
    out: list[str] = [f"# Benchmark report - {run['run_id']}", ""]
    out += [
        "Generated by `sdplab report` from `trials.jsonl` and `run.json` only; nothing was re-run. "
        f"Run status: **{run['status']}**.",
        "",
        "## Conditions",
        "",
        _table(
            ["setting", "value"],
            [
                ["dataset seed", str(cfg["dataset"]["seed"])],
                ["rows", ", ".join(f"{n:,}" for n in cfg["dataset"]["sizes"])],
                ["variants", ", ".join(cfg["formats"]["enabled"])],
                [
                    "warm-up / measured rounds",
                    f"{cfg['trials']['warmup_rounds']} / {cfg['trials']['measured_rounds']}",
                ],
                ["order seed", str(cfg["trials"]["order_seed"])],
                ["cache mode", "warm (OS page cache not cleared)"],
                ["thread_env", cfg["environment"]["thread_env"]],
                ["Python / NumPy", f"{env.get('python')} / {env.get('numpy')}"],
                ["OS", str(env.get("os"))],
                ["CPU", f"{env.get('cpu_model')} ({env.get('cpu_count')} logical cores)"],
                ["RAM (bytes)", str(env.get("ram_bytes"))],
                ["data filesystem", str(env.get("filesystem_type"))],
                ["CPU governor / power", f"{env.get('cpu_governor')} / {env.get('power_source')}"],
                ["load average at start", str(env.get("loadavg_at_start"))],
                [
                    "git commit (dirty)",
                    f"{(env.get('git') or {}).get('commit')} ({(env.get('git') or {}).get('dirty')})",
                ],
            ],
        ),
        "",
    ]
    for w in run.get("warnings", []):
        out += [f"> warning: {w}", ""]
    out += [
        "## Correctness and failures",
        "",
        f"Trials recorded: {counts.get('trials', len(trials))} (warm-ups included, kept in the raw file). "
        f"Failed: {counts.get('failed', 0)}. Incorrect: {counts.get('incorrect', 0)}. "
        "Every dataset and every variant passed the bit-exact pre-run gate before any trial was timed. "
        "Failed and incorrect trials are excluded from the statistics below and counted per cell.",
    ]
    if truncated:
        out += [
            "",
            "> The trial file ended with a truncated line (interrupted run); it was ignored.",
        ]
    out += [""]

    for op in ("write", "load", "preprocess", "load_preprocess"):
        cells = [r for r in rows if r["operation"] == op]
        if not cells:
            continue
        out += [
            f"## {OPERATION_TITLES[op]}",
            "",
            f"Median [Q1-Q3] in ms (quantiles: {QUANTILE_METHOD}); n = accepted/total measured trials.",
            "",
        ]
        sizes = sorted({r["rows"] for r in cells})
        variants = sorted({r["variant"] for r in cells})
        body = []
        for v in variants:
            line = [v]
            for n in sizes:
                r = next((c for c in cells if c["variant"] == v and c["rows"] == n), None)
                if r is None or r["median_ms"] is None:
                    line.append(f"- (n={r['n_ok']}/{r['n_total']})" if r else "-")
                else:
                    line.append(
                        f"{_fmt(r['median_ms'])} [{_fmt(r['q1_ms'])}-{_fmt(r['q3_ms'])}] (n={r['n_ok']}/{r['n_total']})"
                    )
            body.append(line)
        out += [_table(["variant"] + [f"{n:,} rows" for n in sizes], body), ""]
        if plots.get(f"time_{op}"):
            out += [f"![{op}]({plots[f'time_{op}'].as_posix()})", ""]

    load_cells = [r for r in rows if r["operation"] == "load"]
    if load_cells:
        out += [
            "## Throughput and memory (load)",
            "",
            "Logical throughput = rows x 34 B / median time (same numerator for every variant). "
            "File throughput = on-disk bytes / median time (differs per variant). They are reported "
            "separately and must not be compared with each other. The memory estimate is "
            "`VmHWM - VmRSS(baseline)` per trial: an estimate, not exact workload memory.",
            "",
        ]
        body = [
            [
                f"{r['rows']:,}",
                r["variant"],
                _fmt(r["logical_throughput_mb_s"]),
                _fmt(r["file_throughput_mb_s"]),
                _fmt(r["file_bytes"] and r["file_bytes"] / 1e6),
                _fmt(r["median_vm_hwm_kib"]),
                _fmt(r["estimated_workload_rss_kib_median"]),
            ]
            for r in sorted(load_cells, key=lambda r: (r["rows"], r["variant"]))
        ]
        out += [
            _table(
                [
                    "rows",
                    "variant",
                    "logical MB/s",
                    "file MB/s",
                    "file MB",
                    "median VmHWM KiB",
                    "estimated workload KiB",
                ],
                body,
            ),
            "",
        ]
        for key in ("throughput_logical", "throughput_file", "memory_estimate", "file_size"):
            if plots.get(key):
                out += [f"![{key}]({plots[key].as_posix()})", ""]

    flagged = sum(r["n_outlier_flagged"] for r in rows)
    out += [
        "## Flags (kept, never removed)",
        "",
        f"Trials with high load average: {sum(r['n_noisy_load'] for r in rows)}. "
        f"Trials at least {cfg['noise']['outlier_factor']}x their cell median: {flagged}. "
        f"Trials whose `ru_maxrss` may be floored by the parent process: {sum(r['n_maxrss_floor_suspect'] for r in rows)}.",
        "",
        "## Caveats",
        "",
        CAVEATS,
        "",
    ]
    return "\n".join(out)


def build_report(run_dir: str | Path, example_root: str | Path | None = None) -> dict[str, Any]:
    """Write summary.csv, plots and a markdown report from the raw files; return the paths.

    By default outputs go to ``<results>/plots/<run_id>/`` and ``<results>/reports/<run_id>.md``
    and ``summary.csv`` next to the raw files. With ``example_root`` a self-contained, tracked-
    friendly copy is written to ``<example_root>/<run_id>/`` instead (raw files, summary, plots,
    report), refusing to overwrite an existing example.
    """
    run_dir = Path(run_dir)
    run = read_run_json(run_dir / "run.json")
    trials, truncated = read_trials(run_dir / "trials.jsonl")
    run_id = run["run_id"]
    if example_root is None:
        root = run_dir.parent.parent  # <results_dir>/raw/<run_id> -> <results_dir>
        plot_dir = root / "plots" / run_id
        report_path = root / "reports" / f"{run_id}.md"
        link_prefix = Path("..") / "plots" / run_id
        summary_path = run_dir / "summary.csv"
    else:
        dest = Path(example_root) / run_id
        dest.mkdir(parents=True, exist_ok=False)
        plot_dir = dest / "plots"
        report_path = dest / "report.md"
        link_prefix = Path("plots")
        summary_path = dest / "summary.csv"
        for name in ("run.json", "trials.jsonl"):
            shutil.copyfile(run_dir / name, dest / name)
    plot_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    factor = run["config"]["noise"]["outlier_factor"]
    rows = summarize(trials, factor)
    for t in flag_outliers(trials, factor):
        t["flags"]["outlier_vs_median"] = True
    write_summary_csv(rows, summary_path)
    if example_root is not None:
        write_summary_csv(rows, run_dir / "summary.csv")

    candidates = {"file_size": plot_file_sizes(run, plot_dir / "file_size.png")}
    for op in OPERATION_TITLES:
        candidates[f"time_{op}"] = plot_time(run, rows, trials, op, plot_dir / f"time_{op}.png")
    candidates["throughput_logical"] = plot_metric(
        run,
        rows,
        "load",
        "logical_throughput_mb_s",
        "Load: logical-payload throughput (median time)",
        "MB/s of logical payload",
        plot_dir / "throughput_logical.png",
    )
    candidates["throughput_file"] = plot_metric(
        run,
        rows,
        "load",
        "file_throughput_mb_s",
        "Load: on-disk file throughput (median time)",
        "MB/s of file bytes",
        plot_dir / "throughput_file.png",
    )
    candidates["memory_estimate"] = plot_metric(
        run,
        rows,
        "load",
        "estimated_workload_rss_kib_median",
        "Load: estimated workload memory (an estimate: VmHWM - baseline)",
        "KiB (estimate)",
        plot_dir / "memory_estimate.png",
    )
    plots = {k: v for k, v in candidates.items() if v is not None}
    rel = {k: link_prefix / v.name for k, v in plots.items()}
    report_path.write_text(render_markdown(run, trials, rows, rel, truncated), encoding="utf-8")
    return {"summary": summary_path, "report": report_path, "plots": plots, "rows": rows}


README_MARKERS = ("<!-- results:start -->", "<!-- results:end -->")


def readme_results_block(run: dict, rows: list[dict], example_dir: str) -> str:
    """The README results block, generated from a committed example run.

    A test regenerates this block from ``results/examples/<run_id>/`` and compares it with the
    README text between the markers, so every number in the README is traceable to that run.
    """
    env = run["environment"]
    cfg = run["config"]
    sizes = sorted({r["rows"] for r in rows})
    lines = [
        README_MARKERS[0],
        f"Source: [`{example_dir}`]({example_dir}) (`run.json`, `trials.jsonl`, `summary.csv`). "
        f"One run on one machine: {env.get('cpu_model')}, {env.get('cpu_count')} logical cores, "
        f"{(env.get('ram_bytes') or 0) / 2**30:.1f} GiB RAM, {env.get('os')}, "
        f"Python {env.get('python')}, NumPy {env.get('numpy')}, data on {env.get('filesystem_type')}, "
        f"CPU governor {env.get('cpu_governor')}, power {env.get('power_source')}, "
        f"warm OS page cache, thread_env `{cfg['environment']['thread_env']}`. "
        f"{cfg['trials']['warmup_rounds']} warm-up and {cfg['trials']['measured_rounds']} measured "
        "rounds per cell, one fresh process per trial. Cells show the median [Q1-Q3] in ms over the "
        "measured rounds, with the number of accepted trials.",
        "",
    ]
    for op in ("write", "load", "preprocess", "load_preprocess"):
        cells = [r for r in rows if r["operation"] == op]
        if not cells:
            continue
        lines += [f"**{OPERATION_TITLES[op]}**", ""]
        header = ["variant"] + [f"{n:,} rows" for n in sizes]
        body = []
        for v in sorted({r["variant"] for r in cells}):
            line = [v]
            for n in sizes:
                r = next((c for c in cells if c["variant"] == v and c["rows"] == n), None)
                if r is None or r["median_ms"] is None:
                    line.append("-")
                else:
                    line.append(
                        f"{_fmt(r['median_ms'])} [{_fmt(r['q1_ms'])}-{_fmt(r['q3_ms'])}] "
                        f"(n={r['n_ok']}/{r['n_total']})"
                    )
            body.append(line)
        lines += [_table(header, body), ""]
    datasets = run.get("datasets") or {}
    variants = sorted({v for d in datasets.values() for v in d["file_bytes"]})
    if variants:
        lines += ["**File size on disk (MB, decimal)**", ""]
        body = [
            [v] + [_fmt(datasets[str(n)]["file_bytes"][v] / 1e6) for n in sizes] for v in variants
        ]
        lines += [_table(["variant"] + [f"{n:,} rows" for n in sizes], body), ""]
    lines.append(README_MARKERS[1])
    return "\n".join(lines)
