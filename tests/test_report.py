import json
from pathlib import Path

import pytest

from sdplab import config
from sdplab.analysis import summarize
from sdplab.report import CAVEATS, build_report
from sdplab.results import RESULTS_SCHEMA_VERSION, TRIAL_KEYS, append_trial, write_run_json


def make_trial(
    run_id, rows, variant, op, round_no, ms, *, phase="measured", status="ok", correct=True
):
    rec = {k: None for k in TRIAL_KEYS}
    elapsed = None if ms is None else int(ms * 1e6)
    rec.update(
        results_schema_version=RESULTS_SCHEMA_VERSION,
        run_id=run_id,
        variant=variant,
        operation=op,
        dataset={"rows": rows, "seed": 1, "dtype": {}, "sha256": "x"},
        round=round_no,
        position=1,
        phase=phase,
        status=status,
        correct=correct if status == "ok" else None,
        correctness_check="fake",
        timing={
            "elapsed_ns": elapsed,
            "process_time_ns": elapsed,
            "subprocess_wall_ns": 90_000_000,
        },
        resources={
            "ru_maxrss_kib": 50000,
            "vm_hwm_kib": 48000,
            "vm_rss_baseline_kib": 30000,
            "vm_hwm_baseline_kib": 30000,
            "hwm_reset": True,
            "parent_ru_maxrss_kib_at_launch": 20000,
        },
        flags={"noisy_load": False, "maxrss_floor_suspect": False, "outlier_vs_median": False},
        sizes={"logical_bytes": rows * 34, "file_bytes": None if op == "preprocess" else rows * 40},
        measurement={"cache_mode": "warm"},
        error=None if status == "ok" else "boom",
    )
    return rec


@pytest.fixture
def run_dir(tmp_path):
    run_id = "20260101T000000Z-test"
    d = tmp_path / "results" / "raw" / run_id
    d.mkdir(parents=True)
    cfg = config.defaults()
    cfg["dataset"]["sizes"] = [1000, 10000]
    write_run_json(
        d / "run.json",
        {
            "run_id": run_id,
            "status": "completed",
            "config": cfg,
            "environment": {"python": "3.13", "numpy": "2.5", "os": "Linux", "git": {}},
            "warnings": [],
            "counts": {"trials": 40, "failed": 1, "incorrect": 0},
            "datasets": {
                str(n): {
                    "file_bytes": {
                        "csv": n * 70,
                        "npy": n * 34,
                        "npz": n * 34,
                        "npz_compressed": n * 26,
                    }
                }
                for n in (1000, 10000)
            },
        },
    )
    for n in (1000, 10000):
        for variant in ("csv", "npy", "npz", "npz_compressed"):
            for op in ("write", "load", "load_preprocess"):
                for r in (1, 2, 3):
                    ms = (n / 1000) * (5 if variant == "csv" else 1) * (1 + r / 10)
                    append_trial(d / "trials.jsonl", make_trial(run_id, n, variant, op, r, ms))
        for r in (1, 2, 3):
            append_trial(
                d / "trials.jsonl", make_trial(run_id, n, "in_memory", "preprocess", r, n / 2000)
            )
    append_trial(
        d / "trials.jsonl", make_trial(run_id, 1000, "csv", "load", 9, None, status="failed")
    )
    return d


def test_report_writes_summary_plots_and_markdown(run_dir):
    out = build_report(run_dir)
    assert out["summary"] == run_dir / "summary.csv"
    assert out["summary"].is_file()
    names = {p.name for p in out["plots"].values()}
    assert {"file_size.png", "time_load.png", "time_write.png", "time_preprocess.png"} <= names
    assert {"throughput_logical.png", "throughput_file.png", "memory_estimate.png"} <= names
    for path in out["plots"].values():
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert out["report"].parent.name == "reports"
    assert out["report"].name == f"{run_dir.name}.md"


def test_markdown_contains_the_caveat_block_and_no_verdict_language(run_dir):
    text = build_report(run_dir)["report"].read_text(encoding="utf-8")
    assert CAVEATS in text
    for needle in ("synthetic", "one machine", "warm", "not affiliated"):
        assert needle in CAVEATS
    lowered = text.replace(CAVEATS, "").lower()  # the caveat itself denies a universal winner
    for banned in ("fastest", "winner", "best format", "outperforms", "wins"):
        assert banned not in lowered
    assert "estimate" in lowered
    assert "logical throughput" in lowered
    assert "![load](../plots/" in text


def test_failures_are_counted_in_the_report_and_the_summary(run_dir):
    out = build_report(run_dir)
    row = next(
        r
        for r in out["rows"]
        if r["variant"] == "csv" and r["operation"] == "load" and r["rows"] == 1000
    )
    assert row["n_failed"] == 1
    assert row["n_total"] == 4
    assert row["n_ok"] == 3


def test_summary_is_regenerable_from_the_raw_files_alone(run_dir):
    first = build_report(run_dir)["summary"].read_bytes()
    trials_before = (run_dir / "trials.jsonl").read_bytes()
    (run_dir / "summary.csv").unlink()
    for png in (run_dir.parent.parent / "plots").rglob("*.png"):
        png.unlink()
    again = build_report(run_dir)
    assert again["summary"].read_bytes() == first
    assert (run_dir / "trials.jsonl").read_bytes() == trials_before  # raw data never rewritten
    rows = summarize(
        [json.loads(line) for line in (run_dir / "trials.jsonl").read_text().splitlines()]
    )
    assert len(rows) == len(again["rows"])


def test_a_truncated_trial_file_is_reported_not_fatal(run_dir):
    with open(run_dir / "trials.jsonl", "a", encoding="utf-8") as fh:
        fh.write('{"results_schema_version": 1, "run_i')
    text = Path(build_report(run_dir)["report"]).read_text(encoding="utf-8")
    assert "truncated line" in text
