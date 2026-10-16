import pytest

from sdplab import config
from sdplab.config import ConfigError

# The block documented in docs/architecture/PROPOSAL.md section 10.
PROPOSAL_BLOCK = """
config_schema_version = 1
[dataset]
seed = 12345
sizes = [10000, 100000, 1000000]
data_dir = "data/generated"
[formats]
enabled = ["csv", "npy", "npz", "npz_compressed"]
[workload]
pt_cut = 20.0
eta_cut = 2.4
operations = ["write", "load", "preprocess", "load_preprocess"]
[trials]
warmup_rounds = 2
measured_rounds = 7
order_seed = 777
fsync = false
timeout_s = 600
[noise]
outlier_factor = 3.0
max_load_per_core = 0.5
[environment]
thread_env = "inherit"
[output]
results_dir = "results"
"""


def test_minimal_config_gets_all_defaults():
    assert config.loads("config_schema_version = 1\n") == config.defaults()


def test_proposal_block_equals_the_defaults():
    assert config.loads(PROPOSAL_BLOCK) == config.defaults()


def test_values_are_overridden_and_integers_accepted_as_floats():
    cfg = config.loads(
        "config_schema_version = 1\n[trials]\ntimeout_s = 30\nmeasured_rounds = 3\n"
        "[workload]\npt_cut = 25\n[dataset]\nsizes = [1000]\n"
    )
    assert cfg["trials"]["timeout_s"] == 30.0
    assert type(cfg["trials"]["timeout_s"]) is float
    assert cfg["trials"]["measured_rounds"] == 3
    assert cfg["workload"]["pt_cut"] == 25.0
    assert cfg["dataset"]["sizes"] == [1000]


def test_defaults_are_independent_copies():
    a, b = config.defaults(), config.defaults()
    a["dataset"]["sizes"].append(1)
    assert b["dataset"]["sizes"] == [10_000, 100_000, 1_000_000]


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("config_schema_version = 1\n[dataset]\nseed = 7\n", encoding="utf-8")
    assert config.load(str(path))["dataset"]["seed"] == 7


