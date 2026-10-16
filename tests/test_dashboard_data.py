"""Dashboard data layer: run discovery, safe loading, validation and shaping (real example run)."""

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("altair")

from sdplab.analysis import summarize
from sdplab.dashboard import charts, discovery
from sdplab.dashboard.data import (
    DashboardDataError,
    comparison_table,
    docs_markdown,
    file_size_frame,
    fmt_num,
    load_run,
    overview_facts,
    scoped_findings,
    scrub,
    summary_frame,
    trials_frame,
)
from sdplab.results import read_run_json, read_trials

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "results" / "examples"


@pytest.fixture
def example():
    runs = discovery.discover_runs(EXAMPLES)
    assert len(runs) >= 1, "the committed example run is missing"
    return runs[0]


@pytest.fixture
def sandbox(tmp_path, example):
    """A temporary results root with a copy of the real example run that tests may tamper with."""
    dest = tmp_path / "results" / example.run_id
    shutil.copytree(example.path, dest)
    return tmp_path / "results", discovery.RunRef(example.run_id, dest)


# ---------------------------------------------------------------- discovery and path safety


def test_the_committed_example_run_is_discovered(example):
    assert discovery.RUN_ID_RE.match(example.run_id)
    assert (example.path / "run.json").is_file()


def test_discovery_ignores_symlinks_bad_names_and_non_runs(tmp_path, example):
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(example.path, root / example.run_id)
    shutil.copytree(example.path, root / "not-a-run-id")  # wrong name
    (root / "20260101T000000Z-aaaa").mkdir()  # no run.json
    (root / "stray.txt").write_text("x")
    outside = tmp_path / "outside"
    shutil.copytree(example.path, outside / "20260102T000000Z-bbbb")
    (root / "20260102T000000Z-bbbb").symlink_to(
        outside / "20260102T000000Z-bbbb"
    )  # escapes the root
    assert [r.run_id for r in discovery.discover_runs(root)] == [example.run_id]


def test_discovery_of_a_missing_or_file_root_is_empty(tmp_path):
    assert discovery.discover_runs(tmp_path / "absent") == []
    f = tmp_path / "file"
    f.write_text("x")
    assert discovery.discover_runs(f) == []


def test_only_whitelisted_artifacts_resolve(example):
    assert discovery.artifact_path(example, "run.json") is not None
    for bad in ("../run.json", "/etc/passwd", "trials.jsonl/../../x", "secrets.env", "plots", ""):
        assert discovery.artifact_path(example, bad) is None


def test_artifacts_that_are_symlinks_or_oversized_are_refused(sandbox, monkeypatch):
    _, run = sandbox
    target = run.path.parent / "elsewhere.json"
    target.write_text("{}")
    (run.path / "report.md").unlink()
    (run.path / "report.md").symlink_to(target)
    assert discovery.artifact_path(run, "report.md") is None
    monkeypatch.setitem(discovery.ARTIFACT_LIMITS, "summary.csv", 10)
    assert discovery.artifact_path(run, "summary.csv") is None


def test_plots_are_whitelisted_by_name_and_type(sandbox):
    _, run = sandbox
    (run.path / "plots" / "evil.sh").write_text("x")
    (run.path / "plots" / "UPPER.png").write_text("x")
    names = [p.name for p in discovery.plot_paths(run)]
    assert "time_load.png" in names
    assert "evil.sh" not in names
    assert "UPPER.png" not in names


def test_results_root_can_be_set_by_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(discovery.RESULTS_ENV, str(tmp_path))
    assert discovery.default_results_root() == tmp_path.resolve()
    monkeypatch.delenv(discovery.RESULTS_ENV)
    assert discovery.default_results_root().name == "examples"


# ---------------------------------------------------------------- loading and validation


def test_a_valid_run_loads_and_agrees_with_its_raw_records(example):
    data = load_run(example)
    assert data.is_valid
    assert data.problems == ()
    assert data.summary_csv_matches is True
    trials, truncated = read_trials(example.path / "trials.jsonl")
    assert truncated is False
    assert len(data.trials) == len(trials)
    assert list(data.rows) == summarize(trials, data.run["config"]["noise"]["outlier_factor"])


def test_overview_facts_come_from_the_records(example):
    data = load_run(example)
    facts = overview_facts(data)
    trials, _ = read_trials(example.path / "trials.jsonl")
    assert facts["trials_total"] == len(trials)
    assert facts["trials_measured"] == sum(1 for t in trials if t["phase"] == "measured")
    assert facts["failed"] == sum(1 for t in trials if t["status"] != "ok")
    assert facts["formats"] == ["csv", "npy", "npz", "npz_compressed"]
    run = read_run_json(example.path / "run.json")
    assert facts["sizes"] == sorted(int(n) for n in run["datasets"])
    assert facts["run_id"] == run["run_id"]


