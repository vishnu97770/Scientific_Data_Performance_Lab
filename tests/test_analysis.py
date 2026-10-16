import csv

import pytest

from sdplab.analysis import (
    COLUMNS,
    QUANTILE_METHOD,
    flag_outliers,
    median,
    quantile,
    stdev,
    summarize,
    write_summary_csv,
)


def trial(
    elapsed_ms,
    *,
    rows=1000,
    variant="npy",
    op="load",
    phase="measured",
    status="ok",
    correct=True,
    **kw,
):
    elapsed = None if elapsed_ms is None else int(elapsed_ms * 1e6)
    return {
        "dataset": {"rows": rows},
        "variant": variant,
        "operation": op,
        "phase": phase,
        "status": status,
        "correct": correct if status == "ok" else None,
        "timing": {"elapsed_ns": elapsed, "subprocess_wall_ns": (elapsed or 0) + 50_000_000},
        "resources": {
            "ru_maxrss_kib": 40000,
            "vm_hwm_kib": kw.get("hwm", 39000),
            "vm_rss_baseline_kib": kw.get("base", 30000),
        },
        "sizes": {"logical_bytes": rows * 34, "file_bytes": kw.get("file_bytes", 34000)},
        "flags": {"noisy_load": kw.get("noisy", False), "maxrss_floor_suspect": False},
    }


def test_quantile_uses_linear_interpolation():
    xs = [1, 2, 3, 4, 5, 6, 7]
    assert quantile(xs, 0.5) == 4
    assert quantile(xs, 0.25) == 2.5
    assert quantile(xs, 0.75) == 5.5
    assert quantile(xs, 0.75) - quantile(xs, 0.25) == 3.0  # IQR of 1..7 with this method
    assert quantile([5.0], 0.25) == 5.0
    assert quantile([1.0, 3.0], 0.5) == 2.0
    with pytest.raises(ValueError, match="empty"):
        quantile([], 0.5)


def test_median_and_stdev_on_fixed_vectors():
    assert median([3, 1, 2]) == 2
    assert median([4, 1, 2, 3]) == 2.5
    assert median([]) is None
    assert stdev([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.138089935299395)
    assert stdev([1.0]) is None


def test_summary_statistics_of_a_known_sample():
    trials = [trial(float(v)) for v in (1, 2, 3, 4, 5, 6, 7)]
    (row,) = summarize(trials)
    assert row["n_total"] == row["n_ok"] == 7
    assert row["median_ms"] == 4
    assert (row["q1_ms"], row["q3_ms"], row["iqr_ms"]) == (2.5, 5.5, 3.0)
    assert (row["min_ms"], row["max_ms"], row["mean_ms"]) == (1, 7, 4)
    assert row["stdev_ms"] == pytest.approx(2.160246899469287)
    assert row["quantile_method"] == QUANTILE_METHOD == "linear"


def test_warmups_are_excluded_and_failures_are_counted_not_dropped():
    trials = [
        trial(100.0, phase="warmup"),
        trial(2.0),
        trial(4.0),
        trial(None, status="failed"),
        trial(None, status="timeout"),
        trial(9.0, correct=False),
    ]
    (row,) = summarize(trials)
    assert row["n_total"] == 5
    assert row["n_ok"] == 2
    assert row["n_failed"] == 2
    assert row["n_incorrect"] == 1
    assert row["median_ms"] == 3  # the incorrect 9.0 and the warm-up 100.0 are not in it


def test_a_cell_where_every_trial_failed_still_appears_with_empty_statistics():
    (row,) = summarize([trial(None, status="failed"), trial(None, status="failed")])
    assert row["n_total"] == 2
    assert row["n_ok"] == 0
    assert row["n_failed"] == 2
    for key in ("median_ms", "q1_ms", "iqr_ms", "min_ms", "mean_ms", "stdev_ms"):
        assert row[key] is None


def test_throughputs_are_separate_and_use_their_own_numerators():
    (row,) = summarize([trial(10.0, rows=1_000_000, file_bytes=66_000_000)])
    assert row["logical_bytes"] == 34_000_000
    assert row["logical_throughput_mb_s"] == pytest.approx(34.0 / 0.010)
    assert row["file_throughput_mb_s"] == pytest.approx(66.0 / 0.010)
    assert row["logical_throughput_mb_s"] != row["file_throughput_mb_s"]


def test_file_throughput_is_empty_without_a_file():
    t = trial(10.0, op="preprocess", variant="in_memory")
    t["sizes"]["file_bytes"] = None
    (row,) = summarize([t])
    assert row["file_throughput_mb_s"] is None
    assert row["logical_throughput_mb_s"] is not None


def test_memory_raw_medians_and_the_labelled_estimate():
    trials = [trial(1.0, hwm=50000, base=30000), trial(2.0, hwm=70000, base=30000)]
    (row,) = summarize(trials)
    assert row["median_vm_hwm_kib"] == 60000
    assert row["median_vm_rss_baseline_kib"] == 30000
    assert row["estimated_workload_rss_kib_median"] == 30000  # an estimate, by column name


def test_ratio_to_csv_is_a_ratio_of_medians():
    trials = [trial(10.0, variant="csv"), trial(2.0, variant="npy"), trial(5.0, variant="npz")]
    rows = {r["variant"]: r for r in summarize(trials)}
    assert rows["csv"]["median_ratio_vs_csv"] == 1.0
    assert rows["npy"]["median_ratio_vs_csv"] == pytest.approx(0.2)
    assert rows["npz"]["median_ratio_vs_csv"] == pytest.approx(0.5)


def test_outliers_are_flagged_and_counted_but_stay_in_the_statistics():
    trials = [trial(1.0), trial(1.0), trial(1.0), trial(10.0)]
    (row,) = summarize(trials, outlier_factor=3.0)
    assert row["n_outlier_flagged"] == 1
    assert row["n_ok"] == 4
    assert row["max_ms"] == 10.0
    flagged = flag_outliers(trials, 3.0)
    assert [t["timing"]["elapsed_ns"] for t in flagged] == [10_000_000]


def test_noisy_load_trials_are_counted_not_removed():
    (row,) = summarize([trial(1.0, noisy=True), trial(2.0)])
    assert row["n_noisy_load"] == 1
    assert row["n_ok"] == 2


def test_non_operation_time_is_reported_separately():
    (row,) = summarize([trial(10.0)])
    assert row["median_non_operation_ms"] == pytest.approx(50.0)
    assert row["median_subprocess_wall_ms"] == pytest.approx(60.0)


def test_summary_csv_has_the_documented_columns_and_empty_cells_for_none(tmp_path):
    rows = summarize([trial(2.0), trial(None, status="failed", variant="csv")])
    path = tmp_path / "summary.csv"
    write_summary_csv(rows, path)
    with open(path, encoding="utf-8", newline="") as fh:
        read = list(csv.DictReader(fh))
    assert tuple(read[0]) == COLUMNS
    csv_row = next(r for r in read if r["variant"] == "csv")
    assert csv_row["median_ms"] == ""
    assert csv_row["n_failed"] == "1"
    assert path.read_text().count("\r") == 0
