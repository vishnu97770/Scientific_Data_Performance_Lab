import numpy as np
import pytest

from sdplab.dataset import EVENT_DTYPE, dataset_record, generate
from sdplab.preprocess import preprocess
from sdplab.validate import (
    Mismatch,
    assert_arrays_identical,
    assert_preprocess_identical,
    check_dataset_record,
)


def test_identical_copy_is_accepted(events_small):
    assert_arrays_identical(events_small, events_small.copy())


@pytest.mark.parametrize("field", ["pt", "eta", "phi"])
def test_one_ulp_in_each_float_field_is_rejected(events_small, field):
    bad = events_small.copy()
    bad[field][5] = np.nextafter(bad[field][5], np.inf)
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, bad)
    assert exc.value.aspect == "bytes"


def test_integer_field_change_is_rejected(events_small):
    bad = events_small.copy()
    bad["category_code"][0] += 1
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, bad)
    assert exc.value.aspect == "bytes"


def test_negative_zero_is_rejected_where_array_equal_is_blind(events_small):
    a, b = events_small.copy(), events_small.copy()
    a["eta"][0], b["eta"][0] = 0.0, -0.0
    assert np.array_equal(a, b)  # the blind spot that makes array_equal unusable as the gate
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(a, b)
    assert exc.value.aspect == "bytes"


def test_padding_only_difference_is_rejected(events_small, aligned_copy):
    clean, dirty = aligned_copy(events_small, pad=0), aligned_copy(events_small, pad=0xFF)
    assert clean.dtype == dirty.dtype
    assert_arrays_identical(clean, aligned_copy(events_small, pad=0))
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(clean, dirty)
    assert exc.value.aspect == "bytes"


def test_aligned_versus_packed_is_rejected(events_small, aligned_copy):
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, aligned_copy(events_small))
    assert exc.value.aspect == "dtype"


def test_endianness_only_difference_is_rejected(events_small):
    big = events_small.astype(EVENT_DTYPE.newbyteorder(">"))
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, big)
    assert exc.value.aspect == "dtype"


def test_renamed_field_view_is_rejected(events_small):
    renamed = np.dtype(
        [("x", "<i8"), *[(n, EVENT_DTYPE.fields[n][0]) for n in EVENT_DTYPE.names[1:]]]
    )
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, events_small.view(renamed))
    assert exc.value.aspect == "dtype"


def test_shape_and_type_differences_are_rejected(events_small):
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, events_small[:-1])
    assert exc.value.aspect == "shape"
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, events_small.view(np.recarray))
    assert exc.value.aspect == "type"
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small, events_small.tolist())
    assert exc.value.aspect == "type"


def test_non_contiguous_view_is_rejected(events_small):
    with pytest.raises(Mismatch) as exc:
        assert_arrays_identical(events_small[::2], events_small[::2])
    assert exc.value.aspect == "layout"


def test_preprocess_outputs_identical_and_perturbed(events_small):
    expected = preprocess(events_small)
    assert_preprocess_identical(expected, preprocess(events_small.copy()))

    bumped_n = expected._replace(n_selected=expected.n_selected + 1)
    with pytest.raises(Mismatch) as exc:
        assert_preprocess_identical(expected, bumped_n)
    assert exc.value.aspect == "n_selected"

    ulp_sum = expected._replace(sum_pt=float(np.nextafter(expected.sum_pt, np.inf)))
    with pytest.raises(Mismatch) as exc:
        assert_preprocess_identical(expected, ulp_sum)
    assert exc.value.aspect == "sum_pt"

    bad_z = expected.pt_z.copy()
    bad_z[2] = np.nextafter(bad_z[2], np.inf)
    with pytest.raises(Mismatch) as exc:
        assert_preprocess_identical(expected, expected._replace(pt_z=bad_z))
    assert exc.value.aspect == "pt_z"


def test_preprocess_negative_zero_sum_is_rejected():
    expected = preprocess(generate(50, 2))
    with pytest.raises(Mismatch) as exc:
        assert_preprocess_identical(expected._replace(sum_pt=0.0), expected._replace(sum_pt=-0.0))
    assert exc.value.aspect == "sum_pt"


def test_dataset_record_check(events_small):
    rec = dataset_record(4242, events_small)
    check_dataset_record(rec, dataset_record(4242, events_small.copy()))
    other = dataset_record(4242, generate(64, 4243))
    with pytest.raises(Mismatch) as exc:
        check_dataset_record(rec, other)
    assert exc.value.aspect == "dataset"
    assert str(exc.value).startswith("dataset differs")
