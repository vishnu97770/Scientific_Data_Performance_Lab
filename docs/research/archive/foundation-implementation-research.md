# Phase 1: Foundation & Dataset - Research

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


**Researched:** 2026-10-13 to 2026-10-14
**Domain:** Python/uv packaging and CI for a small NumPy library; deterministic structured-array datasets; bit-exact identity hashing; hand-written TOML validation
**Confidence:** HIGH for everything tagged VERIFIED (executed here, versions stated); MEDIUM for CI behaviour that cannot run locally; the open items are in the Assumptions Log.

## Provenance legend (read first)

- `[VERIFIED: <source>]` - confirmed by a tool run in this session. For in-repo discrete values the file was opened with Read/sed this session, the path and line range are cited and the value is quoted verbatim next to the claim. `[VERIFIED: experiment ...]` means I executed it in a scratch directory outside the repo (scripts are NOT in the repo; outputs are reproduced here) with the stated versions. An experiment is evidence for those versions on this machine only, never a cross-version guarantee.
- `[CITED: url]` - read from official documentation this session.
- `[ASSUMED]` - training knowledge or inference, not confirmed. Each one is listed in the Assumptions Log.
- Experiment environment: Linux 7.0.0-38-generic, Intel i5-12450H (AVX2, no AVX512F), uv 0.13.0, CPython 3.12.15 (uv-managed, already installed before this session started) and CPython 3.13.5 (Anaconda interpreter, found by uv), NumPy 2.0.0 / 2.1.0 / 2.5.4, matplotlib 3.9.0 to 3.11.2, pytest 9.1.0 / 9.1.1, ruff 0.17.0.
- Scratch work lives in the session scratchpad (`.../scratchpad/p1full` is a complete throwaway implementation of Phase 1 with 57 tests). It may be deleted; every example below is self-sufficient. Nothing was written inside the repository except this file. No git state was changed.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

### Packaging, tooling and CI (FND-01, FND-02, FND-04)
- **D-01:** One installable package `sdplab`, `src/` layout, ~10 flat modules eventually, no abstract base classes (ADR-001). Phase 1 creates only the modules it needs: `config`, `dataset`, `preprocess`, `validate`, and a minimal `cli` entry point so `uv run sdplab --help` works.
- **D-02:** `requires-python = ">=3.12"`; Python 3.13 is primary (`.python-version`); CI tests Python 3.12 and 3.13; no claim of Python 3.11 support anywhere (ADR-015). `uv` manages the environment; `uv.lock` is committed and `uv sync --locked` must pass. Verify the real project lock resolves one NumPy version, and verify the declared dependency floors (`numpy>=2.0`, `matplotlib>=3.9` are untested) with a lowest-direct resolution check or by raising the floors to versions actually exercised.
- **D-03:** Runtime dependencies are `numpy` and `matplotlib` only; dev group `pytest` and `ruff`; stdlib otherwise (`argparse`, `tomllib`, `hashlib`). No pandas, psutil, pyperf, typer, pydantic (ADR-009, ADR-013). A `[build-system]` is required so `python -m sdplab...` works from the installed venv.
- **D-04:** CI is GitHub Actions on Ubuntu with a Python 3.12 and a 3.13 leg running `uv sync --locked`, `uv run ruff check`, `uv run ruff format --check`, `uv run pytest`. Benchmarks are never run in CI. Third-party actions are pinned by full commit SHA with a version comment; the SHAs recorded in `.planning/research/STACK.md` must be re-verified (e.g. `git ls-remote`) when the workflow is written, not copied blindly.
- **D-05:** FND-04 is verification only: the `.gitignore` is already applied. Verify with `git check-ignore` that `.claude/settings.local.json`, `.venv/`, `data/generated/`, and `results/raw|plots|reports/` are ignored while the GSD install under `.claude/` and `.planning/` stay tracked. Do not weaken or rewrite the existing `.gitignore`; add only what the new files need.

### Configuration (FND-03)
- **D-06:** Config is TOML read with `tomllib`, with its own `config_schema_version = 1`, separate from the future `results_schema_version` (ADR-014). The initial key set is complete and fixed here (unknown keys fail fast): `[dataset]` (seed, sizes, data_dir), `[formats]` (enabled), `[workload]` (pt_cut, eta_cut, operations), `[trials]` (warmup_rounds, measured_rounds, order_seed, fsync, `timeout_s`), `[noise]` (`outlier_factor`, `max_load_per_core`), `[environment]` (`thread_env` = `inherit`|`single`), `[output]` (results_dir). Proposed defaults are in PROPOSAL section 10 (`outlier_factor = 3.0`, `max_load_per_core = 0.5`, `timeout_s = 600`, warmup 2, measured 7).
- **D-07:** Validation checks types, ranges (`timeout_s > 0`, `outlier_factor > 1`, `max_load_per_core >= 0`, sizes > 0, rounds as specified), enum values, unknown keys at every nesting level, and unknown `formats` names, failing fast with a message that names the offending key. It rejects an unknown `config_schema_version`. Validation is hand-written (no pydantic/tomli).

### Dataset and identity (DAT-01, DAT-02, DAT-03)
- **D-08:** `EVENT_DTYPE` is exactly `[("event_id","<i8"), ("pt","<f8"), ("eta","<f8"), ("phi","<f8"), ("category_code","<i2")]`, little-endian, packed (no alignment padding), 34 bytes per row. The canonical in-memory form is a 1-D C-contiguous structured array of this dtype.
- **D-09:** Documented seeded distributions: `event_id` = 0..N-1; `pt` log-normal and strictly positive; `eta` normal clipped to [-2.5, 2.5]; `phi` uniform in [-pi, pi); `category_code` categorical over 4-6 codes with fixed weights. Same seed in the same environment gives a byte-identical array.
- **D-10:** The dataset identity hash is SHA-256 over dtype description + shape + bytes (not bytes alone); a canonical-form check rejects non-1-D, non-contiguous, aligned or non-little-endian arrays. Tests must show the hash distinguishes packed vs aligned dtype and little- vs big-endian data.
- **D-11:** NumPy `Generator` streams have no cross-version guarantee, so **no test hard-codes an expected SHA-256**; determinism is tested within a process and across two fresh processes. The record carrying seed, NumPy version and dataset hash is producible, and a regenerated hash that differs from a recorded one is reported as "dataset differs". (Writing the record into `run.json` is Phase 3 / RES-01.) Avoid `Generator.binomial`/`multinomial` (stream changed in NumPy 2.5).

### Preprocessing and validation (DAT-04, DAT-05)
- **D-12:** One deterministic preprocessing function: `mask = (pt > pt_cut) & (abs(eta) < eta_cut)`; outputs `n_selected`, `sum(pt[mask])`, and the z-scored `pt` column using full-column mean and std; parameters from config (defaults 20.0 and 2.4). Known-answer tests; bit-identical outputs for bit-identical inputs.
- **D-13:** The validator is bit-exact: identical dtype description, shape and bytes/SHA-256 for arrays, and identical preprocess outputs. There is no tolerance (ADR-007). Tests must reject a 1-ULP perturbation, a `-0.0` vs `0.0` change (which `np.array_equal` alone would accept), a padding-only or endianness-only change, and a renamed-field view.

### Honesty and testing constraints (all requirements)
- **D-14:** Tests never assert on timing values and never hard-code dataset hashes. The suite runs in seconds on tiny datasets. Nothing in this phase may claim a benchmark result, and unimplemented features stay marked planned in documentation.

### Claude's Discretion
- Exact module-internal structure, function names and signatures, error-message wording, test file layout and fixtures.
- Exact distribution parameters (log-normal mean/sigma, categorical codes and weights) provided they are documented and satisfy D-09.
- How per-column random streams are derived from the seed (e.g. `SeedSequence`), provided D-11 holds.
- Exact `ruff`/`pytest` configuration (research recommends an explicit `lint.select`, `ruff>=0.17,<0.18`, native `[tool.pytest]` with `strict = true`); `filterwarnings` policy.
- Whether `sdplab info` is added now or left to Phase 4; Phase 1 only requires `uv run sdplab --help`.
- Whether a thin project-skeleton "tracer" (config -> generate -> hash -> validate exercised through the installed entry point) is the first task of the first plan. Note: the Walking-Skeleton template assumes a web app (database, UI, deployment); for this CLI/library project interpret it as the thinnest runnable end-to-end slice of this phase.

### Deferred Ideas (OUT OF SCOPE)
- **Deferred to Phase 3 planning by the user:** how the worker obtains its `write`/`preprocess` input and expected values; scheduling loop order; untimed `prepare` vs timed worker `write`.
- Format writers/loaders and the CSV exactness work - Phase 2.
- Worker, runner, results schema, environment capture, memory counters - Phase 3.
- Analysis, plots, report, the five CLI subcommands, exit codes and `configs/example.toml` - Phase 4.
- README final verification, ADR consistency check, committed example run - Phase 5.
- Optional extensions EXT-01..EXT-06 (fsync, 10^7 rows, pandas loader, column-wise npz, other formats, cold cache) - not planned.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FND-01 | Fresh clone: `uv sync --locked` then `uv run sdplab --help` on 3.12 and 3.13; `requires-python = ">=3.12"`, src layout, committed lock with a single NumPy | Verified end to end in a throwaway project on 3.12.15 and 3.13.5 (sync, entry point, `python -m sdplab`); lock has 18 packages, exactly one `numpy` 2.5.4, no `resolution-markers`; `[build-system]` needed; floors section; `uv init` pitfalls |
| FND-02 | ruff check, ruff format --check, pytest pass locally on 3.13; same three in GitHub Actions on Ubuntu with 3.12 and 3.13 jobs; SHA-pinned actions; no benchmarks | Action SHAs re-verified (git ls-remote + GitHub API + action.yml inputs); full workflow; local CI-parity commands that were run; ruff/pytest config verified incl. strict mode and warnings policy |
| FND-03 | TOML config via `tomllib`, own `config_schema_version`, full key set, validation of types/ranges/enums/unknown keys at every level naming the key | Table-driven validator prototyped; 31 rejection cases pass on 3.12 and 3.13; bool/nan/inf/TOML-date traps; `TOMLDecodeError` has no `lineno` before 3.14 |
| FND-04 | `.gitignore` tracks GSD install, ignores listed paths | `git check-ignore` run read-only on 25 paths (10 ignored as required, 15 not ignored as required); `.gitkeep` files do not exist yet and must be created |
| DAT-01 | `EVENT_DTYPE` 34 B/row; seeded 1-D C-contiguous array; byte-identical for same seed; pt>0, abs(eta)<=2.5, phi in [-pi, pi) | Generator design (per-column `SeedSequence.spawn`), bounds proof for phi, determinism across processes, identical bytes on NumPy 2.0.0/2.1.0/2.5.4 (informational) |
| DAT-02 | Identity hash over dtype description + shape + bytes; distinguishes packed/aligned and LE/BE; no hard-coded SHA | Two-layer design (canonical check + unchecked identity hash) is REQUIRED for the "distinguishes" claim to be testable; mutation experiment proves it; meta-test forbidding 64-hex literals |
| DAT-03 | Record carries seed, NumPy version, dataset hash; `validate` reports "dataset differs" | `dataset_record()` + `check_dataset_record()` prototype |
| DAT-04 | One deterministic preprocess function with known-answer tests and bit-identical outputs | Prototype; exactly representable known-answer vectors; sums differ in the last bits between NumPy 2.1.0 and 2.5.4, so bit-identity is same-environment only |
| DAT-05 | Validator requires identical dtype, shape, bytes/hash, preprocess outputs; rejects 1-ULP, -0.0, padding-only, endianness-only | Prototype rejects all; mutation experiment shows which tests kill a value-only validator |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