def test_summary_frame_matches_summary_csv_independently(example):
    import csv

    data = load_run(example)
    frame = summary_frame(data)
    with open(example.path / "summary.csv", encoding="utf-8", newline="") as fh:
        recorded = {(int(r["rows"]), r["variant"], r["operation"]): r for r in csv.DictReader(fh)}
    assert len(frame) == len(recorded)
    for _, row in frame.iterrows():
        rec = recorded[(int(row["rows"]), row["variant"], row["operation"])]
        if rec["median_ms"] == "":
            assert row["median_ms"] != row["median_ms"]  # NaN, never zero
        else:
            assert row["median_ms"] == pytest.approx(float(rec["median_ms"]))


def test_trials_frame_has_one_row_per_trial_in_milliseconds(example):
    data = load_run(example)
    frame = trials_frame(data)
    assert len(frame) == len(data.trials)
    first = data.trials[0]
    assert frame.iloc[0]["elapsed_ms"] == pytest.approx(first["timing"]["elapsed_ns"] / 1e6)


def test_file_sizes_equal_the_recorded_dataset_sizes(example):
    data = load_run(example)
    fs = file_size_frame(data)
    run = read_run_json(example.path / "run.json")
    for _, row in fs.iterrows():
        assert row["file_mb"] * 1e6 == pytest.approx(
            run["datasets"][str(row["rows"])]["file_bytes"][row["variant"]]
        )


