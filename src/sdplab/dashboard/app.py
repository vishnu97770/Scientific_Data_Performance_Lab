"""Streamlit pages for the read-only results explorer.

All values come from recorded runs through ``sdplab.dashboard.data`` (which reuses the benchmark
package's own readers, validator and summary code). The app never runs a benchmark, never accepts
paths or code from visitors, and never shows local filesystem paths or tracebacks.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import streamlit as st

from sdplab.dashboard import charts
from sdplab.dashboard.data import (
    OPERATION_LABELS,
    VARIANT_ORDER,
    DashboardDataError,
    RunData,
    comparison_table,
    docs_markdown,
    file_size_frame,
    load_run,
    operation_label,
    overview_facts,
    scoped_findings,
    summary_frame,
    trials_frame,
    variant_label,
)
from sdplab.dashboard.discovery import (
    RESULTS_ENV,
    RunRef,
    artifact_path,
    default_results_root,
    discover_runs,
    plot_paths,
    signature,
)

log = logging.getLogger("sdplab.dashboard")
REPO_ENV = "SDPLAB_REPO_URL"
DEFAULT_REPO_URL = "https://github.com/vishnu97770/Scientific_Data_Performance_Lab"
TRIAL_PAGE_SIZE = 200
DISCLAIMER = (
    "Independent educational project. It is not affiliated with, endorsed by, or an official "
    "project of CERN or CERN-HSF."
)
CAVEAT = (
    "These are **recorded measurements** from one run on one machine (warm OS page cache, "
    "synthetic data, CPython + NumPy). They are not measured on your device, not a general ranking "
    "of formats, and not representative of production-scale workloads."
)
FORMAT_BLURBS = {
    "csv": "Text: one line per event; values must be parsed from text.",
    "npy": "Binary: a header plus the raw structured records.",
    "npz": "ZIP archive (stored) holding the same array as one member.",
    "npz_compressed": "ZIP archive with DEFLATE compression, same member.",
}


# ---------------------------------------------------------------- cached, read-only loading


@st.cache_data(show_spinner="Loading the recorded run...", max_entries=6)
def _load_cached(path: str, sig: tuple) -> tuple[RunData | None, str | None]:
    """Load one run; the signature (file mtimes and sizes) invalidates the cache on change."""
    try:
        return load_run(RunRef(Path(path).name, Path(path))), None
    except DashboardDataError as exc:
        return None, str(exc)
    except Exception:
        log.exception("unexpected error while loading a run")
        return None, "The run could not be loaded."


@st.cache_data(show_spinner=False, max_entries=6)
def _frames_cached(path: str, sig: tuple, _data: RunData):
    return summary_frame(_data), trials_frame(_data), file_size_frame(_data)


@st.cache_data(show_spinner=False, max_entries=24)
def _artifact_bytes(path: str, name: str, sig: tuple) -> bytes | None:
    p = artifact_path(RunRef(Path(path).name, Path(path)), name)
    return p.read_bytes() if p else None


def _ref() -> RunRef | None:
    return st.session_state.get("run_ref")


def _require_run() -> RunData:
    """Return the selected valid run, or render the right empty/error state and stop."""
    ref = _ref()
    if ref is None:
        st.title("No recorded run found")
        st.info(
            "This explorer displays recorded benchmark runs and has none to show. To add one: "
            "run `sdplab run --config configs/benchmark.toml`, check it with `sdplab check-run --run "
            "results/raw/<run_id>`, then copy it with `sdplab report --run results/raw/<run_id> "
            "--example-dir results/examples`. Nothing is generated or simulated here."
        )
        st.stop()
    data, error = _load_cached(str(ref.path), signature(ref))
    if data is None:
        st.title("This run cannot be displayed")
        st.error(error or "The run could not be loaded.")
        st.stop()
    if not data.is_valid:
        st.title("This run did not pass validation")
        st.error(
            "The recorded files are inconsistent, so no charts or rankings are shown for this run. "
            f"{len(data.problems)} problem(s) found:"
        )
        for problem in data.problems[:20]:
            st.markdown(f"- {problem}")
        if data.summary_csv_matches is False:
            st.markdown(
                "- `summary.csv` does not match the summary recomputed from the raw trials."
            )
        st.stop()
    return data


def _repo_url() -> str:
    return st.session_state.get("repo_url", DEFAULT_REPO_URL)


# ---------------------------------------------------------------- pages


def page_overview() -> None:
    data = _require_run()
    facts = overview_facts(data)
    st.title("Scientific Data Performance Lab")
    st.markdown("##### Reproducible benchmarking of scientific data storage formats.")
    st.write(
        "SDPLab measures what it costs to move the same synthetic, HEP-inspired event dataset between "
        "disk and NumPy arrays in four storage formats: file size, write time, load time, preprocessing "
        "time, throughput and process memory, with a bit-exact correctness check on every result. "
        "This page explores one recorded benchmark run."
    )
    st.caption(DISCLAIMER)

    cols = st.columns(3)
    cols[0].metric("Formats compared", len(facts["formats"]))
    cols[1].metric("Dataset sizes", len(facts["sizes"]), help="Row counts in this run")
    cols[1].caption(" / ".join(f"{n:,}" for n in facts["sizes"]) + " rows")
    cols[2].metric("Measured trials", f"{facts['trials_measured']:,}")
    cols = st.columns(3)
    cols[0].metric("Failed / incorrect trials", f"{facts['failed']} / {facts['incorrect']}")
    cols[1].metric(
        "Generator version",
        ", ".join(str(v) for v in facts["generator_versions"]) or "not recorded",
    )
    cols[2].metric(
        "Rounds (warm-up + measured)", f"{facts['warmup_rounds']} + {facts['measured_rounds']}"
    )

    st.success(
        f"Run `{facts['run_id']}` passed the same consistency checks as `sdplab check-run` "
        f"(status: {facts['status']}; `summary.csv` matches the raw trials). This shows the files are "
        "internally consistent, not that the results are scientifically conclusive."
    )
    st.warning(CAVEAT)

    left, right = st.columns([3, 2])
    with left:
        st.subheader("What is compared")
        st.markdown(
            "\n".join(
                f"- **{variant_label(v)}**: {FORMAT_BLURBS.get(v, '')}" for v in facts["formats"]
            )
        )
        st.markdown(
            "**Operations:** "
            + ", ".join(operation_label(o) for o in OPERATION_LABELS if o in facts["operations"])
            + "."
        )
        st.markdown(
            "**How:** each trial runs in a fresh process after untimed warm-ups, in a seeded shuffled "
            "order; the operation is timed inside the worker, so interpreter start-up is excluded. "
            "See **Methodology** for the exact boundaries."
        )
    with right:
        st.subheader("Start exploring")
        for page in st.session_state.get("pages", []):
            if page.url_path in ("comparison", "results"):
                st.page_link(page, label=page.title)
        st.link_button("Source code on GitHub", _repo_url())

    with st.expander("Run conditions (recorded)"):
        env = data.run.get("environment", {})
        ram = env.get("ram_bytes")
        rows = {
            "CPU": f"{env.get('cpu_model')} ({env.get('cpu_count')} logical cores)",
            "Memory": f"{ram / 2**30:.1f} GiB" if ram else "unavailable",
            "OS": env.get("os"),
            "Python / NumPy": f"{env.get('python')} / {env.get('numpy')}",
            "Data filesystem": env.get("filesystem_type"),
            "CPU governor / power": f"{env.get('cpu_governor')} / {env.get('power_source')}",
            "Load average at start": str(env.get("loadavg_at_start")),
            "Thread settings": data.run["config"]["environment"]["thread_env"],
            "Cache state": "warm (OS page cache not cleared)",
        }
        st.table({"setting": list(rows), "value": [str(v) for v in rows.values()]})
        for w in data.run.get("warnings", []):
            st.warning(w)


def _download(data: RunData, name: str, label: str, mime: str) -> None:
    ref = _ref()
    if ref is None or name not in data.artifacts:
        st.caption(f"{label}: not available for this run.")
        return
    payload = _artifact_bytes(str(ref.path), name, signature(ref))
    if payload is None:
        st.caption(f"{label}: not available for this run.")
        return
    st.download_button(
        label, payload, file_name=f"{data.run_id}_{name}", mime=mime, key=f"dl-{name}"
    )


def page_comparison() -> None:
    data = _require_run()
    ref = _ref()
    assert ref is not None
    summary, trials, file_sizes = _frames_cached(str(ref.path), signature(ref), data)
    st.title("Format comparison")
    st.caption(
        f"Run `{data.run_id}`. Pick an operation and dataset size; the table and findings are scoped to that choice."
    )

    operations = [o for o in OPERATION_LABELS if o in set(summary["operation"])]
    c1, c2 = st.columns(2)
    default_op = operations.index("load") if "load" in operations else 0
    operation = c1.selectbox("Operation", operations, index=default_op, format_func=operation_label)
    sizes = sorted(int(n) for n in set(summary[summary["operation"] == operation]["rows"]))
    size = c2.selectbox(
        "Dataset size (rows)", sizes, index=len(sizes) - 1, format_func=lambda n: f"{n:,}"
    )
    available = [
        v for v in VARIANT_ORDER if v in set(summary[summary["operation"] == operation]["variant"])
    ]
    formats = st.multiselect("Formats", available, default=available, format_func=variant_label)
    log_y = st.toggle(
        "Log scale for time (recommended when formats differ by orders of magnitude)", value=True
    )
    if not formats:
        st.info("Select at least one format.")
        return

    table = comparison_table(summary, data, operation, size, formats)
    for finding in scoped_findings(table, operation, size):
        st.markdown(f"- {finding}")
    st.dataframe(
        table.drop(columns=["variant"]),
        hide_index=True,
        width="stretch",
        column_config={
            "Median (ms)": st.column_config.NumberColumn(
                format="%.4g", help="Median of accepted measured trials"
            ),
            "Q1 (ms)": st.column_config.NumberColumn(format="%.4g"),
            "Q3 (ms)": st.column_config.NumberColumn(format="%.4g"),
            "IQR (ms)": st.column_config.NumberColumn(
                format="%.4g", help="Q3 - Q1, linear quantiles"
            ),
            "File size (MB)": st.column_config.NumberColumn(
                format="%.4g", help="On-disk size, decimal MB"
            ),
            "Logical throughput (MB/s)": st.column_config.NumberColumn(
                format="%.4g", help="rows x 34 B / median time; same numerator for every format"
            ),
            "File throughput (MB/s)": st.column_config.NumberColumn(
                format="%.4g",
                help="on-disk bytes / median time; differs per format; do not compare with logical throughput",
            ),
            "Estimated workload memory (KiB, estimate)": st.column_config.NumberColumn(
                format="%.4g",
                help="VmHWM minus baseline VmRSS: an estimate, not exact workload memory",
            ),
        },
    )
    st.caption(
        "Empty cells mean the measurement does not apply or was not recorded (for example no file for "
        "in-memory preprocessing); they are never filled with zero."
    )

    tab_time, tab_size, tab_tp, tab_mem = st.tabs(["Time", "File size", "Throughput", "Memory"])
    with tab_time:
        chart = charts.time_chart(summary, trials, operation, formats, log_y)
        if chart is None:
            st.info("No accepted measurements for this selection.")
        else:
            st.altair_chart(chart, width="stretch")
            st.caption("Points: median; bars: IQR (Q1-Q3); faint dots: individual measured trials.")
    with tab_size:
        chart = charts.size_chart(file_sizes, [f for f in formats if f != "in_memory"])
        if chart is None:
            st.info("No file sizes for this selection.")
        else:
            st.altair_chart(chart, width="stretch")
    with tab_tp:
        st.caption(
            "Logical-payload throughput and on-disk file throughput answer different questions and are "
            "plotted separately; do not compare one with the other."
        )
        logical = charts.metric_chart(
            summary,
            operation,
            formats,
            "logical_throughput_mb_s",
            "Logical throughput (MB/s, log scale)",
            "Logical-payload throughput (rows x 34 B / median time)",
            log_y=True,
        )
        filetp = charts.metric_chart(
            summary,
            operation,
            formats,
            "file_throughput_mb_s",
            "File throughput (MB/s, log scale)",
            "On-disk file throughput (file bytes / median time)",
            log_y=True,
        )
        if logical is not None:
            st.altair_chart(logical, width="stretch")
        if filetp is not None:
            st.altair_chart(filetp, width="stretch")
        if logical is None and filetp is None:
            st.info("No throughput values for this selection.")
    with tab_mem:
        st.caption(
            "Linux process high-water marks in KiB that include the Python interpreter and libraries. "
            "The estimate is `VmHWM - VmRSS(baseline)`: an estimate, not exact workload memory."
        )
        mem = charts.metric_chart(
            summary,
            operation,
            formats,
            "estimated_workload_rss_kib_median",
            "Estimated workload memory (KiB, estimate)",
            "Estimated workload memory (an estimate)",
        )
        if mem is None:
            st.info("No memory measurements for this selection.")
        else:
            st.altair_chart(mem, width="stretch")
        raw = summary[
            (summary["operation"] == operation)
            & (summary["rows"] == size)
            & summary["variant"].isin(formats)
        ]
        st.dataframe(
            raw[
                [
                    "variant_label",
                    "median_ru_maxrss_kib",
                    "median_vm_hwm_kib",
                    "median_vm_rss_baseline_kib",
                    "n_maxrss_floor_suspect",
                ]
            ].rename(
                columns={
                    "variant_label": "Format",
                    "median_ru_maxrss_kib": "ru_maxrss (KiB)",
                    "median_vm_hwm_kib": "VmHWM (KiB)",
                    "median_vm_rss_baseline_kib": "VmRSS baseline (KiB)",
                    "n_maxrss_floor_suspect": "ru_maxrss floor-suspect trials",
                }
            ),
            hide_index=True,
            width="stretch",
        )


def page_results() -> None:
    data = _require_run()
    ref = _ref()
    assert ref is not None
    summary, trials, _ = _frames_cached(str(ref.path), signature(ref), data)
    st.title("Detailed results")
    st.caption(
        f"Run `{data.run_id}`: the recorded trials behind every chart, plus the run's metadata."
    )

    st.subheader("Trials")
    c = st.columns(5)
    phases = c[0].multiselect("Phase", ["measured", "warmup"], default=["measured"])
    variants = c[1].multiselect(
        "Format",
        [v for v in VARIANT_ORDER if v in set(trials["variant"])],
        format_func=variant_label,
    )
    ops = c[2].multiselect(
        "Operation",
        [o for o in OPERATION_LABELS if o in set(trials["operation"])],
        format_func=operation_label,
    )
    rows_sel = c[3].multiselect(
        "Rows", sorted(int(n) for n in set(trials["rows"])), format_func=lambda n: f"{n:,}"
    )
    status = c[4].multiselect("Status", sorted(set(trials["status"])))
    view = trials
    if phases:
        view = view[view["phase"].isin(phases)]
    if variants:
        view = view[view["variant"].isin(variants)]
    if ops:
        view = view[view["operation"].isin(ops)]
    if rows_sel:
        view = view[view["rows"].isin(rows_sel)]
    if status:
        view = view[view["status"].isin(status)]
    pages = max(1, -(-len(view) // TRIAL_PAGE_SIZE))
    page = (
        st.number_input("Page", min_value=1, max_value=pages, value=1, step=1) if pages > 1 else 1
    )
    start = (int(page) - 1) * TRIAL_PAGE_SIZE
    st.caption(
        f"{len(view):,} trials match; showing {start + 1 if len(view) else 0}-{min(start + TRIAL_PAGE_SIZE, len(view))} (max {TRIAL_PAGE_SIZE} per page)."
    )
    st.dataframe(view.iloc[start : start + TRIAL_PAGE_SIZE], hide_index=True, width="stretch")

    st.subheader("Summary per format, operation and size")
    st.dataframe(
        summary.drop(columns=["variant_label", "operation_label"]),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Run metadata")
    cfg = data.run["config"]
    with st.expander("Configuration"):
        st.json(cfg)
    with st.expander("Datasets (seed, generator version, NumPy version, SHA-256)"):
        rows = [
            {
                "rows": int(n),
                "seed": d["dataset"]["seed"],
                "generator_version": d["dataset"].get("generator_version"),
                "numpy_version": d["dataset"]["numpy_version"],
                "sha256": d["dataset"]["sha256"],
            }
            for n, d in data.run["datasets"].items()
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
    with st.expander("Environment"):
        env = {k: v for k, v in data.run.get("environment", {}).items() if k != "data_dir"}
        st.json(env)

    st.subheader("Downloads")
    d1, d2 = st.columns(2)
    with d1:
        _download(data, "summary.csv", "Summary (CSV)", "text/csv")
        _download(data, "run.json", "Run metadata (JSON)", "application/json")
    with d2:
        _download(data, "trials.jsonl", "Raw trial records (JSON Lines)", "application/x-ndjson")
        _download(data, "report.md", "Generated report (Markdown)", "text/markdown")
    if data.plots:
        with st.expander("Plots generated with the run (PNG)"):
            for p in plot_paths(ref):
                st.image(p.read_bytes(), caption=p.stem.replace("_", " "))


def _docs_root() -> Path:
    return Path(__file__).resolve().parents[3] / "docs"


def page_methodology() -> None:
    st.title("Methodology")
    st.caption("How the recorded numbers were produced, and what they do and do not mean.")
    from sdplab.dataset import EVENT_DTYPE, ROW_BYTES

    st.subheader("Canonical dataset")
    st.table(
        {
            "field": list(EVENT_DTYPE.names),
            "dtype": [EVENT_DTYPE.fields[n][0].str for n in EVENT_DTYPE.names],
            "bytes": [EVENT_DTYPE.fields[n][0].itemsize for n in EVENT_DTYPE.names],
        }
    )
    st.caption(
        f"Packed, little-endian: {ROW_BYTES} bytes per row. Synthetic and HEP-inspired; not real detector data."
    )
    doc = _docs_root() / "benchmark-methodology.md"
    try:
        text = doc.read_text(encoding="utf-8")
    except OSError:
        st.info(
            "The methodology document is not bundled with this deployment; see the repository's docs folder."
        )
        st.link_button(
            "Methodology on GitHub",
            f"{_repo_url().rstrip('/')}/blob/main/docs/benchmark-methodology.md",
        )
        return
    st.markdown(docs_markdown(text, _repo_url()))


def page_about() -> None:
    st.title("About and reproducibility")
    st.write(
        "Scientific data pipelines spend time turning stored bytes into arrays. Text formats are easy "
        "to inspect but must be parsed; binary formats keep dtype and shape but trade portability; "
        "compression trades CPU for space. SDPLab measures those trade-offs on a reproducible synthetic "
        "dataset, checks every result bit for bit, and records enough metadata to interpret the numbers."
    )
    st.warning(CAVEAT)
    st.subheader("Reproduce it locally")
    st.code(
        "git clone " + _repo_url() + ".git\n"
        "cd Scientific_Data_Performance_Lab\n"
        "uv sync --locked\n"
        "uv run pytest\n"
        "uv run sdplab run --config configs/example.toml\n"
        "uv run sdplab check-run --run results/raw/<run_id>\n"
        "uv run sdplab report --run results/raw/<run_id>\n"
        "uv run streamlit run streamlit_app.py",
        language="bash",
    )
    st.write(
        "This web app is a read-only viewer: it shows runs recorded earlier (it cannot run benchmarks, "
        "upload data or execute code). Results depend on the machine, filesystem, cache state, software "
        "versions and workload; a different computer will produce different numbers."
    )
    st.subheader("Links")
    st.link_button("GitHub repository", _repo_url())
    st.markdown(
        f"- [README]({_repo_url()}/blob/main/README.md)\n"
        f"- [Benchmark methodology]({_repo_url()}/blob/main/docs/benchmark-methodology.md)\n"
        f"- [Limitations]({_repo_url()}/blob/main/docs/limitations.md)\n"
        f"- [Architecture]({_repo_url()}/blob/main/docs/architecture.md)"
    )
    st.caption(DISCLAIMER)


# ---------------------------------------------------------------- entry point


def _select_run(runs: list[RunRef]) -> RunRef | None:
    if not runs:
        return None
    if len(runs) == 1:
        st.sidebar.caption("Recorded run")
        st.sidebar.code(runs[0].run_id, language=None)
        return runs[0]
    labels = [r.run_id for r in runs]
    choice = st.sidebar.selectbox("Recorded run", labels, help="Newest first")
    return runs[labels.index(choice)]


def build_pages() -> list[Any]:
    return [
        st.Page(
            page_overview,
            title="Overview",
            icon=":material/home:",
            url_path="overview",
            default=True,
        ),
        st.Page(
            page_comparison,
            title="Format comparison",
            icon=":material/compare_arrows:",
            url_path="comparison",
        ),
        st.Page(
            page_results,
            title="Detailed results",
            icon=":material/table_chart:",
            url_path="results",
        ),
        st.Page(
            page_methodology, title="Methodology", icon=":material/science:", url_path="methodology"
        ),
        st.Page(page_about, title="About", icon=":material/info:", url_path="about"),
    ]


def main(results_root: Path | None = None, repo_url: str | None = None) -> None:
    """Render the dashboard. ``results_root`` defaults to ``$SDPLAB_RESULTS_DIR`` or results/examples."""
    st.set_page_config(
        page_title="SDPLab - Scientific Data Performance Lab",
        page_icon=":material/analytics:",
        layout="wide",
        initial_sidebar_state="auto",
    )
    root = results_root or default_results_root()
    st.session_state["repo_url"] = repo_url or os.environ.get(REPO_ENV) or DEFAULT_REPO_URL
    st.session_state["run_ref"] = _select_run(discover_runs(root))
    pages = build_pages()
    st.session_state["pages"] = pages
    st.sidebar.link_button("Source on GitHub", st.session_state["repo_url"])
    st.sidebar.caption(DISCLAIMER)
    st.navigation(pages).run()


__all__ = ["REPO_ENV", "RESULTS_ENV", "main"]
