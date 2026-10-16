# Technology Stack

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


> **Decision update (2026-10-13):** the user has since resolved the open items raised by this research. Python floor is now **>=3.12** (CI on 3.12 and 3.13; no 3.11 claim, ADR-015); ADR-005 is amended to store raw `ru_maxrss`, worker `VmHWM`/`VmRSS` and the parent's `ru_maxrss` at launch (the parent-floor effect was re-verified, research-notes section 7); `config_schema_version` and `results_schema_version` are separate (ADR-014); `timeout_s`, noise thresholds and `thread_env` are in the initial config (ADR-016); correctness is validated per operation (ADR-017). Where this file says otherwise it is superseded by `docs/architecture/PROPOSAL.md` (revision 3) and `docs/adr/`. Worker input, loop order and `prepare` vs timed `write` remain deferred to Phase 3 planning.


**Project:** Scientific Data Performance Lab (`sdplab`) - reproducible CSV vs NumPy `.npy`/`.npz` I/O benchmark
**Researched:** 2026-10-13
**Overall confidence:** HIGH for versions and tooling configuration; MEDIUM for three flagged items (lockfile fork, Ruff defaults, baseline-memory mechanism)

The stack choices in `docs/architecture/PROPOSAL.md` sections 6 and 13 are the confirmed baseline and are not re-litigated. This file verifies versions and configuration practice and records the real conflicts found. **Four findings change the baseline plan.** They are in "Conflicts and findings" below, and the first is the most important.

---

## Conflicts and findings (read first)

| # | Finding | Severity | Confidence | Action |
|---|---------|----------|------------|--------|
| C1 | **APPROVED 2026-10-13 (ADR-005 amended).** **`ru_maxrss` of a child inherits the parent's peak RSS across exec on this machine.** I ran a probe on this machine (Python 3.13.5, kernel 7.0.0-38). The parent touched 600 MiB and then spawned `python -c`. The child reported `ru_maxrss` = 626312 KiB. With a small parent the child reported 11724 KiB. In the same child, `/proc/self/status` `VmHWM` read 10516 KiB (uninflated). This follows from the kernel folding the old address space's high-water mark into the process's `maxrss` at exec. | HIGH for the memory metric (ADR-005, RQ4) | HIGH (empirical, one machine; the kernel mechanism is from memory) | Keep `ru_maxrss` stored raw as planned, but **also** record `VmHWM` and `VmRSS` from `/proc/self/status` (stdlib file read, Linux-only) in the worker. Record the parent's own `ru_maxrss` at spawn as `parent_maxrss_kib`. Define `rss_baseline_kib` as `VmRSS` after imports. Keep the runner process small (never hold a generated array while spawning). Add a Phase 3 test that reproduces this probe. Without this, `peak - baseline` can silently read 0 for a cheap loader. |
| C2 | **RESOLVED 2026-10-13 (user decision, ADR-015): `requires-python >=3.12`.** NumPy 2.5.4 has `Requires-Python >=3.12`, so the project no longer claims Python 3.11. Primary development and CI version is 3.13; CI also tests 3.12. A throwaway `uv lock` with `requires-python >=3.12` resolved a single NumPy 2.5.4 with no fork (research-notes 7.2). | Resolved | HIGH on the throwaway lock; the real project lock is verified in Phase 1 | Verify `uv.lock` in Phase 1, run a `--resolution lowest-direct` check or raise the declared floors, and **never commit a hard-coded dataset SHA-256 in tests** (RNG stream stability, note N8). Test determinism within one process and across two fresh processes instead. |
| C3 | **`astral-sh/setup-uv` has no floating major tags.** `git ls-remote` shows only full tags (`v10.0.0` ... `v10.3.0`, `v9.0.0`, `v8.x`). The upstream README itself pins `@<sha> # v10.3.0`. So `@v10` will not resolve. `actions/checkout` does have a floating `v7`. | Low (fails fast) | HIGH | Pin both actions by full commit SHA with a version comment (exact SHAs below). |
| C4 | **Ruff's default rule set is now a broad curated list, not the old `E4/E7/E9/F`.** The 0.17 docs list defaults spanning `RUF, B, UP, SIM, PT, I, N, PERF, D, S, TRY, PL*` and others (only selected codes per prefix). This came from a summarised fetch of the docs page, so treat the exact list as unverified. 0.17.0 also changed defaults (DTZ rules removed from defaults, F406 added) and line-length handling of trailing pragma comments. | Low | MEDIUM | Set `lint.select` **explicitly** so CI does not depend on a moving default. Cap Ruff at `<0.18` in the dev group so `uv lock --upgrade` cannot silently change the formatter or rules. |

---

## Recommended Stack

### Core Framework

