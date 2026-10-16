# Development

## Setup (Ubuntu, Python 3.12 or newer; 3.13 is the primary version)
```bash
sudo apt install -y git curl
curl -LsSf https://astral.sh/uv/install.sh | sh      # or follow uv's instructions
git clone <YOUR_REPOSITORY_URL> && cd scientific-data-performance-lab
uv sync --locked                                     # project environment in .venv from uv.lock (engine + dev + dashboard)
# engine only: uv sync --locked --no-group dashboard   (dashboard tests then skip)
uv run sdplab --help
```

## Checks
```bash
uv run ruff check && uv run ruff format --check
uv run pytest                    # fast suite (about 30 s: some tests start real worker processes)
uv run pytest -m slow            # adds 10^6-row round trips
```
Tests never assert on timing values and never hard-code a dataset hash. Docs links, anchors and Mermaid fences are tested (`tests/test_docs.py`); the README results block is regenerated from the committed example run and compared (`tests/test_readme_results.py`).

## Python 3.12 / 3.13 parity and dependency floors
```bash
for v in 3.12 3.13; do UV_PROJECT_ENVIRONMENT=/tmp/sdplab-ci-$v UV_PYTHON=$v uv sync --locked && UV_PROJECT_ENVIRONMENT=/tmp/sdplab-ci-$v uv run --no-sync pytest; done
uv run --isolated --no-group dashboard --no-build --resolution lowest-direct --python 3.12 pytest   # declared floors; does not modify uv.lock
```
The declared floors are `numpy>=2.1` and `matplotlib>=3.10.8`. The lock must keep resolving a single NumPy (`tests/test_repo_hygiene.py`).

## Dashboard
```bash
uv run streamlit run streamlit_app.py --server.address 127.0.0.1
```
Restart the server after editing modules under `src/sdplab/` (the editable package is not hot-reloaded). Dashboard tests (`tests/test_dashboard_*.py`) use Streamlit's `AppTest` and skip when Streamlit is not installed. See [deployment.md](deployment.md) and ADR-021.

## CI
`.github/workflows/ci.yml` runs on pushes and pull requests to `main`, and manually (`workflow_dispatch`), on `ubuntu-24.04` with `contents: read` permission only, no secrets and no artifact uploads. Actions are pinned by commit SHA and uv is pinned to 0.13.0 (matching `required-version`). Three jobs:

| Job | Python | What it checks |
|---|---|---|
| `core` | 3.12 and 3.13 | `uv sync --locked --no-group dashboard`, Ruff lint, Ruff format check, the fast pytest suite, `sdplab --help` / `python -m sdplab --version` / `sdplab info`, and `sdplab check-run` on every committed run under `results/examples/` |
| `floors` | 3.12 | the suite against the lowest declared `numpy`/`matplotlib` (`--resolution lowest-direct --no-build`; does not change `uv.lock`) |
| `dashboard` | 3.12 and 3.13 | `uv sync --locked` (adds Streamlit), the dashboard tests, and a start of the real app on 127.0.0.1 with a health-endpoint check |

The engine job installs without Streamlit, so the optional dashboard cannot break it (the dashboard tests skip there by design).

**What CI does not verify:** benchmark performance (benchmarks are never run on shared runners; their timings would not be comparable with the curated example run), the slow 10^6-row tests (`pytest -m slow`), the visual rendering of the dashboard in a browser, Streamlit Community Cloud deployment, or platforms other than Ubuntu.

**Equivalent local checks** (use `UV_PROJECT_ENVIRONMENT=/tmp/sdplab-ci-<v> UV_PYTHON=<v>` to keep a separate environment per Python version):
```bash
uv sync --locked --no-group dashboard
uv run --no-sync ruff check && uv run --no-sync ruff format --check
uv run --no-sync pytest
uv run --no-sync sdplab --help && uv run --no-sync sdplab check-run --run results/examples/<run_id>
uv run --isolated --no-group dashboard --no-build --resolution lowest-direct pytest
uv sync --locked && uv run --no-sync pytest tests/test_dashboard_data.py tests/test_dashboard_app.py
```
**Status:** every step was run locally (see [verification-log.md](verification-log.md)); the workflow has **not** yet run on GitHub, so its status there is unknown. `tests/test_repo_hygiene.py::test_workflow_shape` guards the workflow's structure.

## Adding or changing things
- **A storage variant:** add `write_x`/`load_x` in `formats.py` (the loader must call `_require_schema` and raise `FormatError`), register it in `VARIANTS`, add the name to `config.KNOWN_FORMATS`, and extend the format tests (round trip, edge values, malformed input).
- **Preprocessing or the generator:** bump `GENERATOR_VERSION` if generated values change; update the known-answer tests and the docs.
- **Result fields:** bump `RESULTS_SCHEMA_VERSION`, update `results.TRIAL_KEYS`, the golden files in `tests/golden/`, `analysis.py` and the report.

## Producing the committed example run
```bash
uv run sdplab run --config configs/benchmark.toml     # an otherwise idle machine on AC power
uv run sdplab check-run --run results/raw/<run_id>
uv run sdplab report --run results/raw/<run_id> --example-dir results/examples
```
Then regenerate the README results block from the new example directory; `tests/test_readme_results.py` fails until README and example agree.
