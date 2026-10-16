"""Tracer: config -> generate -> hash -> record -> validate, through the installed package."""

import subprocess
import sys

import pytest

from sdplab import config
from sdplab.dataset import array_sha256, dataset_record, generate
from sdplab.preprocess import preprocess
from sdplab.validate import (
    Mismatch,
    assert_arrays_identical,
    assert_preprocess_identical,
    check_dataset_record,
)


def test_end_to_end_slice():
    cfg = config.loads("config_schema_version = 1\n[dataset]\nseed = 31337\nsizes = [256]\n")
    seed, n = cfg["dataset"]["seed"], cfg["dataset"]["sizes"][0]

    original = generate(n, seed)
    record = dataset_record(seed, original)
    assert record["sha256"] == array_sha256(original)

    regenerated = generate(n, seed)
    check_dataset_record(record, dataset_record(seed, regenerated))
    assert_arrays_identical(original, regenerated)
    assert_preprocess_identical(
        preprocess(original, **_cuts(cfg)), preprocess(regenerated, **_cuts(cfg))
    )

    near_miss = regenerated.copy()
    near_miss["phi"][0] += 1e-15
    with pytest.raises(Mismatch):
        assert_arrays_identical(original, near_miss)
    with pytest.raises(Mismatch):
        check_dataset_record(record, dataset_record(seed, generate(n, seed + 1)))


def _cuts(cfg):
    return {"pt_cut": cfg["workload"]["pt_cut"], "eta_cut": cfg["workload"]["eta_cut"]}


def test_installed_entry_point_runs():
    result = subprocess.run(
        [sys.executable, "-I", "-m", "sdplab", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