Source: `.claude/CLAUDE.md` (read this session). Treated with the same authority as locked decisions.

- Correctness: bit-exact equality (dtype, shape, bytes/SHA-256) for every loaded array; no tolerance without a documented ADR.
- Honesty: no benchmark numbers or "implemented/verified" claims until produced and verified; unimplemented features marked planned.
- Tech stack: Python >= 3.12 (3.13 primary; CI on 3.12 and 3.13), uv, numpy, matplotlib; pytest + Ruff; stdlib `argparse`, `tomllib`; no pandas/psutil/pyperf/typer in MVP. (CLAUDE.md and `.planning/PROJECT.md:55` currently say `numpy >= 2.0`; see Open Question 1 if the floor is raised.)
- Scope: one developer, flat package `sdplab`, ~10 modules, no abstract base classes, relative effort only.
- Git: `.planning/` stays version-controllable (not ignored); **no commits, pushes, resets or branch changes without explicit user authorization**; `commit_docs` is false. The user commits everything, including `uv.lock` and the CI workflow.
- Platform: Linux-first.
- GSD workflow: repo edits go through a GSD command (`/gsd-execute-phase` for planned phase work). This research did not edit the repo except this file.

## Summary

Phase 1 is a greenfield build with no technical unknowns left that block planning; the work is mostly about choosing designs that make the exactness claims *testable* rather than vacuous. I built a complete throwaway implementation of every Phase 1 module in a scratch directory and ran it: lint, format-check and 57 tests pass in about 0.3 s on Python 3.12.15 and 3.13.5 with the locked NumPy 2.5.4; an earlier 56-test revision also passed at the declared lowest-direct floors on 3.12 (NumPy 2.0.0, matplotlib 3.9.0, pytest 9.1.0), and the 57-test revision (with a headless matplotlib import) passed at the recommended raised floors on both Pythons (NumPy 2.1.0, matplotlib 3.10.8). The reference `pyproject.toml` from STACK.md works as written except that floors, `uv init` defaults and a few lint/warning interactions need the adjustments below.

Seven findings change what the planner should write. (1) The declared floors `numpy>=2.0` and `matplotlib>=3.9` cannot be exercised on Python 3.13: NumPy 2.0.0 and matplotlib 3.9.0/3.9.1 have no cp313 wheels; and with `filterwarnings = ["error"]`, `import matplotlib.pyplot` fails for every matplotlib I tried up to 3.10.0 because of a `PyparsingDeprecationWarning` from the (unpinned, transitive) pyparsing 3.3.3. Recommended floors, verified at lowest-direct on both Pythons: `numpy>=2.1`, `matplotlib>=3.10.8`. (2) If `array_sha256()` runs the canonical check first, it can never hash an aligned, big-endian or renamed array, so "the hash distinguishes packed vs aligned" is untestable; split into a checked `array_sha256` and an unchecked `identity_sha256`, and a mutation experiment shows the split is what kills "hash omits dtype / shape" faults. (3) `np.array_equal` has more blind spots than `-0.0` (aligned vs packed, endianness, padding junk all compare equal; a renamed view raises `TypeError`; `equal_nan=True` returns `True` only via an identity shortcut), and `dtype.descr` itself raises for out-of-order fields, so build the canonical dtype text from names/formats/offsets/itemsize. (4) `preprocess` outputs are bit-identical only within one environment: the same 100,000-row input gave `sum_pt` 1945990.4884465795 on NumPy 2.0.0 and 2.1.0 but 1945990.4884465793 on 2.5.4, while the dataset bytes were identical on all three. (5) Use `uv run --isolated --no-build --resolution lowest-direct ...` for the floor check; `uv sync --resolution lowest-direct` (as suggested in STACK.md) rewrites `uv.lock`. (6) The ruff selection `PT`/`RUF` flags composite asserts (PT018) and non-ASCII math characters such as U+2212 and the multiplication sign in docstrings (RUF002). (7) `tomllib.TOMLDecodeError` has no `lineno`/`colno` before Python 3.14, so STACK.md's claim does not hold for the 3.12 floor.

**Primary recommendation:** Build the phase as five small plans around a tracer test first (config -> generate -> hash -> validate through the installed package), use the verified prototype designs in "Code Examples", raise the floors to `numpy>=2.1` / `matplotlib>=3.10.8` (or keep them and accept an untestable floor; user decision), and make a lowest-direct run a CI step so the floors cannot rot.

## Architectural Responsibility Map

This project has no browser/server tiers; the relevant ownership boundaries are modules and repo tooling.

| Capability | Primary owner | Secondary | Rationale |
|------------|---------------|-----------|-----------|
| TOML parse + schema validation + defaults | `config.py` | - | Only module that reads TOML (PROPOSAL section 6 rule: "only `config` reads TOML"); imports nothing from the package |
| `EVENT_DTYPE`, canonical-form check, identity hash, generator, dataset record | `dataset.py` | - | "`dataset` imports nothing from the package" (PROPOSAL section 6); every later module imports it |
| Preprocess function | `preprocess.py` | `dataset.assert_canonical` | NumPy-only leaf (ARCHITECTURE.md line 98: leaves with no package dependencies are `dataset`, `config`, `results`, `preprocess`); calling `assert_canonical` makes it depend on `dataset` (acceptable: worker already imports both) |
| Bit-exact comparison + "dataset differs" report | `validate.py` | `dataset` | Rule: `formats, validate -> dataset`. Do NOT import `preprocess` into `validate`; compare plain values (see Pattern 4) |
| `--help` entry point | `cli.py` / `__main__.py` | - | Nothing imports `cli`; `__init__.py` stays empty (M8: matplotlib must never be pulled into workers) |
| Lock, env, build backend | `pyproject.toml`, `uv.lock`, `.python-version` | uv 0.13.x | `[build-system]` is required for the installed-package imports |
| Lint/format/test gate | CI workflow + local commands | - | Same four commands on both legs; no benchmark ever |
| Ignore rules | `.gitignore` (already applied) | `.gitkeep` files (to create) | FND-04 is verification plus creating the missing `.gitkeep` files |

## Standard Stack

### Core

| Library | Version (verified) | Purpose | Why Standard |
|---------|--------------------|---------|--------------|
| CPython | `>=3.12`; tested 3.12.15 and 3.13.5 | Runtime | D-02/ADR-015. `.python-version` = `3.13` |
| numpy | **2.5.4** locked [VERIFIED: PyPI JSON, requires_python `>=3.12`, uploaded 2026-10-10]; recommended floor `>=2.1` | Structured arrays, `Generator`, `SeedSequence` | D-03 |
| matplotlib | **3.11.2** locked [VERIFIED: PyPI JSON, 2026-09-11]; recommended floor `>=3.10.8`; not imported in Phase 1 | Declared now (D-03), first used in Phase 4 | D-03 |
| uv | 0.13.0 [VERIFIED: `uv --version`; PyPI uv_build 0.13.0 uploaded 2026-10-09] | Env, lock, run | D-02 |
| uv_build | `>=0.13.0,<0.14` | Build backend (what `uv init` writes) | Verified: wheel contains `sdplab/*.py` only; sdist adds `pyproject.toml`, `README.md`, `src/` |

### Supporting (dev group)

| Library | Version (verified) | Purpose | When to Use |
|---------|--------------------|---------|-------------|
| pytest | 9.1.1 locked; floor `>=9.1` (lowest-direct resolved 9.1.0 and the suite passes) | Tests; native `[tool.pytest]` with `strict = true` | Always |
| ruff | 0.17.0 locked; `>=0.17,<0.18` | Lint + format | Always |

Stdlib only for everything else: `argparse`, `tomllib`, `hashlib`, `json`, `math`, `struct`, `subprocess` (tests only), `importlib.metadata`.

### Alternatives Considered (floors)

| Option | Result observed | Verdict |
|--------|-----------------|---------|
| Keep `numpy>=2.0`, `matplotlib>=3.9`, test with lowest-direct | Resolves numpy 2.0.0, matplotlib 3.9.0, pytest 9.1.0. Python 3.12: installs, 56 tests pass. Python 3.13: `error: Distribution matplotlib==3.9.0 ... can't be installed because it is marked as --no-build but has no binary distribution`; `Because numpy==2.0.0 has no usable wheels ...` | Floor is only testable on 3.12; 3.13 would need a source build |
| Raise to `numpy>=2.1`, `matplotlib>=3.9.2` | cp313 wheels exist for both. 56 pass, but `import matplotlib.pyplot` under `filterwarnings=error` fails (`PyparsingDeprecationWarning`) | Works only if matplotlib is never imported in tests, or a scoped ignore is added |
| **Raise to `numpy>=2.1`, `matplotlib>=3.10.8`** | Lowest-direct: numpy 2.1.0, matplotlib 3.10.8, pytest 9.1.0, pyparsing 3.3.3. **57 passed (incl. headless matplotlib import) on 3.12.15 and on 3.13.5**, `uv.lock` untouched | **Recommended** |
| Keep declared floors and add a scoped `filterwarnings` ignore | Not tried; hides a deprecation, and Python 3.13 still cannot install the floors from wheels | Not recommended |

