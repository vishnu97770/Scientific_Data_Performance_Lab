# Requirements: Scientific Data Performance Lab

**Defined:** 2026-10-13
**Core Value:** Every reported number is trustworthy: each timing comes from a correctness-validated, fully documented, reproducible experiment whose raw trials, software versions and dataset hash are preserved.

Source of truth for scope: `docs/architecture/PROPOSAL.md` (revision 2, confirmed). The open decisions of the first draft were resolved by the user on 2026-10-13 (see "Decisions" at the end); only the Phase 3 design items remain deferred.

A requirement is **Complete** only when implemented, tested, verified and (by the user) committed. As of 2026-10-15 36 of 38 are *Verified locally* (evidence: `docs/verification-log.md`), none is committed, and the checkboxes below stay unchecked until the user commits. Writing it down is not completion.

## v1 Requirements

### Foundation (FND)

- [ ] **FND-01**: A fresh clone runs `uv sync --locked` and then `uv run sdplab --help` successfully on Python 3.12 and 3.13 (package `sdplab`, `requires-python = ">=3.12"`, src layout, committed lockfile that resolves a single NumPy version; no claim of Python 3.11 support).
- [ ] **FND-02**: `uv run ruff check`, `uv run ruff format --check` and `uv run pytest` pass locally on Python 3.13, and the same three run in a GitHub Actions workflow on Ubuntu with a Python 3.12 and a 3.13 job (actions pinned by commit SHA; benchmarks are never run in CI).
- [ ] **FND-03**: A TOML config loads through `tomllib` and carries its own `config_schema_version`. The initial key set is complete — `[dataset]`, `[formats]`, `[workload]`, `[trials]` (including `timeout_s`), `[noise]` (`outlier_factor`, `max_load_per_core`), `[environment]` (`thread_env`), `[output]` — and validation checks types, ranges (e.g. `timeout_s > 0`, `outlier_factor > 1`, `max_load_per_core >= 0`, sizes > 0), enum values and unknown keys at every level, failing fast with a message naming the offending key.
- [ ] **FND-04**: The `.gitignore` ignores local Claude Code settings (`.claude/settings.local.json`), `.venv/`, `data/generated/` and `results/raw|plots|reports/` (with `.gitkeep` exceptions) — already applied; verified by `git check-ignore`.

### Dataset and validation (DAT)

- [ ] **DAT-01**: `EVENT_DTYPE` (`<i8` event_id, `<f8` pt/eta/phi, `<i2` category_code, packed, 34 B/row) generates a 1-D C-contiguous structured array of N rows from a seed; the same seed in the same environment yields byte-identical arrays, and pt>0, |eta|<=2.5, phi in [-pi, pi) hold.
- [ ] **DAT-02**: The dataset identity hash covers dtype description, shape and bytes (not bytes alone); tests demonstrate it distinguishes packed vs aligned dtype and little- vs big-endian data, and no test hard-codes an expected SHA-256 value.
- [ ] **DAT-03**: Run metadata records the seed, NumPy version and dataset hash, and `validate` reports "dataset differs" when a regenerated hash does not match a recorded one.
- [ ] **DAT-04**: One deterministic preprocessing function (`pt > pt_cut` and `|eta| < eta_cut` selection, `n_selected`, `sum(pt[mask])`, z-scored pt) has known-answer tests and produces bit-identical outputs for bit-identical inputs.
- [ ] **DAT-05**: The validator requires identical dtype, shape and bytes/hash for every loaded array plus identical preprocess outputs; a test that perturbs one value by 1 ULP, a test that changes only `-0.0` vs `0.0`, and a test that changes only padding/endianness are all rejected.

### Format variants (FMT)

- [ ] **FMT-01**: Each of `csv`, `npy`, `npz`, `npz_compressed` writes the structured array to disk and loads it back as a structured array of `EVENT_DTYPE` that passes DAT-05 at 10^3, 10^4, 10^5 and 10^6 rows.
- [ ] **FMT-02**: CSV uses `%.17g` for float64 and integer formatting for integer fields, explicit dtypes on load, and an explicit one-row-header contract; edge-value tests (subnormals, `-0.0`, extreme exponents, int64 beyond 2^53, 1-row and empty files) pass bit-exactly or the failure is investigated and documented (writer, parser, schema) before any change to the representation or comparison policy.
- [ ] **FMT-03**: The `.npz` variants store exactly one member named `events`, never pass `allow_pickle` to `savez`, and the loader materializes and returns a plain ndarray and closes the archive.
- [ ] **FMT-04**: Loading uses `allow_pickle=False` everywhere; a test confirms an object-dtype file is rejected.
- [ ] **FMT-05**: Documented representation/loader differences (text vs binary, header, zip framing, DEFLATE, copies per loader) appear in the README and are not hidden in code comments only.

