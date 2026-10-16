import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from sdplab import config
from sdplab.results import read_run_json, read_trials
from sdplab.runner import (
    EXIT_GATE,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_PREFLIGHT,
    IN_MEMORY,
    Cell,
    build_schedule,
    cells_for,
    estimate_resources,
    preflight,
    run_benchmark,
    spawn_worker,
)

FAKE = (sys.executable, str(Path(__file__).with_name("fake_worker.py")))


def make_cfg(tmp_path, *, sizes="[1200]", warmup=1, measured=2, formats=None, ops=None, extra=""):
    formats_toml = f"[formats]\nenabled = {json.dumps(formats)}\n" if formats else ""
    ops_toml = f"[workload]\noperations = {json.dumps(ops)}\n" if ops else ""
    return config.loads(
        f"config_schema_version = 1\n[dataset]\nsizes = {sizes}\ndata_dir = '{tmp_path}/data'\n"
        f"{formats_toml}{ops_toml}"
        f"[trials]\nwarmup_rounds = {warmup}\nmeasured_rounds = {measured}\ntimeout_s = 60\n"
        f"[output]\nresults_dir = '{tmp_path}/results'\n{extra}"
    )


def quiet(_msg):
    return None


# ------------------------------------------------------------------ schedule and pre-flight


def test_preprocess_runs_once_per_size_in_memory():
    cfg = config.defaults()
    cfg["dataset"]["sizes"] = [100, 200]
    cells = cells_for(cfg)
    assert len(cells) == 2 * (3 * 4 + 1)
    pre = [c for c in cells if c.operation == "preprocess"]
    assert pre == [Cell(100, IN_MEMORY, "preprocess"), Cell(200, IN_MEMORY, "preprocess")]


def test_schedule_is_a_seeded_permutation_each_round():
    cells = cells_for(config.defaults())
    a = build_schedule(cells, 4, 777)
    assert build_schedule(cells, 4, 777) == a
    assert build_schedule(cells, 4, 778) != a
    for order in a:
        assert sorted(order, key=str) == sorted(cells, key=str)
    assert len({tuple(o) for o in a}) > 1


def test_preflight_accepts_a_small_run_and_names_every_refusal():
    cfg = config.defaults()
    assert preflight(cfg, allow_large=False, mem_available=10**10, disk_free=10**12) == []
    cfg["trials"]["fsync"] = True
    assert "fsync" in preflight(cfg, allow_large=False, mem_available=None, disk_free=None)[0]
    cfg = config.defaults()
    cfg["dataset"]["sizes"] = [10_000_000]
    assert (
        "--allow-large" in preflight(cfg, allow_large=False, mem_available=None, disk_free=None)[0]
    )
    assert preflight(cfg, allow_large=True, mem_available=10**11, disk_free=10**13) == []
    low_ram = preflight(config.defaults(), allow_large=False, mem_available=10**6, disk_free=None)
    assert any("RAM" in p for p in low_ram)
    low_disk = preflight(config.defaults(), allow_large=False, mem_available=None, disk_free=10**6)
    assert any("disk" in p for p in low_disk)


def test_resource_estimates_scale_with_rows():
    assert estimate_resources(2_000_000)["ram_bytes"] > estimate_resources(1_000_000)["ram_bytes"]


def test_preflight_refusal_creates_nothing(tmp_path):
    cfg = make_cfg(tmp_path, extra="")
    cfg["trials"]["fsync"] = True
    out = run_benchmark(cfg, worker_cmd=FAKE, progress=quiet)
    assert out.exit_code == EXIT_PREFLIGHT
    assert "fsync" in out.message
    assert not (tmp_path / "results").exists()


# ------------------------------------------------------------------ a real end-to-end run


def test_real_run_records_every_trial_and_a_consistent_run_json(tmp_path):
    cfg = make_cfg(tmp_path, sizes="[800, 2400]", warmup=1, measured=2)
    out = run_benchmark(cfg, progress=quiet)
    assert out.exit_code == EXIT_OK, out.message
    trials, truncated = read_trials(out.run_dir / "trials.jsonl")
    assert truncated is False
    per_round = len(cells_for(cfg))
    assert len(trials) == 3 * per_round
    assert Counter(t["phase"] for t in trials) == {"warmup": per_round, "measured": 2 * per_round}
    assert all(t["status"] == "ok" and t["correct"] is True for t in trials)
    assert all(t["measurement"]["cache_mode"] == "warm" for t in trials)
    assert all(t["timing"]["subprocess_wall_ns"] > t["timing"]["elapsed_ns"] > 0 for t in trials)
    for t in trials:  # the flag follows its rule whatever the (pytest-sized) parent peak is
        res = t["resources"]
        assert t["flags"]["maxrss_floor_suspect"] is (
            res["ru_maxrss_kib"] <= res["parent_ru_maxrss_kib_at_launch"]
        )
    first_measured = [t for t in trials if t["phase"] == "measured" and t["round"] == 1]
    assert sorted(t["position"] for t in first_measured) == list(range(1, per_round + 1))
    run = read_run_json(out.run_dir / "run.json")
    assert run["status"] == "completed"
    assert run["counts"] == {"trials": len(trials), "failed": 0, "incorrect": 0}
    assert set(run["datasets"]) == {"800", "2400"}
    assert all(
        t["dataset"]["sha256"] == run["datasets"][str(t["dataset"]["rows"])]["dataset"]["sha256"]
        for t in trials
    )
    assert run["environment"]["numpy"]
    assert not (out.run_dir / "scratch").exists()


