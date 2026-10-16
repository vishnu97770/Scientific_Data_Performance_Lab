import gc
import warnings

import numpy as np
import pytest

from sdplab import config
from sdplab.dataset import EVENT_DTYPE, array_sha256, generate
from sdplab.formats import NPZ_MEMBER, VARIANTS, FormatError, variant_filename
from sdplab.validate import assert_arrays_identical

NAMES = list(VARIANTS)


def roundtrip(name, a, tmp_path):
    path = tmp_path / variant_filename(name, a.shape[0])
    VARIANTS[name].write(path, a)
    return VARIANTS[name].load(path), path


def table(**columns):
    n = len(next(iter(columns.values())))
    a = np.zeros(n, dtype=EVENT_DTYPE)
    for key, values in columns.items():
        a[key] = values
    return a


def test_registry_matches_the_configuration_schema():
    assert tuple(VARIANTS) == config.KNOWN_FORMATS


def test_variant_filenames_are_distinct_even_when_extensions_match():
    names = {variant_filename(v, 1000) for v in NAMES}
    assert len(names) == 4
    assert variant_filename("npz_compressed", 1000) == "events_1000_npz_compressed.npz"


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("n", [0, 1, 2, 1000, 10_000, 100_000])
def test_generated_data_roundtrips_bit_exactly(name, n, tmp_path):
    original = generate(n, 12345)
    loaded, _ = roundtrip(name, original, tmp_path)
    assert_arrays_identical(original, loaded)
    assert array_sha256(loaded) == array_sha256(original)


@pytest.mark.slow
@pytest.mark.parametrize("name", NAMES)
def test_one_million_rows_roundtrip_bit_exactly(name, tmp_path):
    original = generate(1_000_000, 12345)
    loaded, _ = roundtrip(name, original, tmp_path)
    assert_arrays_identical(original, loaded)


EDGE_FLOATS = [
    0.0,
    -0.0,
    5e-324,
    -5e-324,
    2.2250738585072014e-308,
    2.225073858507201e-308,
    1.7976931348623157e308,
    -1.7976931348623157e308,
    1.0 / 3.0,
    0.1,
    1.0000000000000002,
    0.9999999999999999,
    123456789.12345678,
    1e22,
    1e23,
    4.9406564584124654e-324,
    float("inf"),
    float("-inf"),
]


@pytest.mark.parametrize("name", NAMES)
def test_edge_values_roundtrip_bit_exactly(name, tmp_path):
    n = len(EDGE_FLOATS)
    ids = [
        0,
        -1,
        2**53 - 1,
        2**53,
        2**53 + 1,
        2**63 - 1,
        -(2**63),
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
    ]
    codes = [-32768, 32767, 0, -1, 1] + [0] * (n - 5)
    a = table(
        event_id=ids, pt=EDGE_FLOATS, eta=EDGE_FLOATS[::-1], phi=EDGE_FLOATS, category_code=codes
    )
    loaded, _ = roundtrip(name, a, tmp_path)
    assert_arrays_identical(a, loaded)


@pytest.mark.parametrize("name", NAMES)
def test_negative_zero_keeps_its_sign(name, tmp_path):
    a = table(
        event_id=[1, 2], pt=[-0.0, 0.0], eta=[0.0, -0.0], phi=[-0.0, -0.0], category_code=[0, 0]
    )
    loaded, _ = roundtrip(name, a, tmp_path)
    assert np.signbit(loaded["pt"]).tolist() == [True, False]
    assert np.signbit(loaded["eta"]).tolist() == [False, True]


def _random_finite_floats(rng, n):
    bits = rng.integers(0, 2**64, size=n, dtype=np.uint64)
    values = bits.view(np.float64)
    return values[np.isfinite(values)]


def test_csv_roundtrips_random_float64_bit_patterns(tmp_path):
    rng = np.random.default_rng(2026)
    values = _random_finite_floats(rng, 60_000)
    n = values.shape[0] // 3
    a = table(
        event_id=np.arange(n),
        pt=values[:n],
        eta=values[n : 2 * n],
        phi=values[2 * n : 3 * n],
        category_code=np.zeros(n),
    )
    loaded, _ = roundtrip("csv", a, tmp_path)
    assert_arrays_identical(a, loaded)


def test_csv_roundtrips_random_subnormals(tmp_path):
    rng = np.random.default_rng(7)
    bits = rng.integers(1, 2**52, size=30_000, dtype=np.uint64)
    sub = bits.view(np.float64)
    n = sub.shape[0] // 3
    a = table(
        event_id=np.arange(n),
        pt=sub[:n],
        eta=-sub[n : 2 * n],
        phi=sub[2 * n : 3 * n],
        category_code=np.zeros(n),
    )
    loaded, _ = roundtrip("csv", a, tmp_path)
    assert_arrays_identical(a, loaded)