### Measurement and runner (RUN)

- [ ] **RUN-01**: A worker process (`python -m sdplab.worker`) executes one timed operation (write, load, preprocess, load_preprocess) with `time.perf_counter_ns()` inside the process around only that operation, plus `process_time_ns`, and emits exactly one JSON line; a contract test and fault-injection tests (non-zero exit, timeout, garbage stdout, killed child) are recorded as failed trials, not crashes.
- [ ] **RUN-02**: The runner executes every trial, including warm-ups, in a fresh subprocess, with `warmup_rounds` (default 2) discarded from results and `measured_rounds` (default 7) kept; each round runs every (variant, operation) cell once in an order shuffled by `order_seed`, and the realised order is stored.
- [ ] **RUN-03**: Pre-run validation passes for all variants before any trial is scheduled; a mismatch aborts with a non-zero exit and no timing is accepted.
- [ ] **RUN-04**: For every operation, after the timed region and after memory counters are read, the worker verifies its output where applicable and records `correct` and `correctness_check`: `load` (hash of loaded array), `preprocess` (digest of outputs), `load_preprocess` (both), `write` (written scratch file read back by an untimed reference loader and hashed). A check that cannot apply is recorded as `not_applicable`, never as passed. Incorrect trials are counted and excluded from accepted summaries but remain in the raw file. (How the worker obtains its input and expected values is decided in Phase 3 planning.)
- [ ] **RUN-05**: Memory: the worker stores, as separate raw fields, `ru_maxrss_kib`, `vm_hwm_kib`, and `vm_rss_baseline_kib` (VmRSS after imports, before the operation); the runner stores `parent_ru_maxrss_kib_at_launch` per spawn. A trial is flagged `maxrss_floor_suspect` when `ru_maxrss` does not exceed the parent's launch value. Any difference such as `vm_hwm - vm_rss_baseline` is exposed only as `estimated_workload_rss_kib`, labelled an estimate. A pytest reproduces the parent-peak inheritance effect with a large margin (not exact numbers), and the README documents units (KiB), the inheritance effect and the Linux-only limitations.
- [ ] **RUN-06**: Write trials target scratch paths, never the canonical variant files; a failed or partial write cannot affect later load trials.
- [ ] **RUN-07**: Pre-flight estimates RAM and disk per size and refuses sizes that do not fit; 10^7 rows additionally requires `--allow-large`.
- [ ] **RUN-08**: Cache mode is recorded as `warm` in every trial and in the report; no code or documentation describes a process restart as clearing the OS page cache.
- [ ] **RUN-09**: Process start-up cost is recorded as `subprocess_wall_ns` and reported separately; it is never added to operation timings.
- [ ] **RUN-10**: Environment capture records Python/NumPy/matplotlib versions, OS/kernel, CPU model (from `/proc/cpuinfo`), core count, RAM, data-dir filesystem type and path, CPU governor, load average before/after, power source if readable, git commit and dirty flag, config hash, seed and dataset hash, and the thread-related environment variables (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `NUMEXPR_NUM_THREADS`) as set in the worker. With `thread_env = "inherit"` (default) the environment is not modified; with `"single"` the worker environment sets all four to 1. Missing sysfs files are tolerated and recorded as unavailable. The run warns when `data_dir` is on tmpfs.

### Results and analysis (RES)