def test_real_run_cells_cover_every_variant_and_operation(tmp_path):
    out = run_benchmark(make_cfg(tmp_path, warmup=0, measured=1), progress=quiet)
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    pairs = {(t["variant"], t["operation"]) for t in trials}
    expected = {
        (v, o)
        for v in ("csv", "npy", "npz", "npz_compressed")
        for o in ("write", "load", "load_preprocess")
    }
    expected.add((IN_MEMORY, "preprocess"))
    assert pairs == expected


def test_single_thread_environment_is_applied_and_recorded(tmp_path):
    cfg = make_cfg(
        tmp_path,
        warmup=0,
        measured=1,
        formats=["npy"],
        ops=["load"],
        extra="[environment]\nthread_env = 'single'\n",
    )
    out = run_benchmark(cfg, progress=quiet)
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    assert trials[0]["measurement"]["thread_env"]["OMP_NUM_THREADS"] == "1"


def test_the_same_seed_reproduces_the_trial_order(tmp_path):
    runs = []
    for i in range(2):
        cfg = make_cfg(
            tmp_path / str(i), warmup=0, measured=2, formats=["npy", "npz"], ops=["load"]
        )
        out = run_benchmark(cfg, progress=quiet)
        trials, _ = read_trials(out.run_dir / "trials.jsonl")
        runs.append([(t["round"], t["position"], t["variant"], t["operation"]) for t in trials])
    assert runs[0] == runs[1]


# ------------------------------------------------------------------ fault injection


def one_trial_cfg(tmp_path):
    return make_cfg(tmp_path, warmup=0, measured=2, formats=["npy"], ops=["load"])


@pytest.mark.parametrize(
    ("mode", "status", "needle"),
    [
        ("exit1", "failed", "exited with code 1"),
        ("kill", "failed", "code -9"),
        ("garbage", "failed", "not JSON"),
        ("two_lines", "failed", "expected 1"),
        ("no_status", "failed", "no status"),
        ("reported_failure", "failed", "ValueError: nope"),
    ],
)
def test_worker_faults_become_recorded_failed_trials(tmp_path, monkeypatch, mode, status, needle):
    monkeypatch.setenv("FAKE_MODE", mode)
    out = run_benchmark(one_trial_cfg(tmp_path), worker_cmd=FAKE, progress=quiet)
    assert out.exit_code == EXIT_PARTIAL
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    assert len(trials) == 2  # the run continued after the first failure
    assert all(t["status"] == status and needle in t["error"] for t in trials)
    assert all(t["correct"] is None and t["timing"]["elapsed_ns"] is None for t in trials)
    run = read_run_json(out.run_dir / "run.json")
    assert run["status"] == "completed_with_failures"
    assert run["counts"]["failed"] == 2


def test_a_timeout_is_recorded_and_the_child_is_killed(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "sleep")
    cfg = make_cfg(tmp_path, warmup=0, measured=1, formats=["npy"], ops=["load"])
    cfg["trials"]["timeout_s"] = 0.5
    out = run_benchmark(cfg, worker_cmd=FAKE, progress=quiet)
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    assert trials[0]["status"] == "timeout"
    assert "timeout after 0.5" in trials[0]["error"]
    assert out.exit_code == EXIT_PARTIAL


def test_an_incorrect_result_is_kept_flagged_and_counted(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "incorrect")
    out = run_benchmark(one_trial_cfg(tmp_path), worker_cmd=FAKE, progress=quiet)
    assert out.exit_code == EXIT_PARTIAL
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    assert all(t["status"] == "ok" and t["correct"] is False for t in trials)
    assert read_run_json(out.run_dir / "run.json")["counts"]["incorrect"] == 2


def test_the_floor_flag_marks_a_child_that_does_not_exceed_the_parent_peak(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "ok")
    out = run_benchmark(one_trial_cfg(tmp_path), worker_cmd=FAKE, progress=quiet)
    trials, _ = read_trials(out.run_dir / "trials.jsonl")
    for t in trials:
        parent = t["resources"]["parent_ru_maxrss_kib_at_launch"]
        assert t["flags"]["maxrss_floor_suspect"] is (t["resources"]["ru_maxrss_kib"] <= parent)


@pytest.mark.parametrize("mode", ["prepare_mismatch", "prepare_garbage"])
def test_a_failed_validation_gate_aborts_before_any_trial(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("FAKE_MODE", mode)
    out = run_benchmark(one_trial_cfg(tmp_path), worker_cmd=FAKE, progress=quiet)
    assert out.exit_code == EXIT_GATE
    assert "correctness gate failed" in out.message
    assert not (out.run_dir / "trials.jsonl").exists()
    run = read_run_json(out.run_dir / "run.json")
    assert run["status"] == "aborted"
    assert run["gate_failure"]["rows"] == 1200


def test_spawn_worker_reports_a_missing_executable():
    result, wall, error, kind = spawn_worker(["/nonexistent/worker"], {}, 5.0, {})
    assert result is None
    assert kind == "failed"
    assert "cannot start worker" in error
    assert wall >= 0


def test_a_run_on_tmpfs_records_a_warning(tmp_path, monkeypatch):
    from sdplab import runner

    real = runner.capture_environment

    def fake_env(data_dir, project_dir="."):
        return {**real(data_dir, project_dir), "filesystem_type": "tmpfs"}

    monkeypatch.setattr(runner, "capture_environment", fake_env)
    monkeypatch.setenv("FAKE_MODE", "ok")
    messages = []
    out = run_benchmark(
        make_cfg(tmp_path, warmup=0, measured=1, formats=["npy"], ops=["load"]),
        worker_cmd=FAKE,
        progress=messages.append,
    )
    run = read_run_json(out.run_dir / "run.json")
    assert any("tmpfs" in w for w in run["warnings"])
    assert any("warning" in m and "tmpfs" in m for m in messages)