| Technology | Version (verified) | Purpose | Why | Confidence |
|------------|--------------------|---------|-----|------------|
| CPython | `>=3.12` floor (`requires-python`); dev/CI primary **3.13** (dev machine is 3.13.5); CI also tests 3.12 | Runtime | `tomllib` is stdlib. The floor is 3.12 because the current NumPy (2.5.x) requires it (ADR-015). | HIGH |
| NumPy | `numpy>=2.0` declared; lock resolves **2.5.4** (Py>=3.12, uploaded 2026-10-10) | Structured arrays, `.npy`/`.npz`, `loadtxt`, RNG | Confirmed baseline. 2.5 release notes: structured-array copies now `memcpy` for contiguous dtypes (the packed `EVENT_DTYPE` has no padding, so there is no effect on hashes). `Generator.binomial`/`multinomial` streams changed in 2.5, so **do not use them** in the generator. `loadtxt` and `savez` are not mentioned in the 2.5 notes. Stick to `normal`, `lognormal`, `uniform` and a weighted categorical draw. | HIGH |
| matplotlib | `matplotlib>=3.9` declared (floor is my recommendation; see note); lock resolves **3.11.2** (Py>=3.11, 2026-09-11, depends on `numpy>=1.25`) | Plots | Confirmed baseline. Only `report.py` imports it. Call `matplotlib.use("Agg")` first in `report.py`, because the output is files only. Matplotlib also falls back to Agg on Linux with no display. | HIGH (latest version), MEDIUM (3.9 floor from training knowledge) |
| argparse, tomllib, subprocess, resource, json, hashlib, statistics, platform | stdlib | CLI, config, worker spawn, peak RSS, I/O | Confirmed baseline. See "Stdlib usage rules" below. | HIGH |

Note on floors. The declared floors (`numpy>=2.0`, `matplotlib>=3.9`) are only honest if something tests them. Either run a one-off `uv sync --resolution lowest-direct` check in Phase 5, or raise the floors to the versions CI actually exercises.

### Build and Project Management

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| uv | **0.13.0** (latest; uploaded 2026-10-09; same as the locally installed version) | Env, lock, run | Confirmed baseline. Commit `uv.lock`; the docs say it should be checked in. It is a universal, cross-platform lockfile. | HIGH |
| uv_build | `uv_build>=0.13.0,<0.14` | Build backend | This is what `uv init` writes by default. A `[build-system]` is **required**: without it uv does not install the project into the venv, and `python -m sdplab.worker` (spawned via `sys.executable`) would fail to import `sdplab`. | HIGH |

### Dev tooling

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| pytest | **9.1.1** (Py>=3.10, 2026-06-19) | Tests | Confirmed baseline. 9.x has a native `[tool.pytest]` TOML table (since 9.0) and a `strict` option. | HIGH |
| Ruff | **0.17.0** (2026-10-09), capped `<0.18` | Lint and format (replaces flake8, isort, black) | Confirmed baseline. | HIGH |

### Infrastructure (CI)

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| `astral-sh/setup-uv` | **v10.3.0** = `1c37ad07a6a961277cf70c0d37d6f313000f5884` | Install uv, cache, set `UV_PYTHON` | Official. `enable-cache` defaults to `auto`, which is on for GitHub-hosted runners. The default cache key globs include `**/uv.lock` and `**/pyproject.toml`. The `python-version` input sets `UV_PYTHON`. | HIGH |
| `actions/checkout` | **v7.0.1** = `3d3c42e5aac5ba805825da76410c181273ba90b1` | Checkout | The uv docs example uses the same SHA; `git ls-remote` agrees. | HIGH |
| Runner | `ubuntu-24.04` | CI OS | Explicit version rather than `ubuntu-latest`, so runner changes are not silent. Linux-first project. | MEDIUM (a style choice) |

No `actions/setup-python`, `astral-sh/ruff-action`, tox, nox, or pre-commit is needed. uv installs the Python, and Ruff comes from the locked dev group.

---

## Reference configuration (verified practice, not application code)

### `pyproject.toml`

```toml
[project]
name = "sdplab"                      # must match src/sdplab so uv_build needs no module-name override
version = "0.1.0"
description = "Reproducible benchmark of CSV vs NumPy .npy/.npz loading"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "numpy>=2.0",
  "matplotlib>=3.9",
]

[project.scripts]
sdplab = "sdplab.cli:main"

[dependency-groups]
dev = [
  "pytest>=9.1",
  "ruff>=0.17,<0.18",
]

[build-system]
requires = ["uv_build>=0.13.0,<0.14"]
build-backend = "uv_build"

[tool.uv]
required-version = ">=0.13,<0.14"   # single source of truth; setup-uv reads it when no `version:` is given

[tool.pytest]
minversion = "9.0"
testpaths = ["tests"]
addopts = ["-ra"]
strict = true                        # strict_config + strict_markers + strict_parametrization_ids + strict_xfail
filterwarnings = ["error"]           # relax with a specific ignore if a third-party warning appears
markers = ["e2e: end-to-end smoke test that spawns real worker subprocesses"]

[tool.ruff]
line-length = 100
# target-version is inferred from requires-python (py312); do not set it separately

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "NPY", "PT", "RUF"]

[tool.ruff.format]
# defaults (double quotes, spaces)
```

