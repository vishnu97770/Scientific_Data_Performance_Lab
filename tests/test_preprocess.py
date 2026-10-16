import numpy as np
import pytest

from sdplab.dataset import EVENT_DTYPE, NotCanonicalError, array_sha256, generate
from sdplab.preprocess import preprocess


def _table(pt, eta):
    a = np.zeros(len(pt), dtype=EVENT_DTYPE)
    a["event_id"] = np.arange(len(pt))
    a["pt"] = pt
    a["eta"] = eta
    return a


def test_known_answer_with_exactly_representable_values():
    # mean(pt) = 5 and population std = 2 exactly, so the z-scores are exact.
    a = _table([2, 4, 4, 4, 5, 5, 7, 9], [0, 0, 0, 0, 0, 2.4, 2.39, -1])
    res = preprocess(a, pt_cut=4.0, eta_cut=2.4)
    # pt == 4.0 is excluded (strict >), |eta| == 2.4 is excluded (strict <): rows 4, 6, 7 remain.
    assert res.n_selected == 3
    assert res.sum_pt == 21.0
    assert res.pt_z.tolist() == [-1.5, -0.5, -0.5, -0.5, 0.0, 0.0, 1.0, 2.0]


def test_selection_boundaries_are_strict():
    a = _table([20.0, 20.0000001], [2.4, 2.3999999])
    res = preprocess(a, pt_cut=20.0, eta_cut=2.4)
    assert res.n_selected == 1


def test_repeat_is_bit_identical():
    a = generate(2000, 5)
    r1, r2 = preprocess(a), preprocess(a)
    assert r1.n_selected == r2.n_selected
    assert r1.sum_pt.hex() == r2.sum_pt.hex()
    assert r1.pt_z.tobytes() == r2.pt_z.tobytes()


def test_input_is_not_modified():
    a = generate(500, 5)
    before = array_sha256(a)
    preprocess(a)
    assert array_sha256(a) == before


def test_output_shapes_and_types():
    res = preprocess(generate(300, 1))
    assert isinstance(res.n_selected, int)
    assert isinstance(res.sum_pt, float)
    assert res.pt_z.shape == (300,)
    assert res.pt_z.dtype == np.dtype("<f8")


@pytest.mark.parametrize("n", [0, 1])
def test_degenerate_inputs_raise_value_error(n):
    with pytest.raises(ValueError, match=r"empty|zero standard deviation"):
        preprocess(generate(n, 1))


def test_constant_pt_raises_value_error():
    with pytest.raises(ValueError, match="zero standard deviation"):
        preprocess(_table([3.0, 3.0, 3.0], [0, 0, 0]))


def test_non_canonical_input_is_rejected(events_small):
    with pytest.raises(NotCanonicalError):
        preprocess(events_small.reshape(8, 8))