def test_csv_layout_is_a_header_plus_one_line_per_row(tmp_path):
    a = generate(5, 1)
    path = tmp_path / "e.csv"
    VARIANTS["csv"].write(path, a)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "event_id,pt,eta,phi,category_code"
    assert len(lines) == 6
    assert all(line.count(",") == 4 for line in lines)
    assert lines[1].startswith("0,")


def test_csv_with_a_wrong_column_count_is_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("event_id,pt,eta,phi,category_code\n1,2.0,3.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"columns|Wrong number"):
        VARIANTS["csv"].load(path)


@pytest.mark.parametrize("name", NAMES)
def test_loaders_return_plain_in_memory_arrays_independent_of_the_file(name, tmp_path):
    original = generate(100, 3)
    loaded, path = roundtrip(name, original, tmp_path)
    path.unlink()  # a memmap or lazy archive member would break once the file is gone
    assert type(loaded) is np.ndarray  # not a memmap
    assert loaded.flags.c_contiguous
    assert loaded.flags.writeable
    assert loaded.dtype == EVENT_DTYPE
    assert loaded.ndim == 1
    assert_arrays_identical(original, loaded)


@pytest.mark.parametrize("name", NAMES)
def test_writers_do_not_modify_their_input(name, tmp_path):
    a = generate(500, 9)
    before = array_sha256(a)
    roundtrip(name, a, tmp_path)
    assert array_sha256(a) == before


@pytest.mark.parametrize("name", ["npy", "npz", "npz_compressed"])
def test_paths_are_used_exactly_as_given(name, tmp_path):
    path = tmp_path / "events.tmp"
    VARIANTS[name].write(path, generate(10, 1))
    assert path.is_file()
    assert not (tmp_path / "events.tmp.npy").exists()
    assert not (tmp_path / "events.tmp.npz").exists()
    assert_arrays_identical(generate(10, 1), VARIANTS[name].load(path))


@pytest.mark.parametrize("name", ["npz", "npz_compressed"])
def test_npz_has_exactly_one_member_named_events(name, tmp_path):
    _, path = roundtrip(name, generate(50, 1), tmp_path)
    with np.load(path, allow_pickle=False) as archive:
        assert archive.files == [NPZ_MEMBER]


def test_npz_loader_rejects_an_archive_with_extra_members(tmp_path):
    path = tmp_path / "extra.npz"
    with open(path, "wb") as fh:
        np.savez(fh, events=generate(5, 1), stray=np.arange(3))
    with pytest.raises(ValueError, match="one member"):
        VARIANTS["npz"].load(path)


def test_compressed_archive_is_smaller_than_the_stored_one(tmp_path):
    a = generate(10_000, 5)
    _, stored = roundtrip("npz", a, tmp_path)
    _, packed = roundtrip("npz_compressed", a, tmp_path)
    assert packed.stat().st_size < stored.stat().st_size


@pytest.mark.parametrize("name", ["npz", "npz_compressed"])
def test_loading_an_archive_leaks_no_open_file(name, tmp_path):
    path = tmp_path / "e.npz"
    VARIANTS[name].write(path, generate(100, 1))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        VARIANTS[name].load(path)
        gc.collect()
    assert [w for w in caught if issubclass(w.category, ResourceWarning)] == []


def test_pickled_object_arrays_are_refused(tmp_path):
    path = tmp_path / "obj.npy"
    with open(path, "wb") as fh:
        np.save(fh, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    with pytest.raises(ValueError, match="pickle"):
        VARIANTS["npy"].load(path)
    npz = tmp_path / "obj.npz"
    with open(npz, "wb") as fh:
        np.savez(fh, events=np.array([{"a": 1}], dtype=object))
    with pytest.raises(ValueError, match="pickle"):
        VARIANTS["npz"].load(npz)


# ---------------------------------------------------------------- malformed and wrong-schema input


def _write(path, data: bytes):
    path.write_bytes(data)
    return path


def test_a_missing_file_raises_file_not_found_for_every_variant(tmp_path):
    for name in NAMES:
        with pytest.raises(FileNotFoundError):
            VARIANTS[name].load(tmp_path / "absent")


@pytest.mark.parametrize("name", ["npy", "npz", "npz_compressed"])
def test_binary_variants_reject_garbage_and_truncated_files(name, tmp_path):
    good = tmp_path / "good"
    VARIANTS[name].write(good, generate(200, 1))
    raw = good.read_bytes()
    for label, data in (
        ("garbage", b"this is not a numpy file" * 10),
        ("truncated", raw[: len(raw) // 2]),
        ("empty", b""),
    ):
        with pytest.raises(FormatError, match=name.split("_")[0]):
            VARIANTS[name].load(_write(tmp_path / f"bad-{label}", data))


@pytest.mark.parametrize("name", ["npy", "npz", "npz_compressed"])
@pytest.mark.parametrize(
    "bad",
    [
        np.arange(10, dtype="<f8"),
        np.zeros((3, 3), dtype=EVENT_DTYPE),
        np.zeros(5, dtype=EVENT_DTYPE.newbyteorder(">")),
        np.zeros(5, dtype=[("event_id", "<i8"), ("pt", "<f8")]),
        np.zeros(
            5,
            dtype=np.dtype(
                [*[(n, EVENT_DTYPE.fields[n][0]) for n in EVENT_DTYPE.names]], align=True
            ),
        ),
    ],
    ids=["plain-float", "two-dimensional", "big-endian", "missing-fields", "aligned-padded"],
)
def test_wrong_schema_arrays_are_rejected_not_repaired(name, bad, tmp_path):
    path = tmp_path / "wrong"
    if name == "npy":
        with open(path, "wb") as fh:
            np.save(fh, bad)
    else:
        with open(path, "wb") as fh:
            (np.savez if name == "npz" else np.savez_compressed)(fh, events=bad)
    with pytest.raises(FormatError, match=r"dtype|1-D"):
        VARIANTS[name].load(path)


def test_an_npy_file_loaded_as_npz_and_vice_versa_is_rejected(tmp_path):
    a = generate(20, 2)
    VARIANTS["npy"].write(tmp_path / "a.npy", a)
    VARIANTS["npz"].write(tmp_path / "a.npz", a)
    with pytest.raises(FormatError, match="not a zip archive"):
        VARIANTS["npz"].load(tmp_path / "a.npy")
    with pytest.raises(FormatError):
        VARIANTS["npy"].load(tmp_path / "a.npz")


def test_npz_with_the_wrong_member_name_is_rejected(tmp_path):
    path = tmp_path / "w.npz"
    with open(path, "wb") as fh:
        np.savez(fh, data=generate(5, 1))
    with pytest.raises(FormatError, match="one member"):
        VARIANTS["npz"].load(path)


CSV_OK_ROW = "1,2.5,0.5,0.25,3"


@pytest.mark.parametrize(
    ("label", "text", "needle"),
    [
        ("wrong-header", "id,pt,eta,phi,cat\n" + CSV_OK_ROW + "\n", "header"),
        ("no-header", CSV_OK_ROW + "\n", "header"),
        ("empty-file", "", "header"),
        ("missing-column", "event_id,pt,eta,phi,category_code\n1,2.5,0.5,0.25\n", "csv file"),
        ("extra-column", "event_id,pt,eta,phi,category_code\n1,2.5,0.5,0.25,3,9\n", "csv file"),
        ("non-numeric", "event_id,pt,eta,phi,category_code\n1,abc,0.5,0.25,3\n", "csv file"),
        (
            "float-in-int-column",
            "event_id,pt,eta,phi,category_code\n1.0,2.5,0.5,0.25,3\n",
            "csv file",
        ),
        ("int16-overflow", "event_id,pt,eta,phi,category_code\n1,2.5,0.5,0.25,40000\n", "csv file"),
        ("blank-cell", "event_id,pt,eta,phi,category_code\n1,,0.5,0.25,3\n", "csv file"),
    ],
)
def test_malformed_csv_is_rejected_never_silently_cast(label, text, needle, tmp_path):
    path = tmp_path / f"{label}.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(FormatError, match=needle):
        VARIANTS["csv"].load(path)


def test_csv_header_only_file_is_a_valid_empty_dataset(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("event_id,pt,eta,phi,category_code\n", encoding="utf-8")
    assert VARIANTS["csv"].load(path).shape == (0,)


def test_csv_with_windows_line_endings_is_accepted(tmp_path):
    path = tmp_path / "crlf.csv"
    path.write_bytes(b"event_id,pt,eta,phi,category_code\r\n1,2.5,0.5,0.25,3\r\n")
    got = VARIANTS["csv"].load(path)
    assert got["event_id"].tolist() == [1]
    assert got["pt"].tolist() == [2.5]


def test_format_error_is_a_value_error_with_the_path_in_the_message(tmp_path):
    path = tmp_path / "x.npy"
    path.write_bytes(b"nope")
    with pytest.raises(ValueError, match=str(path)):
        VARIANTS["npy"].load(path)