def test_a_changed_trial_makes_the_run_invalid_not_silently_valid(sandbox):
    _, run = sandbox
    lines = (run.path / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["dataset"]["sha256"] = "0" * 64
    (run.path / "trials.jsonl").write_text(
        "\n".join([json.dumps(tampered), *lines[1:]]) + "\n", encoding="utf-8"
    )
    data = load_run(run)
    assert not data.is_valid
    assert any("dataset hash differs" in p for p in data.problems)


def test_a_stale_summary_csv_is_detected(sandbox):
    _, run = sandbox
    text = (run.path / "summary.csv").read_text(encoding="utf-8")
    (run.path / "summary.csv").write_text(text.replace("npy", "npx", 1), encoding="utf-8")
    data = load_run(run)
    assert data.summary_csv_matches is False
    assert not data.is_valid


def test_a_missing_trial_and_a_truncated_file_are_reported(sandbox):
    _, run = sandbox
    lines = (run.path / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    (run.path / "trials.jsonl").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    data = load_run(run)
    assert not data.is_valid
    assert any("expected" in p for p in data.problems)
    (run.path / "trials.jsonl").write_text(
        "\n".join(lines) + '\n{"results_schema_version": 1, "run_', encoding="utf-8"
    )
    data = load_run(run)
    assert any("truncated" in p for p in data.problems)


def test_unsupported_schema_versions_are_rejected(sandbox):
    _, run = sandbox
    meta = json.loads((run.path / "run.json").read_text(encoding="utf-8"))
    meta["results_schema_version"] = 99
    (run.path / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(DashboardDataError, match="could not be read"):
        load_run(run)


def test_missing_and_malformed_files_raise_friendly_errors_without_paths(sandbox):
    _, run = sandbox
    (run.path / "run.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(DashboardDataError) as exc:
        load_run(run)
    assert str(run.path) not in str(exc.value)
    assert "/home" not in str(exc.value)
    (run.path / "trials.jsonl").unlink()
    with pytest.raises(DashboardDataError, match=r"missing trials\.jsonl"):
        load_run(run)


def test_oversized_inputs_are_refused_rather_than_loaded(sandbox, monkeypatch):
    _, run = sandbox
    monkeypatch.setitem(discovery.ARTIFACT_LIMITS, "trials.jsonl", 1000)
    with pytest.raises(DashboardDataError, match="too large"):
        load_run(run)


def test_scrub_removes_absolute_paths():
    assert scrub("/home/user/results/run/trials.jsonl: line 3") == "<path>: line 3"
    assert scrub("plain message") == "plain message"
    assert "/tmp/x/y" not in scrub("failed at /tmp/x/y now")


# ---------------------------------------------------------------- tables, findings, charts


def test_comparison_table_carries_recorded_values_and_scoped_findings(example):
    data = load_run(example)
    summary = summary_frame(data)
    fmts = ["csv", "npy", "npz", "npz_compressed"]
    table = comparison_table(summary, data, "load", 1_000_000, fmts)
    assert list(table["variant"]) == fmts
    for _, row in table.iterrows():
        src = summary[
            (summary["operation"] == "load")
            & (summary["rows"] == 1_000_000)
            & (summary["variant"] == row["variant"])
        ].iloc[0]
        assert row["Median (ms)"] == pytest.approx(src["median_ms"])
        assert row["IQR (ms)"] == pytest.approx(src["iqr_ms"])
    findings = scoped_findings(table, "load", 1_000_000)
    assert findings
    assert all("this run" in f for f in findings if "Lowest" in f or "Smallest" in f)
    assert not any("universally" in f.lower() or "best format" in f.lower() for f in findings)
    lowest = table.sort_values("Median (ms)").iloc[0]["Format"]
    assert lowest in findings[0]


def test_findings_say_when_intervals_overlap():
    import pandas as pd

    table = pd.DataFrame(
        {
            "Format": ["A", "B"],
            "Median (ms)": [1.0, 1.1],
            "Q1 (ms)": [0.8, 0.9],
            "Q3 (ms)": [1.2, 1.3],
            "Failed": [0, 0],
            "Incorrect": [0, 0],
            "File size (MB)": [1.0, 2.0],
        }
    )
    assert any("not clearly separated" in f for f in scoped_findings(table, "load", 10_000))


def test_findings_mention_failures_and_never_rank_nothing():
    import pandas as pd

    table = pd.DataFrame(
        {
            "Format": ["A"],
            "Median (ms)": [float("nan")],
            "Q1 (ms)": [float("nan")],
            "Q3 (ms)": [float("nan")],
            "Failed": [3],
            "Incorrect": [0],
            "File size (MB)": [float("nan")],
        }
    )
    findings = scoped_findings(table, "write", 10_000)
    assert findings == [
        "Some trials failed or were incorrect; those cells use only the accepted trials."
    ]


def test_time_chart_plots_recorded_points_with_units_and_leaves_gaps_unfilled(example):
    data = load_run(example)
    summary, trials = summary_frame(data), trials_frame(data)
    chart = charts.time_chart(summary, trials, "load", ["csv", "npy"], True)
    spec = chart.to_dict()
    text = json.dumps(spec)
    assert "Elapsed time (ms, log scale)" in text
    assert "Dataset size (rows, log scale)" in text
    summary.loc[(summary["variant"] == "csv") & (summary["operation"] == "load"), "median_ms"] = (
        float("nan")
    )
    gapped = charts.time_chart(summary, trials, "load", ["csv", "npy"], True).to_dict()
    cell_data = next(v for k, v in gapped["datasets"].items() if any("median_ms" in r for r in v))
    assert all(
        r["variant"] != "csv" for r in cell_data
    )  # missing values are dropped, never zero-filled
    assert charts.time_chart(summary, trials, "load", ["csv"], True) is None


def test_throughput_charts_are_separate_and_labelled(example):
    data = load_run(example)
    s = summary_frame(data)
    logical = json.dumps(
        charts.metric_chart(
            s,
            "load",
            ["csv", "npy"],
            "logical_throughput_mb_s",
            "Logical throughput (MB/s, log scale)",
            "L",
            True,
        ).to_dict()
    )
    file_ = json.dumps(
        charts.metric_chart(
            s,
            "load",
            ["csv", "npy"],
            "file_throughput_mb_s",
            "File throughput (MB/s, log scale)",
            "F",
            True,
        ).to_dict()
    )
    assert "logical_throughput_mb_s" in logical
    assert "file_throughput_mb_s" in file_
    assert "file_throughput_mb_s" not in logical


def test_docs_markdown_rewrites_relative_links_for_github():
    md = (
        "# Title\nSee [notes](research/research-notes.md) and [site](https://example.org) "
        "and [anchor](#x).\n"
    )
    out = docs_markdown(md, "https://github.com/u/r")
    assert "# Title" not in out
    assert "(https://github.com/u/r/blob/main/docs/research/research-notes.md)" in out
    assert "(https://example.org)" in out
    assert "(#x)" in out
    assert "research-notes.md" not in docs_markdown(md, None)


def test_fmt_num():
    assert fmt_num(None) == "-"
    assert fmt_num(float("nan")) == "-"
    assert fmt_num(1234.6) == "1,235"
    assert fmt_num(0.123456) == "0.123"


def test_the_engine_imports_without_streamlit():
    import subprocess
    import sys

    code = (
        "import sys; import sdplab.cli, sdplab.runner, sdplab.worker, sdplab.results; "
        "import sdplab.report, sdplab.dashboard.discovery, sdplab.dashboard.data; "
        "sys.exit(1 if 'streamlit' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-I", "-c", code], check=False).returncode == 0