Why these choices:
- **Layout.** `uv init --package sdplab` generates `src/sdplab/`, `.python-version`, `README.md`, and the `uv_build` backend. Add `src/sdplab/__main__.py` so `python -m sdplab` also works. The worker is `python -m sdplab.worker`.
- **Dependency group.** A single PEP 735 `dev` group is enough. uv includes `dev` by default in `uv sync` and `uv run`. Do not use the legacy `tool.uv.dev-dependencies`, which the docs say will be removed. Split into `test`/`lint` groups only if CI jobs ever need to differ.
- **Lock.** Commit `uv.lock` and `.python-version` (set to `3.13`). Do not commit `.venv`; uv ignores it automatically.
- **Pytest.** No `pythonpath` entry is needed, because `uv sync` installs the package. `strict = true` was added in pytest 9.0. `rootdir` does not affect imports.
- **Ruff rule set.** `NPY` catches legacy `np.random.seed`/`RandomState`, which matters for RNG discipline. `S` (bandit) is deliberately not selected; it would flag the intentional `subprocess` worker spawn (S603).
- **uv version pin.** The uv docs say "It is considered best practice to pin to a specific uv version." With `required-version` in `pyproject.toml`, setup-uv resolves it when no `version:` input is set. The range also stays aligned with the `uv_build` bound.

### `.github/workflows/ci.yml`

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
jobs:
  check:
    runs-on: ubuntu-24.04
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: astral-sh/setup-uv@1c37ad07a6a961277cf70c0d37d6f313000f5884 # v10.3.0
        with:
          python-version: ${{ matrix.python-version }}   # overrides .python-version via UV_PYTHON
          enable-cache: true
      - run: uv sync --locked
      - run: uv run --no-sync ruff check
      - run: uv run --no-sync ruff format --check
      - run: uv run --no-sync pytest
```

- `uv sync --locked` fails if `uv.lock` is stale (documented). Do not use `--frozen`, which skips that check.
- Benchmarks are never run in CI (PROPOSAL section 12). The `e2e` test uses tiny N and asserts structure, not timings.
- The matrix legs are Python 3.12 and 3.13; both resolve the same locked NumPy (see C2).

### Stdlib usage rules

| Area | Practice | Source / basis |
|------|----------|----------------|
| `tomllib` | `tomllib.load(open(path, "rb"))` needs a **binary** file. It is read-only (no writer). Invalid input raises `TOMLDecodeError` (a `ValueError` subclass with `lineno`/`colno`). Hand-roll validation (unknown keys, types, `schema_version`) in `config.py`. No pydantic, tomli, or tomli-w. | docs.python.org tomllib |
| `argparse` | One `main(argv: list[str] \| None = None) -> int`, with `sys.exit(main())` in `__main__`. Use `add_subparsers(dest="command", required=True)` and `set_defaults(func=...)`. Tests call `main([...])` directly. | stdlib convention (MEDIUM; standard practice) |
| `subprocess` | `subprocess.run([sys.executable, "-m", "sdplab.worker", ...], capture_output=True, text=True, timeout=T, check=False)`. List args and no `shell=True`. A timeout kills and reaps the child, then raises `TimeoutExpired`, which you record as `status="failed"`. | docs.python.org subprocess: `sys.executable` is "the recommended way" to relaunch the interpreter |
| `resource` | `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` in the **worker**. Linux units are KiB. The Python docs do not state units; the units claim rests on the man page via research note M2. The module is "Unix, not WASI", so import it only in the worker, never at the top level of shared modules. | docs.python.org resource; man7 getrusage (via research notes); **plus C1** |
| Memory side channel (new, see C1) | In the worker, parse `/proc/self/status` for `VmRSS` (baseline, after imports) and `VmHWM` (uninflated peak). Treat the difference as an estimate, per the confirmed baseline. | Empirical probe on this machine |
| matplotlib | `matplotlib.use("Agg")` at the top of `report.py`, before `pyplot`. Use `savefig` for PNG. | matplotlib backends docs |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Build backend | `uv_build` | hatchling, setuptools | The uv default, with zero config for a flat `src/sdplab` package. |
| Dev deps | `[dependency-groups] dev` | `tool.uv.dev-dependencies`, `requirements-dev.txt` | The legacy field is being removed. A lockfile gives reproducible dev tools. |
| Lint/format | Ruff (locked, `<0.18`) | flake8 + isort + black, `ruff-action` | One locked tool; `ruff-action` adds an unpinned moving part. |
| Pytest config | native `[tool.pytest]` | `[tool.pytest.ini_options]` | Native TOML types are available since pytest 9.0. Only one of the two tables is read (first match wins); never mix. |
| CI Python | setup-uv `python-version` | `actions/setup-python` | uv manages Python itself; one tool. |
| CI action refs | full SHA + version comment | `@v10` | `setup-uv` has no floating tags (C3). |
| Memory baseline | `VmRSS`/`VmHWM` + raw `ru_maxrss` | `ru_maxrss` only | Inflated by parent peak (C1). |

**Not to use (all confirmed baseline except where noted):** pandas, psutil, pyperf, typer, h5py, pyarrow; also pydantic, tomli/tomli-w, pytest-benchmark (timing assertions are forbidden), tox/nox, `pip install -e`, poetry. mypy/pyright and pre-commit are not in the confirmed set; defer them rather than add them.

## Installation

```bash
# one-time: create the project skeleton (Phase 1)
uv init --package sdplab        # src layout + uv_build; then edit pyproject.toml as above
uv add "numpy>=2.0" "matplotlib>=3.9"
uv add --dev "pytest>=9.1" "ruff>=0.17,<0.18"
uv lock                          # commit uv.lock and .python-version