matplotlib behaviour under `python -W error -c "import matplotlib.pyplot"` with pyparsing 3.3.3 on 3.12 [VERIFIED: experiment]: 3.9.0, 3.9.2, 3.9.4, 3.10.0 fail (`PyparsingDeprecationWarning: 'oneOf' deprecated - use 'one_of'`); 3.10.8 and 3.11.0 pass. 3.10.1 to 3.10.7 were not tested; 3.10.8 is the lowest version proven, so it is the floor.

NumPy wheel facts [CITED: pypi.org/pypi/numpy/2.0.0/json etc.; falsification run below]: numpy 2.0.0 wheel tags cp310-cp312; 2.1.0 adds cp313. matplotlib 3.9.0 and 3.9.1 cp310-cp312; 3.9.2 adds cp313. Falsification [VERIFIED: experiment]: `uv run --isolated --no-build --no-project --python 3.13 --with numpy==2.0.0 python -c ...` -> `Because numpy==2.0.0 has no usable wheels and you require numpy==2.0.0, we can conclude that your requirements are unsatisfiable.`; the same with `numpy==2.1.0` -> `Installed 1 package`, `2.1.0`.

**Installation (research-only; execution happens in the plan):**
```bash
# Hand-write pyproject.toml (see Code Examples). Do NOT run `uv init` inside the repo (Pitfall 13).
uv lock                  # creates uv.lock; user commits it
uv sync --locked
uv run sdplab --help
```

**Version verification:** PyPI JSON queried 2026-10-13/14: numpy 2.5.4, matplotlib 3.11.2, pytest 9.1.1, ruff 0.17.0, uv_build 0.13.0; identical to the versions in the throwaway `uv.lock` (18 packages). `uv.lock` records 434 `sha256` hashes in the throwaway lock.

## Package Legitimacy Audit

Command run: `node .claude/gsd-core/bin/gsd-tools.cjs query package-legitimacy check --ecosystem pypi numpy matplotlib pytest ruff uv-build uv_build`.

| Package | Registry | Age | Downloads | Source Repo | Seam verdict | Disposition |
|---------|----------|-----|-----------|-------------|--------------|-------------|
| numpy | PyPI | multi-year project; latest release 2026-10-10 | not exposed by seam (`null`) | github.com/numpy/numpy (PyPI `project_urls.source`) | SUS (`too-new`, `unknown-downloads`, `no-repository`) | Approved by user decision D-03/ADR-009; flagged, see note |
| matplotlib | PyPI | multi-year; latest 2026-09-11 | `null` | github.com/matplotlib/matplotlib | SUS (`unknown-downloads`) | Approved (D-03); flagged |
| pytest | PyPI | multi-year; latest 2026-06-19 | `null` | github.com/pytest-dev/pytest | SUS (`unknown-downloads`) | Approved (D-03); flagged |
| ruff | PyPI | multi-year; latest 2026-10-09 | `null` | github.com/astral-sh/ruff | SUS (`too-new`, `unknown-downloads`) | Approved (D-03); flagged |
| uv_build | PyPI | same project as uv; latest 2026-10-09 | `null` | github.com/astral-sh/uv | SUS (`too-new`, `unknown-downloads`) | Approved (STACK.md, `uv init` default); flagged |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged suspicious [SUS]:** all five. The reasons are heuristic artefacts: the PyPI JSON API publishes no download counts (so `unknown-downloads` is automatic) and `too-new` reflects a release in the last week of a long-lived project; for numpy the `no-repository` reason comes from the seam not reading PyPI's `project_urls.source` (which does list `https://github.com/numpy/numpy` [VERIFIED: PyPI JSON]). These are the packages the user confirmed (D-03, ADR-009) and they were not discovered via web search. **The planner must still add one `checkpoint:human-verify` before the first lock is accepted**, covering: the 18 package names in `uv.lock` equal the expected list (colorama, contourpy, cycler, fonttools, iniconfig, kiwisolver, matplotlib, numpy, packaging, pillow, pluggy, pygments, pyparsing, pytest, python-dateutil, ruff, sdplab, six - the throwaway lock; all but `sdplab` are PyPI-sourced) and no unexpected extra index is configured. The user reviews the lock when committing it anyway.

## Architecture Patterns

### System Architecture Diagram

```
 config.toml ──► config.load()/loads() ──► validated dict (defaults merged)
                    │  tomllib.load(binary file)                   │
                    │  ConfigError(key, problem)                   │ seed, sizes, pt_cut, eta_cut ...
                    ▼                                              ▼
              (Phase 3/4 consumers)                     dataset.generate(n, seed)
                                                          │  SeedSequence(seed).spawn(5)
                                                          │  one Generator per column, fixed order
                                                          ▼
                                       structured ndarray, EVENT_DTYPE, 1-D, C-contiguous
                                          │                       │                     │
                                          ▼                       ▼                     ▼
                              assert_canonical(a)       preprocess(a, pt_cut,     dataset_record(seed, a)
                              (type, dtype, aligned,     eta_cut)                  {seed, rows, numpy_version,
                               ndim, contiguity)           │  mask, n_selected,        dtype, sha256}
                                          │                │  sum_pt, pt_z                │
                                          ▼                ▼                              ▼
                              identity_sha256(a)     PreprocessResult         check_dataset_record(recorded, regen)
                              (dtype text + shape       │                       -> Mismatch("dataset differs ...")
                               + bytes; any C-contig)   ▼
                                          │       validate.assert_preprocess_identical(expected, actual)
                                          ▼             (int equality, float bit patterns, array bytes)
                           validate.assert_arrays_identical(expected, actual)
                              (type, dtype text, shape, hash)  -> Mismatch(aspect, detail)

 cli.main(argv) ── argparse, only --help in Phase 1 ──► exit 0        __main__.py: sys.exit(main())
```

### Recommended Project Structure

```
pyproject.toml            # hand-written, see Code Examples
uv.lock                   # committed by the user
.python-version           # "3.13"
.github/workflows/ci.yml
data/generated/.gitkeep   # create (FND-04; directory does not exist yet)
results/raw/.gitkeep      # create
results/plots/.gitkeep    # create
results/reports/.gitkeep  # create
src/sdplab/
├── __init__.py           # EMPTY (a package that imports cli/report would pull matplotlib into every worker, PITFALLS M8)
├── __main__.py           # sys.exit(main())
├── cli.py                # argparse, --help only
├── config.py             # schema table, ConfigError, loads/load
├── dataset.py            # EVENT_DTYPE, dtype_description, assert_canonical, identity_sha256, array_sha256, generate, dataset_record
├── preprocess.py         # preprocess()
└── validate.py           # Mismatch, assert_arrays_identical, assert_preprocess_identical, check_dataset_record
tests/
├── conftest.py           # small-array and aligned-copy fixtures
├── test_cli.py  test_config.py  test_dataset.py  test_preprocess.py  test_validate.py
├── test_repo_hygiene.py  # FND-04 git check-ignore, no hard-coded SHA, no timing calls, single-numpy lock, CI file shape
└── test_tracer.py        # config -> generate -> hash -> record -> validate through the installed package
```

### Pattern 1: Table-driven config validation (FND-03)
**What:** One `SCHEMA` dict `section -> key -> (validator, default)`; validators return the normalised value or raise `ConfigError(key, problem)` with the dotted key path (`dataset.sizes[1]`). Unknown keys are checked at the top level and per section before values.
**When to use:** always for this phase; the complete key set is fixed here (D-06).
**Why:** tests assert on `e.key` (machine-readable) instead of matching message prose; verified with 31 rejection cases. See Code Examples.

### Pattern 2: Two-layer identity (DAT-02, DAT-05; D-10, D-13)
**What:** `identity_sha256(a)` hashes `domain tag + dtype text + shape + raw bytes` for any C-contiguous array and performs **no** form check. `array_sha256(a)` = `assert_canonical(a)` then `identity_sha256(a)`. `assert_canonical` requires `type(a) is np.ndarray`, `a.dtype == EVENT_DTYPE` **and** equal canonical dtype text, not `isalignedstruct`, `itemsize == 34`, `ndim == 1`, C-contiguous.
**Why two layers:** with only the checked function the hash can never be computed for an aligned/big-endian/renamed array, so a test cannot show that the hash "distinguishes" them. Mutation experiment [VERIFIED: experiment, NumPy 2.5.4, py3.12]: deleting the dtype line from the hash, deleting the shape line, and deleting the canonical check were each caught by a test only after the unchecked layer existed (single-layer version: the first two mutations were caught by nothing except an unrelated subprocess test). Dtype metadata and field titles are outside the dtype text; titled dtypes fail `dtype ==`, metadata does not (see Pitfall 4).

### Pattern 3: Per-column `SeedSequence` streams
**What:** `children = np.random.SeedSequence(seed).spawn(5)` in a fixed column order; one `np.random.default_rng(child)` per random column; each column drawn with **one** call of size `n`. Categorical column derived explicitly: `cdf = np.cumsum(weights); cdf[-1] = 1.0; codes[np.searchsorted(cdf, rng.random(n), side="right")]`.
**Why:** adding or reordering a column cannot change the others; only `lognormal`, `normal`, `uniform`, `random` are used (none of the `binomial`/`multinomial` family D-11 excludes). One call per column because NumPy reserves the right to use different algorithms for different block sizes [CITED: numpy.org/doc/stable/reference/random/compatibility.html: "We reserve the ability to decide to use different algorithms for different-sized blocks. In practice, this happens rarely."].
**Observation, not a guarantee:** the first 100,000 rows of a 1,000,000-row dataset were byte-identical to the 100,000-row dataset (NumPy 2.5.4). Do not make this a required test; NumPy does not promise it.