REJECTED = [
    # (id, toml text, offending key)
    ("missing-version", "[dataset]\nseed = 1\n", "config_schema_version"),
    ("version-2", "config_schema_version = 2\n", "config_schema_version"),
    ("version-bool", "config_schema_version = true\n", "config_schema_version"),
    ("version-str", 'config_schema_version = "1"\n', "config_schema_version"),
    ("unknown-top-key", "config_schema_version = 1\nsurprise = 1\n", "surprise"),
    ("unknown-section-key", "config_schema_version = 1\n[dataset]\nsedd = 1\n", "dataset.sedd"),
    ("unknown-trials-key", "config_schema_version = 1\n[trials]\nretries = 1\n", "trials.retries"),
    ("unknown-noise-key", "config_schema_version = 1\n[noise]\nx = 1\n", "noise.x"),
    ("section-not-table", "config_schema_version = 1\ndataset = 3\n", "dataset"),
    ("seed-bool", "config_schema_version = 1\n[dataset]\nseed = true\n", "dataset.seed"),
    ("seed-negative", "config_schema_version = 1\n[dataset]\nseed = -1\n", "dataset.seed"),
    ("seed-float", "config_schema_version = 1\n[dataset]\nseed = 1.5\n", "dataset.seed"),
    ("sizes-zero", "config_schema_version = 1\n[dataset]\nsizes = [10, 0]\n", "dataset.sizes[1]"),
    ("sizes-negative", "config_schema_version = 1\n[dataset]\nsizes = [-5]\n", "dataset.sizes[0]"),
    ("sizes-empty", "config_schema_version = 1\n[dataset]\nsizes = []\n", "dataset.sizes"),
    (
        "sizes-duplicate",
        "config_schema_version = 1\n[dataset]\nsizes = [10, 10]\n",
        "dataset.sizes",
    ),
    ("sizes-not-list", "config_schema_version = 1\n[dataset]\nsizes = 10\n", "dataset.sizes"),
    (
        "sizes-str-item",
        'config_schema_version = 1\n[dataset]\nsizes = ["10"]\n',
        "dataset.sizes[0]",
    ),
    ("data-dir-empty", 'config_schema_version = 1\n[dataset]\ndata_dir = ""\n', "dataset.data_dir"),
    ("data-dir-int", "config_schema_version = 1\n[dataset]\ndata_dir = 5\n", "dataset.data_dir"),
    (
        "format-unknown",
        'config_schema_version = 1\n[formats]\nenabled = ["csv", "json"]\n',
        "formats.enabled[1]",
    ),
    (
        "format-duplicate",
        'config_schema_version = 1\n[formats]\nenabled = ["csv", "csv"]\n',
        "formats.enabled",
    ),
    ("format-empty", "config_schema_version = 1\n[formats]\nenabled = []\n", "formats.enabled"),
    (
        "operation-unknown",
        'config_schema_version = 1\n[workload]\noperations = ["load", "sleep"]\n',
        "workload.operations[1]",
    ),
    (
        "pt-cut-negative",
        "config_schema_version = 1\n[workload]\npt_cut = -1.0\n",
        "workload.pt_cut",
    ),
    ("pt-cut-nan", "config_schema_version = 1\n[workload]\npt_cut = nan\n", "workload.pt_cut"),
    ("pt-cut-str", 'config_schema_version = 1\n[workload]\npt_cut = "20"\n', "workload.pt_cut"),
    ("eta-cut-zero", "config_schema_version = 1\n[workload]\neta_cut = 0.0\n", "workload.eta_cut"),
    ("eta-cut-inf", "config_schema_version = 1\n[workload]\neta_cut = inf\n", "workload.eta_cut"),
    (
        "warmup-negative",
        "config_schema_version = 1\n[trials]\nwarmup_rounds = -1\n",
        "trials.warmup_rounds",
    ),
    (
        "measured-zero",
        "config_schema_version = 1\n[trials]\nmeasured_rounds = 0\n",
        "trials.measured_rounds",
    ),
    (
        "order-seed-bool",
        "config_schema_version = 1\n[trials]\norder_seed = false\n",
        "trials.order_seed",
    ),
    ("fsync-int", "config_schema_version = 1\n[trials]\nfsync = 1\n", "trials.fsync"),
    ("timeout-zero", "config_schema_version = 1\n[trials]\ntimeout_s = 0\n", "trials.timeout_s"),
    (
        "timeout-negative",
        "config_schema_version = 1\n[trials]\ntimeout_s = -3.5\n",
        "trials.timeout_s",
    ),
    ("timeout-bool", "config_schema_version = 1\n[trials]\ntimeout_s = true\n", "trials.timeout_s"),
    ("timeout-nan", "config_schema_version = 1\n[trials]\ntimeout_s = nan\n", "trials.timeout_s"),
    (
        "outlier-factor-one",
        "config_schema_version = 1\n[noise]\noutlier_factor = 1.0\n",
        "noise.outlier_factor",
    ),
    (
        "outlier-factor-str",
        'config_schema_version = 1\n[noise]\noutlier_factor = "3"\n',
        "noise.outlier_factor",
    ),
    (
        "load-negative",
        "config_schema_version = 1\n[noise]\nmax_load_per_core = -0.1\n",
        "noise.max_load_per_core",
    ),
    (
        "thread-env-bad",
        'config_schema_version = 1\n[environment]\nthread_env = "auto"\n',
        "environment.thread_env",
    ),
    (
        "thread-env-int",
        "config_schema_version = 1\n[environment]\nthread_env = 1\n",
        "environment.thread_env",
    ),
    (
        "results-dir-date",
        "config_schema_version = 1\n[output]\nresults_dir = 2026-10-14\n",
        "output.results_dir",
    ),
    ("invalid-toml", "config_schema_version = \n", "<toml>"),
]


@pytest.mark.parametrize(
    ("text", "key"), [(t, k) for _, t, k in REJECTED], ids=[i for i, _, _ in REJECTED]
)
def test_invalid_config_is_rejected_naming_the_key(text, key):
    with pytest.raises(ConfigError) as exc:
        config.loads(text)
    assert exc.value.key == key
    assert key in str(exc.value)


def test_missing_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError) as exc:
        config.load(str(tmp_path / "absent.toml"))
    assert exc.value.key == "<file>"


def test_non_utf8_file_is_a_config_error(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_bytes(b"config_schema_version = 1\n# \xff\xfe\n")
    with pytest.raises(ConfigError) as exc:
        config.load(str(path))
    assert exc.value.key == "<toml>"


def test_root_must_be_a_table():
    with pytest.raises(ConfigError) as exc:
        config.validate([1, 2])
    assert exc.value.key == "<root>"


def test_both_shipped_configs_validate():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    example = config.load(str(root / "configs" / "example.toml"))
    benchmark = config.load(str(root / "configs" / "benchmark.toml"))
    assert example["environment"]["thread_env"] == "single"
    assert example["dataset"]["sizes"] == [10000, 100000]
    assert benchmark == config.defaults()  # benchmark.toml spells out the documented defaults
