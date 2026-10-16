import math
import subprocess
import sys

import numpy as np
import pytest

from sdplab.dataset import (
    EVENT_DTYPE,
    GENERATOR_VERSION,
    ROW_BYTES,
    NotCanonicalError,
    array_sha256,
    assert_canonical,
    dataset_record,
    dtype_description,
    generate,
    identity_sha256,
)


def test_dtype_layout_is_exactly_the_documented_one():
    assert EVENT_DTYPE.names == ("event_id", "pt", "eta", "phi", "category_code")
    assert [EVENT_DTYPE.fields[n][0].str for n in EVENT_DTYPE.names] == [
        "<i8",
        "<f8",
        "<f8",
        "<f8",
        "<i2",
    ]
    assert EVENT_DTYPE.itemsize == ROW_BYTES == 34
    assert not EVENT_DTYPE.isalignedstruct


def test_generated_array_is_canonical_with_documented_bounds():
    a = generate(5000, 99)
    assert_canonical(a)
    assert a.shape == (5000,)
    assert np.array_equal(a["event_id"], np.arange(5000))
    assert bool(np.all(a["pt"] > 0))
    assert bool(np.all(np.abs(a["eta"]) <= 2.5))
    assert bool(np.all(a["phi"] >= -math.pi))
    assert bool(np.all(a["phi"] < math.pi))
    assert set(np.unique(a["category_code"]).tolist()) <= {0, 1, 2, 3, 4}


def test_phi_upper_bound_arithmetic_stays_below_pi():
    # Generator.uniform computes low + (high - low) * u with u < 1; check the largest u.
    largest_u = 1.0 - 2.0**-53
    assert -math.pi + (2 * math.pi) * largest_u < math.pi


def test_same_seed_gives_identical_bytes_in_process():
    assert generate(1000, 7).tobytes() == generate(1000, 7).tobytes()


def test_different_seeds_give_different_data():
    assert array_sha256(generate(1000, 7)) != array_sha256(generate(1000, 8))


@pytest.mark.parametrize("n", [0, 1, 2])
def test_tiny_sizes_are_canonical(n):
    a = generate(n, 3)
    assert_canonical(a)
    assert a.shape == (n,)
    array_sha256(a)


@pytest.mark.parametrize(
    ("n", "seed"), [(-1, 1), (3.0, 1), (True, 1), (10, -1), (10, True), (10, 1.5)]
)
def test_generate_rejects_bad_arguments(n, seed):
    with pytest.raises(ValueError, match="must be a non-negative int"):
        generate(n, seed)


def test_fresh_processes_yield_identical_dataset():
    code = (
        "import sys; from sdplab.dataset import array_sha256, generate; "
        "sys.stdout.write(array_sha256(generate(2000, 4242)))"
    )
    outputs = [
        subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
        ).stdout
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2] == array_sha256(generate(2000, 4242))


def test_hash_is_stable_for_equal_content_and_changes_for_one_ulp(events_small):
    copy = events_small.copy()
    assert array_sha256(copy) == array_sha256(events_small)
    copy["pt"][3] = np.nextafter(copy["pt"][3], np.inf)
    assert array_sha256(copy) != array_sha256(events_small)


def test_identity_hash_distinguishes_packed_aligned_bigendian_renamed_and_reshaped(
    events_small, aligned_copy
):
    packed = identity_sha256(events_small)
    aligned = identity_sha256(aligned_copy(events_small))
    big = identity_sha256(events_small.astype(EVENT_DTYPE.newbyteorder(">")))
    renamed_dtype = np.dtype(
        [("x", "<i8"), *[(n, EVENT_DTYPE.fields[n][0]) for n in EVENT_DTYPE.names[1:]]]
    )
    renamed = identity_sha256(events_small.view(renamed_dtype))
    reshaped = identity_sha256(events_small[:32].reshape(1, 32).copy())
    assert len({packed, aligned, big, renamed, reshaped}) == 5


def test_identity_hash_depends_on_shape_not_only_bytes(events_small):
    two_d = events_small.reshape(8, 8)
    assert two_d.tobytes() == events_small.tobytes()
    assert identity_sha256(two_d) != identity_sha256(events_small)


def test_array_sha256_rejects_non_canonical_arrays(events_small, aligned_copy):
    for bad in (
        aligned_copy(events_small),
        events_small.astype(EVENT_DTYPE.newbyteorder(">")),
        events_small.reshape(8, 8),
        events_small[::2],
        events_small.view(np.recarray),
        events_small.tolist(),
    ):
        with pytest.raises(NotCanonicalError):
            array_sha256(bad)


def test_identity_hash_rejects_strided_views(events_small):
    with pytest.raises(NotCanonicalError):
        identity_sha256(events_small[::2])


def test_dtype_description_is_explicit_and_rejects_plain_dtypes():
    assert '"itemsize":34' in dtype_description(EVENT_DTYPE)
    with pytest.raises(TypeError):
        dtype_description(np.dtype("<f8"))


def test_dataset_record_has_the_documented_fields(events_small):
    rec = dataset_record(4242, events_small)
    assert set(rec) == {"seed", "rows", "generator_version", "numpy_version", "dtype", "sha256"}
    assert rec["generator_version"] == GENERATOR_VERSION
    assert rec["seed"] == 4242
    assert rec["rows"] == 64
    assert rec["numpy_version"] == np.__version__
    assert rec["sha256"] == array_sha256(events_small)
    assert rec["dtype"]["itemsize"] == 34