### Pattern 4: Bit-level comparison helpers (DAT-05)
Compare floats by bit pattern (`struct.pack("<d", x)`) never by `==`; compare arrays by dtype text + shape + hash (or bytes), never by `np.array_equal`. `validate.py` must not import `preprocess.py` (dependency rule `formats, validate -> dataset`); take the three values (`n_selected`, `sum_pt`, `pt_z`) via attribute access on any object, or as plain arguments. The Phase 3 digest of preprocess outputs (ARCHITECTURE.md line 160) is deferred; do not design it now.

### Pattern 5: Tracer-bullet first
First task of the first plan: scaffold `pyproject.toml`, empty modules and `tests/test_tracer.py` so that `uv sync --locked`, `uv run sdplab --help`, ruff and pytest are green on a trivial slice. Then fill in modules behind the tracer. This matches the Claude's Discretion item and exercises FND-01/FND-02 early.

### Anti-Patterns to Avoid
- **`np.array_equal` as the gate** (Pitfall 1). Only a secondary check.
- **`str(dtype)`, `repr(dtype)` or `dtype.descr` as the dtype text.** `descr` raises for out-of-order fields; `str`/`repr` text is version-dependent. Use names/formats(`.str`)/offsets/itemsize as JSON.
- **Hash computed only after the canonical check** (Pattern 2).
- **Hard-coded SHA-256 in tests, or comparing prefix-of-larger-dataset.** D-11/D-14.
- **`uv sync --resolution lowest-direct` / `uv lock --resolution lowest-direct` in the repo** - rewrites `uv.lock`. Use `uv run --isolated` (Pitfall 14).
- **Matplotlib imported anywhere in Phase 1 `src/`.** Only a headless-import test may import it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML parsing | A parser | `tomllib.load(f)` on a binary file | Stdlib; read-only; `TOMLDecodeError` is a `ValueError` subclass |
| Hashing | Custom checksum | `hashlib.sha256` with `h.update(a)` (buffer protocol, C-contiguous only) | Verified on NumPy 2.0.0, 2.1.0, 2.5.4: works on structured arrays and on empty arrays; raises `ValueError: ndarray is not C-contiguous` for strided views |
| Seed fan-out | Ad hoc `seed + i` | `np.random.SeedSequence(seed).spawn(k)` | Designed for independent streams. Rejects negatives (`ValueError: expected non-negative integer`) and floats/strings (`TypeError`) but **accepts `True`** and ints beyond 64 bits, so the config validator must reject `bool` itself |
| Weighted categorical | `rng.choice(p=...)` internals | `searchsorted(cumsum(p), rng.random(n), side="right")` with `cdf[-1] = 1.0` | Depends only on the core uniform stream; matched `choice(p=)` in earlier research (PITFALLS G1) |
| Float equality | `==`, `np.isclose` | `struct.pack("<d", x)` comparison | `0.0 == -0.0` is true; ADR-007 forbids tolerance |
| CLI parsing | Manual `sys.argv` | `argparse` (`main(argv=None) -> int`) | Tests call `main([...])` |
| Lock/env management | pip/venv scripts | `uv sync --locked` | Stale lock is detected: editing a floor without relocking gives `error: The lockfile at uv.lock needs to be updated, but --locked was provided.` [VERIFIED: experiment] |

**Key insight:** every "exactness" claim in this phase is only as strong as the weakest primitive used to check it; the primitives above are chosen because each one has a verified failure mode that a naive alternative hides.

## Common Pitfalls

### Pitfall 1: `np.array_equal` blind spots (all [VERIFIED: experiment, NumPy 2.5.4 and 2.0.0 unless noted])
- Packed `a` vs the `align=True` copy (itemsize 40, descr gains `('', '|V6')`): `array_equal` -> `True`, `dtype ==` -> `False`, `tobytes()` differ.
- Big-endian copy (`>` on every field): `array_equal` -> `True`, `dtype ==` -> `False`, bytes differ.
- Padding junk (two aligned arrays, same values, `0xFF` written into padding): `array_equal` -> `True`, bytes differ.
- `-0.0` vs `0.0`: `array_equal` -> `True`, `(a == b).all()` -> `True`, `tobytes()` differ.
- Renamed-field view of the same buffer: `array_equal` **raises** `TypeError: Cannot compare structured arrays unless they have a common dtype`; the bytes-only SHA-256 is identical (collision).
- NaN: `array_equal(c, c)` -> `False`. `equal_nan=True` returns `True` when both arguments are the same object (identity shortcut) and raises `TypeError: ufunc 'isnan' not supported` for two different structured arrays. PITFALLS.md says it "raises"; the nuance matters when writing a negative-control test.
**How to avoid:** the validator checks type, dtype text, shape, then hash; tests include each case above; `array_equal` appears in tests only to *demonstrate* the blind spot.

### Pitfall 2: Canonical check masks the hash tests (see Pattern 2)

### Pitfall 3: `dtype.descr` raises
`np.dtype({"names":["pt","event_id",...],"offsets":[8,0,16,24,32],"itemsize":34,...}).descr` -> `ValueError: dtype.descr is not defined for types with overlapping or out-of-order fields` [VERIFIED: experiment]. An out-of-order dtype is also `!= EVENT_DTYPE`. Use the JSON of `{"names","formats"(each field `.str`),"offsets","itemsize"}`; it is stable and distinguishes aligned (itemsize 40) from packed (34).

### Pitfall 4: Subclasses and dtype oddities
- `a.view(np.recarray)`: `isinstance(x, np.ndarray)` is `True`, `dtype == EVENT_DTYPE` is `True` (dtype type is `numpy.record`); `np.ma.array(a)` is also an `ndarray` instance. Require `type(a) is np.ndarray` [VERIFIED: experiment].
- A titled dtype (`(("T","event_id"),"<i8")`): `dtype ==` -> `False`, but the names-only text is equal; hence check **both** `dtype ==` and the text.
- Dtype `metadata` is invisible to `==`, the text, and the hash (bytes and text unchanged). Harmless; document that metadata is not part of identity.
- 2-D, 0-d, strided views are rejected by `ndim`/`c_contiguous`; a 1-element array is both C- and F-contiguous (accepted); an empty array is accepted and hashable.

### Pitfall 5: `Generator.uniform` can return `high` in general
NumPy documents the `high` limit "may be included in the returned array of floats due to floating-point rounding in the equation `low + (high-low) * random_sample()`" [CITED: numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.uniform.html]. Observed: with `u = 1 - 2**-53` (the largest double `random()` can return), the formula returned `>= high` for 30,490 of 100,000 random `(low, high)` pairs. For `(-pi, pi)` it gives `3.1415926535897922 < pi` [VERIFIED: experiment]. Add a deterministic test of that arithmetic (`-math.pi + 2*math.pi*(1 - 2.0**-53) < math.pi`) next to the data-bound test; the data test alone could never reach the extreme.

### Pitfall 6: Preprocess results are not bit-identical across NumPy versions
Same 100,000-row input (dataset SHA identical on all versions), `preprocess(a)` [VERIFIED: experiment]: NumPy 2.0.0 and 2.1.0 (py3.12 and py3.13): `sum_pt = 1945990.4884465795`, `pt_z.sum().hex() = -0x1.1900000000000p-40`; NumPy 2.5.4: `1945990.4884465793`, `-0x1.e000000000000p-41`; `n_selected = 44657` everywhere. So: (a) D-12's "bit-identical for bit-identical inputs" holds within one environment (repeat runs on 2.5.4, py3.12 and 3.13 were identical); (b) known-answer tests must use small inputs whose sums/means/stds are exactly representable (e.g. `pt = [2,4,4,4,5,5,7,9]`: mean 5, population std 2, z = `[-1.5,-0.5,-0.5,-0.5,0,0,1,2]`); (c) never pin an expected `sum_pt` for generated data; (d) reductions on other CPUs/SIMD builds are untested here (A3).

### Pitfall 7: Declared floors cannot be installed on Python 3.13 (see Standard Stack)

### Pitfall 8: `filterwarnings = ["error"]` meets third-party warnings
`import matplotlib.pyplot` raises `PyparsingDeprecationWarning` for matplotlib <= 3.10.0 with the unpinned transitive pyparsing 3.3.3 (lowest-direct only lowers *direct* dependencies, so transitive packages stay at their highest). Phase 1 `src/` does not import matplotlib; the only exposure is a headless-import smoke test. With the recommended floor this passes. Empty-array reductions (`np.mean([])`) emit `RuntimeWarning` which becomes an error: `preprocess` must raise `ValueError` for empty input and for `std == 0` itself (the prototype does).

### Pitfall 9: Ruff rule traps with the STACK.md selection (`E,F,W,I,B,UP,SIM,NPY,PT,RUF`)
- `PT018` flags `assert a and b`; split asserts.
- `RUF002` (ambiguous Unicode in docstrings) fired on U+2212 (minus sign) and the multiplication sign in a probe docstring; the Greek pi/phi letters, the greater-or-equal and element-of glyphs in the same probe (docstring, comment, string) did not fire. `RUF001`/`RUF003` are the sibling rules for strings/comments and were not observed to fire. Keep `src/` and `tests/` docstrings/comments/strings ASCII to be safe: write `N x 34`, `-pi`.
- `RUF` also contains rules that flag mutable class attributes etc.; none fired on the prototype.
- `ruff format --check` fails on any unformatted file (it caught my sloppy test); run `ruff format` before `--check`.
- Target version is inferred: `linter.unresolved_target_version = 3.12` [VERIFIED: `ruff check --show-settings`].

### Pitfall 10: TOML values that look valid
`seed = true` (bool is an `int` subclass in Python); `timeout_s = nan`/`inf` (valid TOML floats; `max_load_per_core = inf` would pass a bare `>= 0` check); `timeout_s = 1979-05-27` (TOML date -> `datetime.date`); `sizes = [1.5]`; `[dataset.extra]` sub-table; duplicate keys -> `TOMLDecodeError`. All handled in the prototype (type checks use `type(v) is int`, finiteness check before range check).

### Pitfall 11: `TOMLDecodeError` has no position attributes before 3.14
Python 3.12.15 and 3.13.5: no `lineno`/`colno` attribute; Python 3.14.4: `lineno=2, colno=3`. The message text already carries `(at line N, column M)` or `(at end of document)`. STACK.md ("with `lineno`/`colno`") is wrong for the 3.12 floor; wrap the message, do not read attributes.