# contributors / CI
uv sync --locked
uv run pytest
uv run ruff check && uv run ruff format --check
uv run sdplab info
```

## Gaps and Phase-time checks

- Run `uv lock` in Phase 1 and confirm a single NumPy resolution under `requires-python >=3.12` (a throwaway lock already did; see research-notes 7.2).
- Reproduce the C1 probe as a pytest in Phase 3, and decide whether the committed README documents `VmHWM` vs raw `ru_maxrss` before any memory plot is made.
- Verify the exact Ruff 0.17 default set and the `select` list above with `ruff check` on the first real code. Ruff is pre-1.0 and has changed defaults in consecutive minors.
- The `matplotlib>=3.9` and `numpy>=2.0` floors are untested (see note).
- Pytest `filterwarnings = ["error"]` may need specific ignores for NumPy or Matplotlib warnings.

## Sources

- PyPI JSON metadata (fetched 2026-10-13): numpy 2.5.4 (`>=3.12`), 2.4.4 and 2.3.5 (`>=3.11`); matplotlib 3.11.2 (`>=3.11`); pytest 9.1.1; ruff 0.17.0; uv 0.13.0. HIGH.
- Git tags (`git ls-remote`): `astral-sh/setup-uv` (v10.3.0 latest, no floating tags), `actions/checkout` (v7.0.1 / `v7`), `astral-sh/ruff` (0.17.0), `astral-sh/uv` (0.13.0), `numpy/numpy` (v2.4.6, v2.5.4). HIGH.
- https://raw.githubusercontent.com/astral-sh/setup-uv/main/README.md - inputs, SHA-pinned usage, cache defaults. HIGH.
- https://docs.astral.sh/uv/guides/integration/github/ - workflow, `uv sync --locked`, matrix, version pinning. HIGH.
- https://docs.astral.sh/uv/concepts/projects/init/ - `uv init` layout, `uv_build` bound. HIGH.
- https://docs.astral.sh/uv/concepts/projects/dependencies/ - PEP 735 groups, default `dev`. HIGH.
- https://docs.astral.sh/uv/concepts/projects/sync/ - `--locked` vs `--frozen`. HIGH.
- https://docs.astral.sh/uv/concepts/projects/layout/ - commit `uv.lock`; universal lockfile. HIGH.
- https://docs.pytest.org/en/stable/reference/customize.html and /reference/reference.html - `[tool.pytest]`, `strict`, `testpaths`. HIGH.
- https://docs.astral.sh/ruff/configuration/, /settings/, /default-rules/ and the 0.17.0 changelog (via fetch summarisation). HIGH for config syntax; MEDIUM for the exact default list.
- https://numpy.org/doc/stable/release/2.5.0-notes.html - Python 3.12+, structured-array `memcpy`, binomial stream change. HIGH.
- https://docs.python.org/3/library/{tomllib,subprocess,resource}.html and https://matplotlib.org/stable/users/explain/figure/backends.html. HIGH.
- Local empirical probe (scratch scripts, not committed): child `ru_maxrss` vs `VmHWM`, Python 3.13.5, kernel 7.0.0-38-generic. HIGH for this machine; not verified on other kernels.
- `docs/research/research-notes.md` items M1-M4, N8 (reused, not re-fetched).