- [ ] **RES-01**: Each line of `trials.jsonl` is an independently parseable JSON object carrying `results_schema_version`, run id, variant, operation, dataset configuration, round/position/phase, status, `correct`, `correctness_check`, timings, resource metrics (`ru_maxrss_kib`, `vm_hwm_kib`, `vm_rss_baseline_kib`, `parent_ru_maxrss_kib_at_launch`), flags, sizes and measurement configuration; `run.json` holds environment, config, per-size dataset hashes and file sizes.
- [ ] **RES-02**: The result schema counter (`results_schema_version`) is separate from the config counter (`config_schema_version`); each reader rejects an unknown value of its own counter; golden-file tests load a frozen sample of each; NaN is never emitted into JSON (`allow_nan=False`).
- [ ] **RES-03**: A truncated final JSONL line (interrupted run) is detected and handled by a documented rule; `run.json` records run status.
- [ ] **RES-04**: `summary.csv` is derived from `trials.jsonl` + `run.json` only — `sdplab report --run <dir>` regenerates it without rerunning; it contains per (variant, size, operation): n_ok, n_failed, n_incorrect, median, Q1, Q3, IQR (quantile method named), min, max, mean, stdev; all-failed cells still appear.
- [ ] **RES-05**: Logical-payload throughput (`N x 34 / elapsed`) and on-disk-file throughput (`file_bytes / elapsed`) are separate columns and separate plots, never combined.
- [ ] **RES-06**: Trials are flagged — never removed or silently excluded — when the 1-minute load average per core exceeds `noise.max_load_per_core` before or after the trial, or a value is at least `noise.outlier_factor` times the cell median. Thresholds are validated config values with documented defaults (proposed: 3.0 and 0.5). Every raw observation stays in `trials.jsonl`; flags appear in the record and the summary. No significance claims.
- [ ] **RES-07**: At minimum, plots of file size, load time and load+preprocess time per variant and size are produced by `report` (matplotlib imported only there, `Agg` backend), and a markdown report always includes the caveat block (synthetic data, one machine, warm cache, CPython+NumPy, not CERN-scale, power/thermal effects).

### CLI and documentation (CLI/DOC)

- [ ] **CLI-01**: `sdplab info`, `prepare`, `validate`, `run` and `report` exist as argparse subcommands with documented exit codes (proposed: 0 success, 1 internal error, 2 usage/config error, 3 correctness gate failed, 4 run completed with failed/timed-out/incorrect trials, 5 pre-flight refused), listed in `--help` and the README and covered by tests.
- [ ] **CLI-02**: A working example config (`configs/example.toml`) for a quick local run ships with the repo (configuration only, no extra code path) and is loaded and validated by a test.
- [ ] **DOC-01**: The README is merged from the committed 823-line draft: status vocabulary (planned / implemented / tested / verified), result formats updated to JSONL, methodology, differences between variants, limitations and CERN non-affiliation statement preserved.
- [ ] **DOC-02**: Every number in the README comes from a committed example run (`results/examples/<run_id>/` with `run.json` and `trials.jsonl`), checked by a script or test; no result claims exist before such a run is produced.
- [ ] **DOC-03**: Formal ADR files (001–013 plus any approved amendments) exist under `docs/adr/` and are consistent with README, requirements and roadmap.
- [ ] **DOC-04**: CI, link and Mermaid-fence checks pass, and the finished MVP is verified against the acceptance criteria in PROPOSAL section 12 with evidence recorded in the phase verification file.

### Testing (TST)

- [ ] **TST-01**: The pytest suite runs in seconds on tiny datasets, asserts structure/validity/counts and never asserts on timing values, and an end-to-end smoke test (`prepare -> validate -> run -> report`, 1 000 rows, 1 warm-up, 2 trials) passes in under 30 s.

## v2 Requirements (optional extensions — not in the MVP)

- **EXT-01**: `--fsync` write experiment as a separate, labelled operation.
- **EXT-02**: 10^7-row stress size.
- **EXT-03**: Additional memory and throughput plots; run-vs-run `compare`.
- **EXT-04**: `csv_pandas` loader study.
- **EXT-05**: Column-wise `.npz` storage-layout study; float32 schema.
- **EXT-06**: JSON, HDF5, Parquet, ROOT variants; cold-cache protocol.

## Out of Scope

| Feature | Reason |
|---------|--------|
| Missing values, real experiment data | MVP uses a clean synthetic workload |
| mmap/streaming/partial/column reads | Different workloads; reported separately if ever added |
| Parallel/distributed loading | Not needed for the research questions |
| Significance tests, regression gating, dashboards | Invented rigor; peer-tool features outside scope |
| Wrapping pyperf/asv/pytest-benchmark; plugin/ABC architecture; YAML/SQLite | Unneeded complexity for one developer |
| Any CERN endorsement or ROOT performance claim | Independent educational project |
| Project 2 | Deferred until Project 1 is implemented, tested, documented and reliable |

## Traceability