### Pitfall 12: `uv_build`, `required-version` and future uv releases
`[tool.uv] required-version = ">=0.13,<0.14"` plus `uv_build>=0.13.0,<0.14` mean a fresh clone fails on uv 0.14+ until both are bumped. `required-version` is read by setup-uv when no `version` input is given [CITED: raw.githubusercontent.com/astral-sh/setup-uv/1c37ad07.../README.md lines 33-34: "If you do not specify a version, this action will look for a required-version ... in a `uv.toml` or `pyproject.toml` ... If none is found, the latest version will be installed."]. Trade-off: the cap protects `uv sync --locked` from lockfile-format drift in a new uv; the cost is a bump when uv 0.14 ships. Keep it, and document the bump procedure (Open Question 4).

### Pitfall 13: `uv init` defaults
`uv init --package sdplab` in the scratch directory produced `requires-python = ">=3.13"` (from the discovered interpreter), an `authors` entry taken from `git config` (name `vishnu97770`, an e-mail), a `[project.scripts] sdplab = "sdplab:main"` pointing at `__init__`, and its own `.gitignore`/`.git` when run outside a repo. Hand-write `pyproject.toml` instead (Code Examples) and decide on `authors` explicitly (Open Question 3).

### Pitfall 14: lowest-direct check rewrites the lock
`uv run --isolated --resolution lowest-direct ...` prints `Ignoring existing lockfile due to change in resolution mode: highest vs. lowest-direct` and leaves `uv.lock` byte-identical (sha256 compared before and after, three runs) [VERIFIED: experiment]. STACK.md's `uv sync --resolution lowest-direct` was not run; by uv semantics it re-locks (A5).

### Pitfall 15: `.gitkeep` files and `dist/`
The `.gitignore` has `!data/generated/.gitkeep` etc., but no such files or directories exist yet (`ls` of the repo root shows only `.claude .git .gitignore .planning README.md docs`). Create the four empty `.gitkeep` files. `uv build` would create an untracked `dist/` (not ignored); not needed in CI, so either avoid building or add `dist/` to `.gitignore` ("add only what the new files need", D-05).

### Pitfall 16: CI parity on this machine is partly a different interpreter
`uv run --isolated --locked --python 3.13` resolved to the Anaconda 3.13.5, not a uv-managed 3.13. GitHub runners will use whatever uv selects there (A1). For hermetic parity: `uv python install 3.12 3.13` then `UV_PYTHON_PREFERENCE=only-managed`. I did not install a managed 3.13 (it would write to the home directory, outside the research scope).

### Pitfall 17: `uv sync --locked` first use is slow without network cache
The first sync downloaded numpy (18 MiB) and matplotlib (8 MiB) and took 85 s on this connection; set `UV_HTTP_TIMEOUT=120` if a verifier's network is slow. Cross-device hardlink fallbacks (`Invalid cross-device link`) are only DEBUG noise; `UV_LINK_MODE=copy` silences them.

## Code Examples

All examples below were run (prototype in the scratch project). Values in them that come from project documents are quoted here verbatim.

Verbatim source quotes used by the examples:

- `.planning/phases/01-foundation-dataset/01-CONTEXT.md:33` (D-08): `` `EVENT_DTYPE` is exactly `[("event_id","<i8"), ("pt","<f8"), ("eta","<f8"), ("phi","<f8"), ("category_code","<i2")]`, little-endian, packed (no alignment padding), 34 bytes per row. ``
- `docs/architecture/PROPOSAL.md:125`: `EVENT_DTYPE = np.dtype([("event_id","<i8"), ("pt","<f8"), ("eta","<f8"), ("phi","<f8"), ("category_code","<i2")])  # 34 B/row`
- `docs/architecture/PROPOSAL.md:186-193`:
```toml
config_schema_version = 1
[dataset]  seed = 12345  sizes = [10000, 100000, 1000000]  data_dir = "data/generated"
[formats]  enabled = ["csv", "npy", "npz", "npz_compressed"]
[workload] pt_cut = 20.0  eta_cut = 2.4  operations = ["write", "load", "preprocess", "load_preprocess"]
[trials]   warmup_rounds = 2  measured_rounds = 7  order_seed = 777  fsync = false  timeout_s = 600
[noise]    outlier_factor = 3.0  max_load_per_core = 0.5
[environment] thread_env = "inherit"   # or "single": worker env sets the four *_NUM_THREADS variables to 1; effective values always recorded
[output]   results_dir = "results"
```
- `docs/adr/ADR-015.md` Decision: `` `requires-python = ">=3.12"`. ``
- Design choices NOT from any source (Claude's discretion, D-09): category codes `0..4` with weights `(0.40, 0.30, 0.15, 0.10, 0.05)`, `pt ~ lognormal(mean=3.0, sigma=0.8)` (median about 20.1, observed 50.3% of rows above 20.0), `eta ~ normal(0, 1.5)` clipped (observed 9.66% of rows exactly at +-2.5; a smaller sigma such as 1.0 would clip far fewer rows and is equally valid).

### `pyproject.toml` (verified: `uv lock`, `uv sync --locked`, ruff, pytest on 3.12 and 3.13)

```toml
[project]
name = "sdplab"
version = "0.1.0"
description = "Reproducible benchmark of CSV vs NumPy .npy/.npz loading"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
  "numpy>=2.1",          # raised from 2.0: first release with cp313 wheels (Open Question 1)
  "matplotlib>=3.10.8",  # raised from 3.9: lowest version proven to import under filterwarnings=error
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
required-version = ">=0.13,<0.14"

[tool.pytest]
minversion = "9.0"
testpaths = ["tests"]
addopts = ["-ra"]
strict = true
filterwarnings = ["error"]

[tool.ruff]
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "NPY", "PT", "RUF"]
```

Verified behaviours: native `[tool.pytest]` is read (`configfile: pyproject.toml`); `strict = true` rejects an undeclared marker (`'nope' not found in markers configuration option`); `filterwarnings=["error"]` turns `warnings.warn(..., RuntimeWarning)` into a failure. Drop the `markers = ["e2e: ..."]` line from STACK.md in Phase 1 (unused).

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
    timeout-minutes: 15
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
          python-version: ${{ matrix.python-version }}
          enable-cache: true
      - run: uv sync --locked
      - run: uv run --no-sync ruff check
      - run: uv run --no-sync ruff format --check
      - run: uv run --no-sync pytest
      - name: Declared floors (wheels only; does not modify uv.lock)
        run: uv run --isolated --no-build --resolution lowest-direct pytest
```

Re-verification of the pinned actions this session [VERIFIED: `git ls-remote --tags`, `api.github.com/repos/.../git/ref/tags/...`, raw `action.yml`]:
- `actions/checkout`: `3d3c42e5aac5ba805825da76410c181273ba90b1` = `refs/tags/v7.0.1` (also the floating `v7`); GitHub API: `object.type = "commit"`. `action.yml` has `persist-credentials`, `using: node24`. Newest tags seen: v7, v7.0.0, v7.0.1.
- `astral-sh/setup-uv`: `1c37ad07a6a961277cf70c0d37d6f313000f5884` = `refs/tags/v10.3.0` (newest tag; no floating `v10`); API: `object.type = "commit"`. `action.yml` has inputs `python-version` (sets `UV_PYTHON`), `enable-cache` (default `auto`), `version`, `version-file`; `using: "node24"`.
- Both SHAs equal the ones recorded in STACK.md, so STACK.md's values were correct, but they were re-derived, not copied. Re-run `git ls-remote` when the file is written in case newer tags exist.
- `ubuntu-24.04` is a listed standard hosted-runner label [CITED: docs.github.com/en/actions/reference/runners/github-hosted-runners].
- The workflow itself cannot run locally (no `act`, `gh`, or `actionlint` installed). Its content is verified only action-by-action plus the equivalent local commands below (A4). Green CI requires the user to push; plan it as an end-of-phase human-verify item (`human_verify_mode: end-of-phase` in config).
- The last step (floors) ran locally on both Pythons: 57 passed, `uv.lock` unchanged. If the planner prefers exactly four commands per leg, drop it and run the floors check manually at phase verification instead.

### `dataset.py` core (verified; 57 tests)

```python
"""Dataset: EVENT_DTYPE, deterministic generator, shape-aware identity hash."""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np

EVENT_DTYPE = np.dtype(
    [("event_id", "<i8"), ("pt", "<f8"), ("eta", "<f8"), ("phi", "<f8"), ("category_code", "<i2")]
)
ROW_BYTES = 34
CATEGORY_CODES = (0, 1, 2, 3, 4)  # design choice (D-09 discretion)
CATEGORY_WEIGHTS = (0.40, 0.30, 0.15, 0.10, 0.05)  # design choice
_HASH_DOMAIN = b"sdplab-array-v1"


def dtype_description(dt: np.dtype) -> str:
    """Canonical text of a structured dtype (not numpy's repr/str/descr, which vary or raise)."""
    if dt.names is None:
        raise TypeError("structured dtype required")
    return json.dumps(
        {
            "names": list(dt.names),
            "formats": [dt.fields[n][0].str for n in dt.names],
            "offsets": [dt.fields[n][1] for n in dt.names],
            "itemsize": dt.itemsize,
        },
        separators=(",", ":"),
    )


EXPECTED_DESCRIPTION = dtype_description(EVENT_DTYPE)


class NotCanonicalError(ValueError):
    """Not the canonical 1-D C-contiguous packed little-endian EVENT_DTYPE array."""


def assert_canonical(a: object) -> None:
    if type(a) is not np.ndarray:
        raise NotCanonicalError(f"type {type(a).__name__} is not a plain numpy.ndarray")
    if a.dtype != EVENT_DTYPE or dtype_description(a.dtype) != EXPECTED_DESCRIPTION:
        raise NotCanonicalError("dtype differs from EVENT_DTYPE")
    if a.dtype.isalignedstruct or a.dtype.itemsize != ROW_BYTES:
        raise NotCanonicalError("dtype is aligned or padded")
    if a.ndim != 1:
        raise NotCanonicalError(f"expected 1-D array, got ndim={a.ndim}")
    if not a.flags.c_contiguous:
        raise NotCanonicalError("array is not C-contiguous")


def identity_sha256(a: np.ndarray) -> str:
    """SHA-256 over dtype description + shape + bytes. No canonical-form requirement."""
    if not a.flags.c_contiguous:
        raise NotCanonicalError("array is not C-contiguous")
    h = hashlib.sha256()
    h.update(_HASH_DOMAIN + b"\0")
    h.update(dtype_description(a.dtype).encode() + b"\0")
    h.update(json.dumps(list(a.shape)).encode() + b"\0")
    h.update(a)  # buffer protocol; works for structured and empty arrays
    return h.hexdigest()


def array_sha256(a: np.ndarray) -> str:
    """Dataset identity hash: canonical-form check, then identity_sha256."""
    assert_canonical(a)
    return identity_sha256(a)


def generate(n: int, seed: int) -> np.ndarray:
    if n < 0:
        raise ValueError("n must be >= 0")
    ss = np.random.SeedSequence(seed)
    _, c_pt, c_eta, c_phi, c_cat = ss.spawn(5)  # fixed column order; slot 0 = event_id (unused)
    out = np.zeros(n, dtype=EVENT_DTYPE)
    out["event_id"] = np.arange(n, dtype="<i8")
    out["pt"] = np.random.default_rng(c_pt).lognormal(mean=3.0, sigma=0.8, size=n)
    out["eta"] = np.clip(np.random.default_rng(c_eta).normal(0.0, 1.5, size=n), -2.5, 2.5)
    out["phi"] = np.random.default_rng(c_phi).uniform(-math.pi, math.pi, size=n)
    cdf = np.cumsum(np.asarray(CATEGORY_WEIGHTS))
    cdf[-1] = 1.0
    u = np.random.default_rng(c_cat).random(n)
    out["category_code"] = np.asarray(CATEGORY_CODES, dtype="<i2")[
        np.searchsorted(cdf, u, side="right")
    ]
    return out


def dataset_record(seed: int, a: np.ndarray) -> dict:
    return {
        "seed": seed,
        "rows": int(a.shape[0]),
        "numpy_version": np.__version__,
        "dtype": json.loads(dtype_description(a.dtype)),  # explicit fields, not str(dtype)
        "sha256": array_sha256(a),
    }
```
Seed validation (reject `bool`, negatives) belongs in `config`; `generate` receives a validated int. `np.zeros` (not `np.empty`) is used so the buffer is deterministic even if a future dtype gains padding.

### `preprocess.py` and `validate.py` cores (verified)

```python
class PreprocessResult(NamedTuple):
    n_selected: int
    sum_pt: float
    pt_z: np.ndarray


def preprocess(a, pt_cut=20.0, eta_cut=2.4) -> PreprocessResult:
    assert_canonical(a)
    if a.shape[0] == 0:
        raise ValueError("cannot preprocess an empty array")  # avoids RuntimeWarning from mean([])
    pt = a["pt"]
    mask = (pt > pt_cut) & (np.abs(a["eta"]) < eta_cut)
    std = pt.std()  # population std (ddof=0), full column
    if not std > 0:
        raise ValueError("pt column has zero standard deviation")
    return PreprocessResult(
        int(np.count_nonzero(mask)), float(pt[mask].sum()), (pt - pt.mean()) / std
    )
```
The reduction expressions are part of the contract: `pt[mask].sum()` and `np.sum(pt, where=mask)` can differ in the last bits; define it once and document it.

```python
class Mismatch(AssertionError):
    def __init__(self, aspect, detail):
        self.aspect = aspect  # "type" | "dtype" | "shape" | "bytes" | "n_selected" | "sum_pt" | "pt_z" | "dataset"
        super().__init__(f"{aspect} differs: {detail}")


def assert_arrays_identical(expected, actual):
    if type(actual) is not np.ndarray:
        raise Mismatch("type", type(actual).__name__)
    if actual.dtype != expected.dtype or dtype_description(actual.dtype) != dtype_description(
        expected.dtype
    ):
        raise Mismatch("dtype", ...)
    if actual.shape != expected.shape:
        raise Mismatch("shape", ...)
    if array_sha256(expected) != array_sha256(actual):
        raise Mismatch("bytes", "SHA-256 of canonical bytes differs")


def _bits(x: float) -> bytes:
    return struct.pack("<d", x)  # 0.0 and -0.0 differ; nan keeps its payload


def check_dataset_record(recorded, regenerated):
    if recorded["sha256"] != regenerated["sha256"]:
        raise Mismatch(
            "dataset",
            f"recorded numpy {recorded['numpy_version']}, regenerated numpy {regenerated['numpy_version']}",
        )
        # message starts "dataset differs: ..." as required by DAT-03
```

### `config.py` core (verified: 31 rejection cases on 3.12.15 and 3.13.5)

```python
class ConfigError(ValueError):
    def __init__(self, key: str, problem: str):
        self.key, self.problem = key, problem
        super().__init__(f"config key '{key}': {problem}")

def _int(lo=None):
    def check(key, v):
        if type(v) is not int:                       # bool is an int subclass: reject explicitly
            raise ConfigError(key, f"expected integer, got {type(v).__name__}")
        if lo is not None and v < lo:
            raise ConfigError(key, f"must be >= {lo}, got {v}")
        return v
    return check

def _float(*, gt=None, ge=None):
    def check(key, v):
        if type(v) not in (int, float):              # TOML 20 and 20.0 both accepted; bool/str/date rejected
            raise ConfigError(key, f"expected number, got {type(v).__name__}")
        v = float(v)
        if not math.isfinite(v):                     # nan/inf are valid TOML floats
            raise ConfigError(key, f"must be finite, got {v}")
        if gt is not None and not v > gt: raise ConfigError(key, f"must be > {gt}, got {v}")
        if ge is not None and not v >= ge: raise ConfigError(key, f"must be >= {ge}, got {v}")
        return v
    return check
# _bool, _str (non-empty), _enum(allowed), _list_of(item_check, min_len=1, unique=True) analogous.

SCHEMA = {  # section -> key -> (validator, default)   (defaults = PROPOSAL.md:186-193 quoted above)
    "dataset":     {"seed": (_int(0), 12345), "sizes": (_list_of(_int(1)), [10_000, 100_000, 1_000_000]),
                    "data_dir": (_str, "data/generated")},
    "formats":     {"enabled": (_list_of(_enum(KNOWN_FORMATS)), list(KNOWN_FORMATS))},
    "workload":    {"pt_cut": (_float(ge=0.0), 20.0), "eta_cut": (_float(gt=0.0), 2.4),
                    "operations": (_list_of(_enum(KNOWN_OPERATIONS)), list(KNOWN_OPERATIONS))},
    "trials":      {"warmup_rounds": (_int(0), 2), "measured_rounds": (_int(1), 7), "order_seed": (_int(0), 777),
                    "fsync": (_bool, False), "timeout_s": (_float(gt=0.0), 600.0)},
    "noise":       {"outlier_factor": (_float(gt=1.0), 3.0), "max_load_per_core": (_float(ge=0.0), 0.5)},
    "environment": {"thread_env": (_enum(("inherit", "single")), "inherit")},
    "output":      {"results_dir": (_str, "results")},
}
KNOWN_FORMATS = ("csv", "npy", "npz", "npz_compressed")
KNOWN_OPERATIONS = ("write", "load", "preprocess", "load_preprocess")

def validate(raw):
    # 1. config_schema_version present, `type(ver) is int and ver == 1` else ConfigError("config_schema_version", ...)
    # 2. unknown top-level key -> ConfigError(k, "unknown key")
    # 3. per section: must be a dict (else "expected table"); unknown key -> ConfigError(f"{section}.{k}", "unknown key")
    # 4. each known key: validator(f"{section}.{k}", value) or default
```
`loads(text)` / `load(path)` wrap `tomllib.TOMLDecodeError` and `OSError` into `ConfigError("<toml>" / "<file>", ...)`; `load` opens with `open(path, "rb")`.

Design decisions to confirm are Open Questions 2 (defaults vs required keys) and the extra enum on `workload.operations` / uniqueness rules, which D-07 does not spell out.

### Representative tests (all verified)

```python
# two fresh processes -> identical bytes (DAT-01/D-11); -I isolates from PYTHONPATH/user site, hash seed varied
def test_two_fresh_processes_yield_identical_bytes():
    code = "import sys; from sdplab.dataset import array_sha256, generate; sys.stdout.write(array_sha256(generate(2000, 4242)))"
    outs = []
    for hashseed in ("0", "1", "random"):
        r = subprocess.run(
            [sys.executable, "-I", "-c", code],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONHASHSEED": hashseed, "PATH": "/usr/bin"},
        )
        outs.append(r.stdout)
    assert outs[0] == outs[1] == outs[2] == array_sha256(generate(2000, 4242))


# no hard-coded SHA / no timing in tests (D-11, D-14) - a meta-test over tests/*.py
assert not re.search(r"\b[0-9a-fA-F]{64}\b", text)  # the meta-test file itself is excluded
assert not re.search(r"perf_counter|process_time|time\.time\(|timeit", text)

# -0.0: the blind spot is asserted, then the validator is asserted to reject it
a["eta"][0], b["eta"][0] = 0.0, -0.0
assert np.array_equal(a, b)
with pytest.raises(Mismatch) as e:
    assert_arrays_identical(a, b)
assert e.value.aspect == "bytes"
```

## State of the Art

| Old / assumed | Current / verified | Impact |
|---------------|--------------------|--------|
| `numpy>=2.0` / `matplotlib>=3.9` floors | Floors with cp313 wheels and a warning-clean matplotlib import: `numpy>=2.1`, `matplotlib>=3.10.8` | Floors become installable and testable on both CI legs |
| `uv sync --resolution lowest-direct` | `uv run --isolated --no-build --resolution lowest-direct` | Lock untouched |
| `TOMLDecodeError.lineno/colno` | Present only on Python 3.14+ | Use the message text |
| `[tool.pytest.ini_options]` | native `[tool.pytest]` (pytest >= 9.0) | Verified working with `strict = true` |
| Floating action tags | Full-SHA pins with version comments | `setup-uv` has no floating major tag |

**Deprecated/outdated:** legacy `np.random.seed`/`RandomState` (ruff `NPY` flags them; NumPy says `RandomState` will not be modified "not even to fix correctness bugs" [CITED: numpy.org compatibility policy]).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A hosted-runner 3.12/3.13 leg behaves like the local runs although local 3.13 was the Anaconda build and 3.12 a uv-managed build; no managed 3.13 was installed or tested | Pitfall 16, Validation Architecture | A CI-only failure that local parity missed; low (pure-Python code + wheels) |
| A2 | `SeedSequence.spawn` / `PCG64` output is stable across the NumPy versions users may install. NumPy docs say BitGenerators have "stronger guarantees" but the SeedSequence page states nothing; observed identical dataset hashes on 2.0.0, 2.1.0, 2.5.4 only | Pattern 3 | Dataset changes on a future NumPy; mitigated by D-11 (record NumPy version + hash, report "dataset differs") |
| A3 | `preprocess` reductions are bit-identical across CPUs for the same NumPy build (only one CPU, AVX2/no AVX512, tested) | Pitfall 6 | A recorded preprocess digest could differ across machines (matters in Phase 3, not here) |
| A4 | The CI workflow runs green on GitHub (cannot be executed locally; actions verified individually, commands verified locally) | CI example | First push fails; fix-forward. Needs the user's push |
| A5 | `uv sync --resolution lowest-direct` rewrites `uv.lock` (by uv semantics; not run to avoid touching a lock) | Pitfall 14 | Only affects advice against using it |
| A6 | matplotlib 3.10.1 to 3.10.7 behaviour under `-W error` (untested; 3.10.8 chosen as the proven floor) | Standard Stack | A lower floor might also work; no harm in the higher one |
| A7 | pytest floor `>=9.1` is sufficient; lowest-direct resolved 9.1.0 and the suite passed | Standard Stack | None observed |
| A8 | A future uv 0.14 invalidates `required-version = ">=0.13,<0.14"` for fresh clones | Pitfall 12 | Policy choice, see Open Question 4 |
| A9 | `workload.operations` should be validated against the four documented names; sizes/enabled lists should reject duplicates; `pt_cut >= 0` and `eta_cut > 0` as ranges | Code Examples (config) | D-07 only names some ranges; stricter checks could reject a configuration the user wants |
| A10 | Python 3.14 (installed at `/usr/bin/python3.14`) is not exercised; `requires-python >=3.12` admits it | Environment | Untested interpreter possible for users; CI only claims 3.12/3.13 |

## Open Questions (RESOLVED)

> Each question is answered in plan `01-01-PLAN.md` under "Decisions needing user confirmation" (resolved 2026-10-14 by the planner as a *default*). "RESOLVED" here means the plan adopts an answer; the answers that change confirmed documents (1) or are otherwise user-visible remain subject to the user's approval at the plan-01-01 Task 1 checkpoint before any execution.

1. **Raise the dependency floors?** (D-02 allows either.)
   - Known: the declared floors cannot be installed from wheels on 3.13, and matplotlib <= 3.10.0 breaks `import matplotlib.pyplot` under `filterwarnings=error` with current pyparsing. Verified alternative: `numpy>=2.1`, `matplotlib>=3.10.8`.
   - Unclear: user preference; raising changes wording in `docs/architecture/PROPOSAL.md:238` (`Runtime: numpy>=2.0, matplotlib.`), `.planning/PROJECT.md:55`, `.claude/CLAUDE.md:18` and the STACK/SUMMARY research files. This research did not edit them.
   - Recommendation: raise, and add the lowest-direct step to CI; the executor updates PROPOSAL section 13 and PROJECT.md in the same change with the user's approval.
   - **RESOLVED (plan default, user approval pending at the Task 1 checkpoint):** raise to `numpy>=2.1`, `matplotlib>=3.10.8`; lowest-direct step in CI; document edits in plan 01-05.
2. **Config keys optional-with-defaults or all required?** D-06 says "complete and fixed" key set and "proposed defaults". Recommendation: only `config_schema_version` required; every section/key optional with the PROPOSAL section 10 defaults (so `configs/example.toml` in Phase 4 can be small), plus one test that the literal PROPOSAL section 10 block validates and equals the defaults.
   - **RESOLVED (plan default):** only `config_schema_version` required; everything else defaults (plan 01-02).
3. **`authors` / license metadata in `pyproject.toml`.** `uv init` would copy the git-config identity. Recommendation: omit `authors` unless the user supplies it; no `license` key (none decided).
   - **RESOLVED (plan default):** omit `authors` and `license`.
4. **`required-version` cap policy** (Pitfall 12): keep the `<0.14` cap and record the bump procedure in the README/Phase 5, or use `>=0.13`.
   - **RESOLVED (plan default):** keep the `<0.14` cap; bump procedure documented.
5. **Duplicate or contradictory sizes/formats** (A9): reject duplicates (recommended: duplicate cells would collide in later run ids).
   - **RESOLVED (plan default):** reject duplicate `sizes`/`formats` and unknown `operations` names (plan 01-02).
6. **Add `sdplab info` now?** Recommendation: no; Phase 1 requires only `--help`, and `info` content depends on Phase 3 environment capture.
   - **RESOLVED:** no `sdplab info` in Phase 1 (CONTEXT.md discretion; CLI subcommands are Phase 4).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | all | yes | 0.13.0 | none needed |
| CPython 3.12 | CI parity | yes (uv-managed) | 3.12.15 | `uv python install 3.12` |
| CPython 3.13 | primary | yes (Anaconda; not uv-managed) | 3.13.5 | `uv python install 3.13` (not run) |
| CPython 3.14 | n/a | yes (`/usr/bin`) | 3.14.4 | not used |
| git | FND-04 tests | yes | 2.53.0 | tests skip if absent |
| Network to PyPI / GitHub | lock, CI SHAs | yes, slow (first sync of 3.13 wheels took 85 s; stalls up to several minutes were seen) | - | `UV_HTTP_TIMEOUT=120`; warm cache afterwards |
| gh CLI, actionlint, act | CI lint | no | - | none; workflow verified per action + equivalent local commands |
| node | GSD tooling only | yes (v22.22.1) | - | not a runtime dependency |

Repo disk is ext4 at 88% used; `/tmp` is tmpfs (irrelevant in Phase 1: no timing, no file formats).

**Missing with no fallback:** none. **Missing with fallback:** a way to run the workflow itself (needs a push by the user).

## Validation Architecture

> Required: `workflow.nyquist_validation` is `true` in `.planning/config.json` (read this session).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 (locked; floor 9.1) with native `[tool.pytest]`, `strict = true`, `filterwarnings = ["error"]` |
| Config file | `pyproject.toml` (to be created; Wave 0) |
| Quick run command | `uv run --no-sync pytest -q -x` (prototype: 57 tests in 0.31 to 0.35 s on both Pythons) |
| Lint/format commands | `uv run --no-sync ruff check` and `uv run --no-sync ruff format --check` |
| Full suite command | `uv run pytest` (syncs first) |
| Estimated runtime | under 2 s for tests; the floors/parity runs add seconds once the uv cache is warm |

### Phase Requirements -> Test Map

| Req ID | Behavior | Test type | Automated command | File exists? |
|--------|----------|-----------|-------------------|--------------|
| FND-01 | Fresh clone: lock current, one NumPy, `sdplab --help` rc 0, `python -m sdplab --help` rc 0, `requires-python >=3.12`, package version importable from metadata | smoke + repo | `uv lock --check`; `uv sync --locked`; `uv run sdplab --help`; `uv run --no-sync pytest tests/test_cli.py tests/test_repo_hygiene.py -q` | Wave 0 |
| FND-01 | Lock resolves exactly one `numpy` entry, `requires-python == ">=3.12"`, no `resolution-markers` | unit (reads `uv.lock` via `tomllib`) | `uv run --no-sync pytest tests/test_repo_hygiene.py -q -k lock` | Wave 0 |
| FND-02 | Same three commands pass on 3.12 and 3.13 locally (CI parity) | integration (commands) | see "CI parity" below | n/a |
| FND-02 | Workflow file shape: every `uses:` is a 40-hex SHA with `# v` comment; matrix has `"3.12"` and `"3.13"`; contains `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest`; contains no `sdplab run`/benchmark invocation; `permissions: contents: read` | unit (regex over `.github/workflows/ci.yml`; no PyYAML dependency) | `uv run --no-sync pytest tests/test_repo_hygiene.py -q -k workflow` | Wave 0 |
| FND-02 | Green hosted run on both legs | manual (needs user push) | human-verify at end of phase | n/a |
| FND-03 | Valid configs load; full PROPOSAL section 10 block equals defaults; every rejection case names the key (`e.key`) | unit, parametrized | `uv run --no-sync pytest tests/test_config.py -q` | Wave 0 |
| FND-04 | `git check-ignore` ignores the five required path classes; does not ignore `.claude/CLAUDE.md`, `.claude/settings.json`, `.planning/PROJECT.md`, `uv.lock`, `.gitkeep` files; `.gitkeep` files exist | unit (subprocess `git check-ignore -q --`; skip if git or work tree missing) | `uv run --no-sync pytest tests/test_repo_hygiene.py -q -k ignore` | Wave 0 |
| DAT-01 | dtype layout; canonical; bounds; same seed same bytes in process; different seed differs; n = 0/1/2; phi arithmetic bound; two fresh processes identical | unit + subprocess | `uv run --no-sync pytest tests/test_dataset.py -q` | Wave 0 |
| DAT-02 | `identity_sha256` yields 5 distinct values for packed, aligned, big-endian, renamed view, reshaped array; same content same hash; 1-ULP changes hash; `array_sha256` rejects the non-canonical ones; no 64-hex literal in tests | unit + meta | `uv run --no-sync pytest tests/test_dataset.py tests/test_repo_hygiene.py -q` | Wave 0 |
| DAT-03 | `dataset_record` keys (`seed`, `rows`, `numpy_version`, `dtype`, `sha256`); regenerate equal -> pass; different content -> `Mismatch` with message starting `dataset differs` | unit | `uv run --no-sync pytest tests/test_validate.py -q -k dataset` | Wave 0 |
| DAT-04 | Known answers (selection boundaries `pt == 20.0` and `abs(eta) == 2.4` excluded; sum 110.5; exact z-scores); repeat is bit-identical; input unmodified; empty and constant input raise `ValueError` | unit | `uv run --no-sync pytest tests/test_preprocess.py -q` | Wave 0 |
| DAT-05 | Reject: 1-ULP in each float field; `-0.0` vs `0.0` (and in `sum_pt`); padding-only; endianness-only; renamed view; shape; non-ndarray subclass; preprocess `n_selected`, `sum_pt` ULP, `pt_z` ULP; accepts identical copy | unit | `uv run --no-sync pytest tests/test_validate.py -q` | Wave 0 |
| all | Tracer: default config -> generate(tiny) -> hash -> record -> validate -> `sdplab --help` via installed package | integration | `uv run --no-sync pytest tests/test_tracer.py -q` | Wave 0 |
| D-14 | No timing calls or timing assertions in tests; no hard-coded SHA | meta | `uv run --no-sync pytest tests/test_repo_hygiene.py -q` | Wave 0 |

### What each key test must prove (kill conditions, with the mutation evidence)

| Test | Must fail if | Evidence |
|------|--------------|----------|
| `-0.0`, padding-only, endianness-only, renamed, shape/type tests in `test_validate.py` | validator is replaced by `np.array_equal` | Mutation run: 5 of 10 validate tests failed (`-0.0`, padding, endianness, renamed -> `TypeError`, shape/type) |
| `test_identity_hash_distinguishes_*` | hash omits dtype text, or omits shape | Mutation runs: each mutation fails exactly this test |
| `test_hash_distinguishes_packed_aligned`, `..._not_only_bytes` | canonical check removed from `array_sha256` | Mutation run: both fail |
| 1-ULP test | validator ignores low bits | Not killed by `array_equal` mutation (it also sees ULPs) - the test still guards tolerance-based variants (`np.allclose`); add a `np.allclose`-based mutation to the verification checklist |
| fresh-process test | RNG uses global state / hash seed / environment | Output compared across three processes with `PYTHONHASHSEED` 0, 1, random |
| config rejection table | a key is accepted that should be rejected, or the wrong key is named | 31 cases, each asserts `e.key` |

The verifier (plan "verify" step) should repeat the three mutation checks once on the real code (temporarily edit, run, revert) and record the output; they cost seconds.

### How to test "two fresh processes yield identical bytes"
Spawn `[sys.executable, "-I", "-c", code]` at least twice (the prototype uses three environments: `PYTHONHASHSEED` of `0`, `1`, `random`), with the code printing `array_sha256(generate(N, seed))` (optionally also `hashlib.sha256(a.tobytes())` as an independent digest), then compare against each other and against the in-parent computation. `-I` keeps the child independent of `PYTHONPATH` and user site, and the child imports the installed `sdplab`. Use a tiny `N` (2000 rows: three children cost about 0.2 s total). Never compare with a literal.

### Sampling Rate
- **Per task commit (the user commits; sample at task end):** `uv run --no-sync pytest -q -x <touched test file>` plus `ruff check` and `ruff format --check` (a few seconds).
- **Per wave:** full `uv run pytest`, plus the floors run on both Pythons, plus the local CI-parity loop.
- **Phase gate:** everything green on 3.12 and 3.13, `uv lock --check` and `uv sync --locked` pass, `git check-ignore` verification, mutation checks recorded, the CI file pinned, and (human) a green hosted run before `/gsd-verify-work`.

### Proving CI parity locally on 3.12 and 3.13 (commands that were run in the scratch project)

Hermetic variant (preferred when time allows): `uv python install 3.12 3.13` once, then prefix `UV_PYTHON_PREFERENCE=only-managed`. Environments are created **outside the repo** so `git status` stays clean (`.venv-*` is not covered by `.gitignore`, which only lists `.venv/`).

```bash
for v in 3.12 3.13; do
  export UV_PROJECT_ENVIRONMENT=/tmp/sdplab-ci-$v UV_PYTHON=$v
  uv sync --locked                    # fails if uv.lock is stale
  uv run --no-sync sdplab --help      # rc 0
  uv run --no-sync python -m sdplab --help
  uv run --no-sync ruff check
  uv run --no-sync ruff format --check
  uv run --no-sync pytest
done
unset UV_PROJECT_ENVIRONMENT UV_PYTHON
# Floors (wheels only; leaves uv.lock untouched - compare sha256sum uv.lock before/after):
for v in 3.12 3.13; do uv run --isolated --no-build --resolution lowest-direct --python $v pytest -q; done
```
Equivalent single-line alternative that also checks lock freshness: `uv run --isolated --locked --python $v ruff check` (ran on both). Record in the verification file: `sys.version`, `numpy.__version__`, `matplotlib.__version__` (print them with `uv run --no-sync python -c ...`), the sha256 of `uv.lock`, and the count of `numpy` entries in the lock.

### Wave 0 Gaps (everything; the repo has no code)
- [ ] `pyproject.toml`, `.python-version`, `uv.lock` (user commits), `src/sdplab/*`, `.github/workflows/ci.yml`
- [ ] Four `.gitkeep` files (`data/generated`, `results/raw`, `results/plots`, `results/reports`)
- [ ] `tests/conftest.py` (small-array and aligned-copy fixtures) and the test files in the table above
- [ ] Framework install: `uv sync --locked` after the first `uv lock`

## Security Domain

> `security_enforcement` is true in `.planning/config.json`; ASVS level 1, block on high.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No users or services |
| V3 Session Management | no | - |
| V4 Access Control | no | - (local single-user tool) |
| V5 Input Validation | yes | Hand-written type/range/enum/unknown-key validation of config (`ConfigError` naming the key); `bool`/`nan`/`inf`/date traps handled |
| V6 Cryptography | partly | SHA-256 via `hashlib` for integrity/identity only (not secrecy); no custom crypto; hash is domain-tagged (`sdplab-array-v1`) |
| V10/V14 Supply chain and build | yes | Locked deps with hashes in `uv.lock` (434 `sha256` entries in the throwaway lock); `uv sync --locked`; actions pinned by full SHA; `permissions: contents: read`; `persist-credentials: false`; legitimacy audit above |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Mutable action tag swapped upstream | Tampering | Full-SHA pin + version comment (verified SHAs) |
| Typosquatted/slopsquatted dependency | Tampering | Only user-confirmed packages; lock review checkpoint |
| Malformed or hostile TOML (type confusion, huge ints, `nan`) | Tampering / DoS | `tomllib` (no code execution); strict validators; `ConfigError` rather than a traceback |
| Config paths (`data_dir`, `results_dir`) pointing anywhere | Tampering | Out of scope in Phase 1 (config is trusted local input); path handling belongs to Phases 2-3 where files are written |
| Pickle deserialisation | Elevation | Not reachable in Phase 1; `allow_pickle=False` is a Phase 2 requirement (FMT-04) |
| Secrets in repo | Disclosure | `.gitignore` covers `.env*`, `*.pem`, `*.key`; no secrets in CI |

## Sources

### Primary (HIGH confidence)
- Local experiments listed in the provenance legend (throwaway projects under the session scratchpad: `p1`, `p1full`, `p1low`, `p1iso`, `p1raise`, `proto`, `ph1`, `pt`, `rufftest`, `bld`) - uv lock/sync/run/build, ruff, pytest strict mode, NumPy structured-array behaviour, generator and preprocess comparisons across NumPy 2.0.0/2.1.0/2.5.4.
- `git ls-remote --tags https://github.com/actions/checkout.git` and `https://github.com/astral-sh/setup-uv.git`; `api.github.com/repos/actions/checkout/git/ref/tags/v7.0.1` and `.../astral-sh/setup-uv/git/ref/tags/v10.3.0`; raw `action.yml` at both pinned SHAs; raw `README.md` of setup-uv at `1c37ad07...`.
- PyPI JSON API for numpy, matplotlib, pytest, ruff, uv_build (versions, `requires_python`, wheel tags, project URLs).
- Repo files read this session: `.planning/phases/01-foundation-dataset/01-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md`, `.planning/STATE.md`, `.planning/config.json`, `.claude/CLAUDE.md`, `.planning/research/PITFALLS.md`, `.planning/research/STACK.md` (reference config lines 70-200), `.planning/research/ARCHITECTURE.md` (grep), `docs/architecture/PROPOSAL.md` sections 6, 7, 10, 11, 12, `docs/adr/ADR-007/014/015/016.md`, `docs/research/research-notes.md` section 7, `.gitignore`.
- `git check-ignore` (read-only) on 25 paths (results in the FND-04 row of the requirements table).

### Secondary (MEDIUM confidence)
- https://numpy.org/doc/stable/reference/random/compatibility.html (fetched, summarised by the fetch tool; quoted statements about same-build/same-environment streams and block-size algorithms).
- https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.uniform.html (the `high` limit rounding note).
- https://numpy.org/doc/stable/reference/random/bit_generators/generated/numpy.random.SeedSequence.html (entropy must be non-negative; silent on cross-version stability).
- https://docs.github.com/en/actions/reference/runners/github-hosted-runners (`ubuntu-24.04` label).

### Tertiary (LOW confidence)
- None used for recommendations. Items resting only on inference are in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack and pyproject/lock behaviour: HIGH - executed on two Pythons with lowest-direct and highest resolutions.
- CI workflow: MEDIUM - actions and inputs verified, local equivalent verified, the hosted run itself unverified (A4).
- Identity/hash/validator design: HIGH - prototype plus mutation experiments.
- RNG determinism: MEDIUM - observed on three NumPy versions, no documented SeedSequence guarantee (A2).
- Config validation: HIGH - 31 cases on 3.12 and 3.13.
- Pitfalls: HIGH where marked experiment; MEDIUM for uv future-version behaviour (A5, A8).

**Research date:** 2026-10-13/14
**Valid until:** about 2026-11-13 for tool versions (uv, ruff, setup-uv move quickly; re-run `git ls-remote` and the PyPI queries when writing the workflow and lock); the structured-array findings stay valid until the NumPy minor changes.
