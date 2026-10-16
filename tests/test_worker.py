import json
import subprocess
import sys

import pytest

from sdplab import worker
from sdplab.dataset import generate

ROWS, SEED = 1500, 11


@pytest.fixture
def prepared(tmp_path):
    out = worker.handle(
        {
            "job": "prepare",
            "rows": ROWS,
            "seed": SEED,
            "data_dir": str(tmp_path / "data"),
            "variants": ["csv", "npy", "npz", "npz_compressed"],
            "pt_cut": 20.0,
            "eta_cut": 2.4,
        }
    )
    assert out["status"] == "ok"
    return tmp_path, {
        "array_sha256": out["array_sha256"],
        "preprocess_digest": out["preprocess_digest"],
    }


def request(tmp_path, expected, operation, variant="npy", **over):
    req = {
        "job": "trial",
        "operation": operation,
        "variant": variant,
        "rows": ROWS,
        "seed": SEED,
        "data_dir": str(tmp_path / "data"),
        "scratch_dir": str(tmp_path / "scratch"),
        "pt_cut": 20.0,
        "eta_cut": 2.4,
        "expected": expected,
    }
    req.update(over)
    return req


def test_prepare_writes_and_validates_every_variant(prepared):
    tmp_path, _ = prepared
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == [
        f"events_{ROWS}_csv.csv",
        f"events_{ROWS}_npy.npy",
        f"events_{ROWS}_npz.npz",
        f"events_{ROWS}_npz_compressed.npz",
    ]


@pytest.mark.parametrize("variant", ["csv", "npy", "npz", "npz_compressed"])
@pytest.mark.parametrize("operation", ["write", "load", "load_preprocess"])
def test_each_operation_is_timed_and_correct(prepared, variant, operation):
    tmp_path, expected = prepared
    out = worker.handle(request(tmp_path, expected, operation, variant))
    assert out["status"] == "ok"
    assert out["correct"] is True
    assert out["timing"]["elapsed_ns"] > 0
    assert out["sizes"]["file_bytes"] > 0
    assert out["sizes"]["logical_bytes"] == ROWS * 34


def test_preprocess_needs_no_variant_or_file(prepared):
    tmp_path, expected = prepared
    out = worker.handle(request(tmp_path, expected, "preprocess", variant="in_memory"))
    assert out["correct"] is True
    assert out["sizes"]["file_bytes"] is None
    assert out["correctness_check"] == "preprocess_digest"


def test_write_goes_to_scratch_and_never_touches_the_canonical_file(prepared):
    tmp_path, expected = prepared
    canonical = tmp_path / "data" / f"events_{ROWS}_npy.npy"
    before = canonical.read_bytes()
    worker.handle(request(tmp_path, expected, "write", "npy"))
    assert canonical.read_bytes() == before
    assert (tmp_path / "scratch" / f"events_{ROWS}_npy.npy").is_file()


def test_wrong_expected_hash_marks_the_trial_incorrect(prepared):
    tmp_path, expected = prepared
    bad = {**expected, "array_sha256": "0" * 64}
    assert worker.handle(request(tmp_path, bad, "load"))["correct"] is False
    assert worker.handle(request(tmp_path, bad, "write"))["correct"] is False
    bad = {**expected, "preprocess_digest": "0" * 64}
    assert worker.handle(request(tmp_path, bad, "preprocess", "in_memory"))["correct"] is False


def test_a_corrupted_canonical_file_is_detected(prepared):
    tmp_path, expected = prepared
    path = tmp_path / "data" / f"events_{ROWS}_npy.npy"
    data = bytearray(path.read_bytes())
    data[-1] ^= 0x01
    path.write_bytes(bytes(data))
    assert worker.handle(request(tmp_path, expected, "load", "npy"))["correct"] is False


def test_memory_counters_are_separate_raw_fields(prepared):
    tmp_path, expected = prepared
    res = worker.handle(request(tmp_path, expected, "load", "csv"))["resources"]
    assert set(res) == {
        "ru_maxrss_kib",
        "vm_hwm_kib",
        "vm_rss_baseline_kib",
        "vm_hwm_baseline_kib",
        "hwm_reset",
    }
    assert res["vm_hwm_kib"] > 0
    assert res["vm_rss_baseline_kib"] > 0


def test_unknown_operation_and_job_raise():
    with pytest.raises(ValueError, match="unknown operation"):
        worker.run_trial({"operation": "sleep"})
    with pytest.raises(ValueError, match="unknown job"):
        worker.handle({"job": "x"})


def _call(stdin: str):
    return subprocess.run(
        [sys.executable, "-I", "-m", "sdplab.worker"],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_protocol_one_json_line_even_for_failures():
    for stdin in ("not json", "{}", json.dumps({"job": "trial", "operation": "load"})):
        proc = _call(stdin)
        assert proc.returncode == 0
        lines = proc.stdout.strip().splitlines()
        assert len(lines) == 1
        out = json.loads(lines[0])
        assert out["status"] == "failed"
        assert out["error"]


def test_protocol_end_to_end_in_a_fresh_process(tmp_path):
    data = tmp_path / "d"
    prep = json.loads(
        _call(
            json.dumps(
                {
                    "job": "prepare",
                    "rows": 300,
                    "seed": 1,
                    "data_dir": str(data),
                    "variants": ["npy"],
                    "pt_cut": 20.0,
                    "eta_cut": 2.4,
                }
            )
        ).stdout
    )
    assert prep["status"] == "ok"
    out = json.loads(
        _call(
            json.dumps(
                request(
                    tmp_path,
                    {
                        "array_sha256": prep["array_sha256"],
                        "preprocess_digest": prep["preprocess_digest"],
                    },
                    "load",
                    "npy",
                    rows=300,
                    seed=1,
                    data_dir=str(data),
                )
            )
        ).stdout
    )
    assert out["status"] == "ok"
    assert out["correct"] is True


def test_stdout_stays_clean_when_the_operation_prints(prepared, capsys):
    tmp_path, expected = prepared
    generate(10, 1)
    worker.handle(request(tmp_path, expected, "load"))
    assert capsys.readouterr().out == ""


def test_imports_are_primed_and_the_priming_file_is_removed(prepared):
    tmp_path, expected = prepared
    out = worker.handle(request(tmp_path, expected, "load", "npz"))
    assert out["primed"] is True
    assert list((tmp_path / "scratch").glob("prime_*")) == []
