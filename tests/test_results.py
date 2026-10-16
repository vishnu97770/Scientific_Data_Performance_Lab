import json
from pathlib import Path

import pytest

from sdplab.results import (
    RESULTS_SCHEMA_VERSION,
    TRIAL_KEYS,
    ResultsError,
    append_trial,
    capture_environment,
    filesystem_type,
    new_run_id,
    read_run_json,
    read_trials,
    write_run_json,
)


def trial(**over):
    rec = {k: None for k in TRIAL_KEYS}
    rec.update(results_schema_version=RESULTS_SCHEMA_VERSION, run_id="r", variant="npy", round=1)
    rec.update(over)
    return rec


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "trials.jsonl"
    recs = [trial(round=i) for i in range(1, 4)]
    for r in recs:
        append_trial(path, r)
    got, truncated = read_trials(path)
    assert got == recs
    assert truncated is False
    assert len(path.read_text().splitlines()) == 3


def test_each_line_is_independently_parseable_json(tmp_path):
    path = tmp_path / "t.jsonl"
    append_trial(path, trial())
    append_trial(path, trial(round=2))
    for line in path.read_text().splitlines():
        assert json.loads(line)["results_schema_version"] == 1


def test_nan_and_infinity_are_refused(tmp_path):
    with pytest.raises(ValueError, match="Out of range float"):
        append_trial(tmp_path / "t.jsonl", trial(timing={"elapsed_ns": float("nan")}))
    assert not (tmp_path / "t.jsonl").exists() or (tmp_path / "t.jsonl").read_text() == ""


def test_unknown_schema_version_and_missing_keys_are_rejected(tmp_path):
    with pytest.raises(ResultsError, match="unsupported results_schema_version"):
        append_trial(tmp_path / "t.jsonl", trial(results_schema_version=2))
    bad = trial()
    del bad["variant"]
    with pytest.raises(ResultsError, match="missing keys"):
        append_trial(tmp_path / "t.jsonl", bad)


def test_truncated_final_line_is_dropped_and_reported(tmp_path):
    path = tmp_path / "t.jsonl"
    append_trial(path, trial())
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"results_schema_version": 1, "run_i')  # interrupted mid-write
    got, truncated = read_trials(path)
    assert len(got) == 1
    assert truncated is True


def test_corruption_before_the_last_line_raises(tmp_path):
    path = tmp_path / "t.jsonl"
    append_trial(path, trial())
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("garbage\n")
    append_trial(path, trial(round=2))
    with pytest.raises(ResultsError, match="line 2"):
        read_trials(path)


def test_a_complete_but_invalid_last_line_raises(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("garbage\n", encoding="utf-8")
    with pytest.raises(ResultsError):
        read_trials(path)


def test_run_json_roundtrip_and_atomic_replace(tmp_path):
    path = tmp_path / "run.json"
    write_run_json(path, {"run_id": "r", "status": "running"})
    write_run_json(path, {"run_id": "r", "status": "completed", "counts": {"trials": 3}})
    run = read_run_json(path)
    assert run["status"] == "completed"
    assert run["results_schema_version"] == RESULTS_SCHEMA_VERSION
    assert not (tmp_path / "run.json.tmp").exists()


def test_run_json_rejects_bad_status_and_unknown_version(tmp_path):
    with pytest.raises(ResultsError, match="status"):
        write_run_json(tmp_path / "run.json", {"status": "great"})
    (tmp_path / "old.json").write_text(json.dumps({"results_schema_version": 99}), encoding="utf-8")
    with pytest.raises(ResultsError, match="unsupported"):
        read_run_json(tmp_path / "old.json")


def test_run_ids_are_unique_and_sortable():
    a, b = new_run_id(), new_run_id()
    assert a != b
    assert len(a.split("-")[0]) == 16
    assert a.split("-")[0].endswith("Z")


def test_environment_capture_is_complete_and_json_serialisable(tmp_path):
    env = capture_environment(tmp_path / "not" / "yet" / "created", tmp_path)
    json.dumps(env, allow_nan=False)
    for key in (
        "python",
        "numpy",
        "os",
        "cpu_count",
        "filesystem_type",
        "cpu_governor",
        "power_source",
        "thread_env",
        "git",
        "data_dir",
    ):
        assert key in env
    assert set(env["thread_env"]) == {
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    }
    assert env["git"]["commit"] is None  # tmp_path is not a repository: tolerated, not an error


def test_filesystem_type_of_a_missing_directory_uses_its_nearest_parent(tmp_path):
    assert filesystem_type(tmp_path / "a" / "b") == filesystem_type(tmp_path)


GOLDEN = Path(__file__).parent / "golden"


def test_golden_trial_records_from_a_real_run_still_load():
    trials, truncated = read_trials(GOLDEN / "trials_v1.jsonl")
    assert truncated is False
    assert {t["operation"] for t in trials} == {"write", "load", "preprocess", "load_preprocess"}
    for t in trials:
        assert t["results_schema_version"] == 1
        assert set(TRIAL_KEYS) <= set(t)
        assert t["status"] == "ok"
        assert t["correct"] is True
        assert t["timing"]["elapsed_ns"] > 0
        assert t["measurement"]["cache_mode"] == "warm"


def test_golden_run_json_from_a_real_run_still_loads_and_its_config_validates():
    run = read_run_json(GOLDEN / "run_v1.json")
    assert run["results_schema_version"] == 1
    assert run["status"] == "completed"
    assert run["config"]["config_schema_version"] == 1
    from sdplab import config as cfg

    assert cfg.validate(run["config"]) == run["config"]
    assert set(run["datasets"]) == {"10000", "100000", "1000000"}
    assert {"python", "numpy", "cpu_model", "filesystem_type", "git"} <= set(run["environment"])