Which phases cover which requirements. Each v1 requirement maps to exactly one milestone-phase (the five phases of `docs/architecture/PROPOSAL.md` section 16). Cross-cutting items (CLI-01, TST-01, DOC-03, FMT-05, DAT-03) belong to the phase where they are finally verifiable.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FND-01 | Phase 1 | Verified locally |
| FND-02 | Phase 1 | Implemented; local checks pass, hosted CI not run |
| FND-03 | Phase 1 | Verified locally |
| FND-04 | Phase 1 | Verified locally |
| DAT-01 | Phase 1 | Verified locally |
| DAT-02 | Phase 1 | Verified locally |
| DAT-03 | Phase 1 | Verified locally |
| DAT-04 | Phase 1 | Verified locally |
| DAT-05 | Phase 1 | Verified locally |
| FMT-01 | Phase 2 | Verified locally |
| FMT-02 | Phase 2 | Verified locally |
| FMT-03 | Phase 2 | Verified locally |
| FMT-04 | Phase 2 | Verified locally |
| FMT-05 | Phase 2 | Verified locally |
| RUN-01 | Phase 3 | Verified locally |
| RUN-02 | Phase 3 | Verified locally |
| RUN-03 | Phase 3 | Verified locally |
| RUN-04 | Phase 3 | Verified locally |
| RUN-05 | Phase 3 | Verified locally |
| RUN-06 | Phase 3 | Verified locally |
| RUN-07 | Phase 3 | Verified locally |
| RUN-08 | Phase 3 | Verified locally |
| RUN-09 | Phase 3 | Verified locally |
| RUN-10 | Phase 3 | Verified locally |
| RES-01 | Phase 3 | Verified locally |
| RES-02 | Phase 3 | Verified locally |
| RES-03 | Phase 3 | Verified locally |
| RES-04 | Phase 4 | Verified locally |
| RES-05 | Phase 4 | Verified locally |
| RES-06 | Phase 4 | Verified locally |
| RES-07 | Phase 4 | Verified locally |
| CLI-01 | Phase 4 | Verified locally |
| CLI-02 | Phase 4 | Verified locally |
| TST-01 | Phase 4 | Verified locally |
| DOC-01 | Phase 5 | Verified locally |
| DOC-02 | Phase 5 | Verified locally |
| DOC-03 | Phase 5 | Verified locally |
| DOC-04 | Phase 5 | Partly done: docs checks pass (tests/test_docs.py); hosted CI and final sign-off pending |

**Coverage:**
- v1 requirements: 38 total
- Mapped to phases: 38 (Phase 1: 9, Phase 2: 5, Phase 3: 13, Phase 4: 7, Phase 5: 4)
- Unmapped: 0
- Duplicates (requirement in more than one phase): 0

## Decisions (resolved 2026-10-13) and items still deferred

| ID | Decision | Status |
|----|----------|--------|
| OD-1 | Amend ADR-005: add worker `VmHWM`/`VmRSS` and parent `ru_maxrss` at launch; keep raw `ru_maxrss`; verify by experiment; document units, inheritance and limits; never call baseline subtraction exact | **Approved** (RUN-05, RES-01); experiment recorded in `docs/research/research-notes.md` section 7 |
| OD-2/4 | Separate `config_schema_version` and `results_schema_version` | **Approved** (FND-03, RES-02; ADR-014) |
| OD-3/5 | Minimum Python 3.12, primary 3.13, CI on 3.12 and 3.13, no 3.11 claim; verify `uv.lock` | **Approved** (FND-01, FND-02; ADR-015); throwaway `uv lock` resolved a single NumPy 2.5.4; real project lock verified in Phase 1 |
| OD-6 | `timeout_s` and noise-flag thresholds in the initial config schema, with type/range/unknown-key validation | **Approved** (FND-03; ADR-016) |
| D2-D5 | Thread env controls + metadata, documented exit codes, working example config, explicit noise thresholds; preserve every raw observation | **Approved** (RUN-10, RES-06, CLI-01, CLI-02) |
| Correctness scope | Every operation validates its output where applicable | **Approved** (RUN-04; ADR-017) |
| Worker input design (write/preprocess), loop order, timed `write` vs untimed `prepare` | **Deferred to Phase 3 planning** by the user | Open |

---
*Requirements defined: 2026-10-13*
*Last updated: 2026-10-13 after roadmap creation (traceability and coverage filled; requirement text and open decisions unchanged)*
