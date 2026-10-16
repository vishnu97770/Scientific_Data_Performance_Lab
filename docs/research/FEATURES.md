# Feature Research

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


> **Decision update (2026-10-13):** the user has since resolved the open items raised by this research. Python floor is now **>=3.12** (CI on 3.12 and 3.13; no 3.11 claim, ADR-015); ADR-005 is amended to store raw `ru_maxrss`, worker `VmHWM`/`VmRSS` and the parent's `ru_maxrss` at launch (the parent-floor effect was re-verified, research-notes section 7); `config_schema_version` and `results_schema_version` are separate (ADR-014); `timeout_s`, noise thresholds and `thread_env` are in the initial config (ADR-016); correctness is validated per operation (ADR-017). Where this file says otherwise it is superseded by `docs/architecture/PROPOSAL.md` (revision 3) and `docs/adr/`. Worker input, loop order and `prepare` vs timed `write` remain deferred to Phase 3 planning.


**Domain:** Small, reproducible benchmark tool for scientific-data file-format load/write performance (Python/NumPy, Linux-first, single developer)
**Researched:** 2026-10-13
**Confidence:** MEDIUM (see "Confidence and sourcing" at the end; the `classify-confidence` seam rates every provider used here, `webfetch`/`websearch`, as LOW unless cross-verified. Claims below are tagged MEDIUM only where two or more independent tools/sources agree, otherwise LOW.)

**Scope rule for this document.** `docs/architecture/PROPOSAL.md` sections 2, 3, 9 and 10 are the confirmed baseline (2026-10-13). This file classifies features; it does not expand scope. Every item is tagged:

- **MVP** = already in the confirmed minimum useful MVP (PROPOSAL section 2/3).
- **OPTIONAL** = already listed by the proposal as an optional extension (independent, not needed to finish the MVP).
- **DEFERRED** = surfaced by this research, not in the proposal, not in MVP. Listed so it is not silently added later.
- **DECISION** = a small gap or ambiguity found by comparing the proposal with peer tools; the user/planner must decide. Never counted in MVP until decided.

## Reference tools surveyed

| Tool | What it is | Why it is a relevant yardstick |
|------|-----------|-------------------------------|
| pyperf | Rigorous Python micro-benchmark harness (worker processes, JSON results, `check`/`stats`/`hist`/`compare_to`, `system tune`) | Methodology benchmark; the project borrows ideas but does not wrap it (proposal ADR-004, research-notes T3-T6) |
| asv (airspeed velocity) | Benchmark suites tracked over git history, JSON results per machine, static HTML publishing, `compare`, regression detection | Result-storage and reporting benchmark; SciPy/NumPy/pandas-scale tool, far larger than this project needs |
| pytest-benchmark | `benchmark` fixture; min/max/mean/stddev/median/IQR/outliers/OPS; `--benchmark-save/compare/json/histogram`; `--benchmark-compare-fail` | CLI/report conventions and the "stats columns" users expect |
| hyperfine | CLI wall-clock benchmarker: warmups, `--prepare` (cache control), outlier warnings, export to JSON/CSV/Markdown | Closest in spirit to "time an external process"; shows warm-vs-cold cache handled as an explicit, documented option |
| Published I/O format studies (e.g. arXiv 2207.09503 HDF5/Zarr/netCDF4; tick-data Parquet-vs-CSV paper; PandasFileFormatBenchmarking repo) | Format comparisons with configs, logged CSV results, medians over a few runs | Shows what typical format benchmarks do and, mostly, what they omit (see gaps) |

## Feature Landscape

### Table Stakes (Users Expect These)

A technical reviewer will mark the project as unserious if any of these is missing. Users do not give credit for them.

#### Methodology

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Process isolation per trial; timing taken inside the worker | pyperf runs benchmarks in worker processes; asv runs each benchmark in its own process; both exist to stop state leaking between measurements. MEDIUM (two tools agree) | MEDIUM | **MVP** (ADR-004). Also required for clean per-trial `ru_maxrss`. |
| Warm-up runs that are discarded but recorded as config | pyperf (one warm-up value per worker, discarded), asv (`warmup_time`), pytest-benchmark (`--benchmark-warmup`), hyperfine (`-w`), tick-data paper (1 warm-up). MEDIUM | LOW | **MVP** (`warmup_rounds = 2`). |
| Multiple measured repeats, all kept | Every surveyed tool repeats; pytest-benchmark `--benchmark-save-data` and pyperf `dump` exist precisely because users want the raw values | LOW | **MVP** (`measured_rounds = 7`, raw `trials.jsonl`). |
| Robust headline statistic with spread (median + IQR, plus min/max) | asv reports median and IQR; pytest-benchmark reports median and IQR columns; pyperf docs recommend median/MAD when results are unstable. MEDIUM | LOW | **MVP** (ADR-010). Mean/stdev may appear as secondary columns. |
| High-resolution monotonic clock, differences only | asv defaults to the highest-resolution timer; Python docs: only `perf_counter` differences are valid (research-notes T1) | LOW | **MVP** (`perf_counter_ns`). |
| Interleaved/shuffled ordering across repeated rounds | asv "rounds are interleaved so measurements span longer periods of background variation"; shuffled order with a recorded seed is the same idea made reproducible | LOW-MEDIUM | **MVP** (round-based, `order_seed`, realised order stored). |
| Explicit statement of cache state | hyperfine states warm cache by default and offers `--prepare` for cold; research-notes C1/C2 | LOW | **MVP** (warm-cache only, `cache_mode:"warm"` in every trial; README wording rules). Cold cache is **OPTIONAL**. |
| Failures and noisy trials recorded, not silently dropped | pyperf prints stability warnings and keeps all values; pyperf docs say to report outlier counts and percentile spread, not only one summary number. LOW-MEDIUM | LOW | **MVP** (`status`, `n_failed`, `n_incorrect`, flags not removal; no automatic outlier removal). |
| Separate measurement of fixed overhead (process start-up) | hyperfine `-S` subtracts shell start-up; this project instead reports start-up separately, which is the more transparent variant | LOW | **MVP** (`subprocess_wall_ns`, `startup_overhead_ns`). |
| Fair-comparison discipline: only compare what every contender supports | arXiv 2207.09503 states benchmarks "must only test features supported by all formats" | LOW (design) | **MVP** (shared `EVENT_DTYPE`; no mmap/partial reads; column-wise `.npz` kept out). |

#### Correctness (domain-specific table stakes for I/O benchmarks)

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Round-trip validation before any timing is trusted | Not offered by pyperf/asv/pytest-benchmark (they time arbitrary code) but a format benchmark without it can time a loader that returns wrong data; pandas docs show text float round-trip hazards (research-notes F4, gap 4) | MEDIUM (CSV float fidelity is the risk, R1) | **MVP** (exact-equality gate, pre-run + per-trial `correct`). |
| Deterministic, seeded dataset with content hash | Published suites generate or ship the dataset; reviewers need to know the input; N8 says seed alone is insufficient | LOW | **MVP** (`dataset_sha256`, NumPy version recorded). |
| Dataset generated outside the timers | Standard practice (setup vs timed region: asv `setup`, pytest-benchmark `pedantic` setup) | LOW | **MVP** (generation, hashing, JSON output, plotting excluded). |

#### Result storage

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Raw per-trial results persisted to a machine-readable file | pyperf JSON, asv JSON under `results/$MACHINE`, pytest-benchmark `--benchmark-json` with all timings, hyperfine JSON/CSV export, arXiv 2207.09503 CSV log. MEDIUM (four tools agree) | LOW-MEDIUM | **MVP** (`trials.jsonl`, append-safe). |
| Environment/machine metadata stored with results | pyperf `metadata`/`collect_metadata`; asv machine info (OS, arch, CPU, RAM) in `~/.asv-machine.json`; pytest-benchmark machine info. MEDIUM | MEDIUM | **MVP** (`run.json`: versions, OS/kernel, CPU, RAM, fs type, governor, load, git commit + dirty, config hash). |
| Schema/version marker; readers reject unknown versions | Needed once results are committed and re-read later; asv and pyperf both version their formats (pyperf `json2`) | LOW | **MVP** (`schema_version`). |
| Derived summary table separate from raw data | pytest-benchmark `compare`/`list`, pyperf `stats`/`show`, asv `publish`: summaries are always derived from stored raw results | LOW-MEDIUM | **MVP** (`summary.csv` regenerable from `trials.jsonl` + `run.json`). |
| Unique run identity and no overwriting of earlier runs | asv/pytest-benchmark keep numbered or timestamped runs | LOW | **MVP** (`results/raw/<run_id>/`). |

#### Reporting

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Per-cell table with n, median, spread, min/max | pytest-benchmark default table; pyperf `stats`; asv `compare` | LOW | **MVP** (`summary.csv`, markdown tables). |
| Cross-variant ratios against a stated baseline | hyperfine treats first command as baseline and prints relative speed; asv `compare` shows ratios | LOW | **MVP** (ratios of medians; baseline variant must be named in the report). |
| At least one time plot and one size plot | pytest-benchmark `--benchmark-histogram`; asv HTML graphs; format papers use bar charts | MEDIUM | **MVP** (load-time, file-size, load+preprocess plots). |
| Markdown report with caveats attached | hyperfine exports Markdown tables; reviewers read reports in GitHub | LOW-MEDIUM | **MVP** (always lists: synthetic data, one machine, warm cache, CPython+NumPy, not CERN-scale, laptop effects). |
| Stability/noise warning surfaced to the reader | pyperf "result may be unstable" warnings and `check`; hyperfine outlier warnings. MEDIUM | LOW-MEDIUM | **MVP** (flag, not remove: high load average, value >= k x cell median; shown in report). |

#### CLI

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Config-file-driven runs, with fail-fast validation | asv `asv.conf.json`; arXiv 2207.09503 YAML config; reviewers expect "no magic flags" | LOW-MEDIUM | **MVP** (versioned TOML, unknown keys / bad types / unknown formats rejected, key named). |
| Staged subcommands that can be re-run independently | pyperf: run then `show`/`stats`/`compare_to` on the stored file; asv: `run` / `publish` / `compare` | LOW | **MVP** (`info`, `prepare`, `validate`, `run`, `report`; `report --run <dir>` does not rerun anything). |
| Environment/capability inspection command | pyperf `system show`/`metadata`; asv machine info | LOW | **MVP** (`info`). |
| Non-zero exit and clear message on validation failure | Basic CLI hygiene; the gate must actually gate | LOW | **MVP** (implied by "abort: no timing accepted"; make exit codes an explicit requirement). |
| Pre-flight resource check (disk/RAM) with refusal | asv has `timeout` as its crude guard; with a ~29 GB-free laptop and a 10^6-row CSV this is more important here | LOW-MEDIUM | **MVP** (preflight; 10^7 behind `--allow-large` is **OPTIONAL**). |

#### Documentation and repo hygiene

| Feature | Why Expected | Complexity | Status / Notes |
|---------|--------------|------------|----------------|
| Documented methodology: what is timed, what is excluded, how many runs, what the statistic is | pyperf/asv docs; reviewers judge this first | MEDIUM | **MVP** (README + PROPOSAL section 9 distilled). |
| Honest, explicit limits (single machine, synthetic data, no universal-winner claims) | Format-comparison blog posts routinely overclaim; reviewers penalise it | LOW | **MVP** (project constraint "Honesty"). |
| Quickstart that works on a fresh clone | Every surveyed tool has a "run it in 5 minutes" path | LOW | **MVP** (`uv sync` + documented commands; acceptance criterion). |
| Every published number traceable to committed raw data | Not offered by most blog-style format benchmarks; the arXiv Parquet paper even omitted HDF5 because a dependency was missing, an example of a non-reproducible gap. LOW (single search result) | LOW | **MVP** (`results/examples/<run_id>/` committed; README numbers only from there). |
| Tests that never assert on timings; CI that does not run benchmarks | Standard for benchmark repos (timings are flaky) | LOW | **MVP** (pytest tiny-N + one smoke; Actions: sync, ruff, pytest). |
| Dependency pinning (lockfile) | Reproducibility baseline; asv builds isolated envs for the same reason | LOW | **MVP** (`uv.lock`). |

### Differentiators (Competitive Advantage)

These are not expected from a small benchmark repo, are aligned with the Core Value ("every reported number is trustworthy"), and are what a reviewer would remember. Almost all are already in the confirmed MVP; that is the point of the design.

| Feature | Value Proposition | Complexity | Status / Notes |
|---------|-------------------|------------|----------------|
| Per-trial correctness flag; incorrect trials excluded from accepted summaries but counted | pyperf/asv/pytest-benchmark time whatever the function returns; here wrong data cannot produce a headline number | MEDIUM | **MVP** (R8: read `ru_maxrss` before hashing; hash without copying). |
| Strict bit-exact contract (dtype, shape, bytes, SHA-256), changes only by ADR | Catches silent corruption incl. CSV float round-trip, which blog benchmarks never check | MEDIUM-HIGH (CSV `%.17g` + edge-value tests first) | **MVP** (ADR-007). Highest-risk differentiator (R1). |
| Raw `ru_maxrss` and post-import baseline stored separately; derived difference always labelled `estimated_workload_rss_kib` | Honest about what a high-water mark can and cannot show; most tools report one unqualified "peak memory" | LOW-MEDIUM | **MVP** (ADR-005). Memory *plots* beyond the minimum are **OPTIONAL**. |
| Logical-payload throughput and on-disk-file throughput reported in separate columns | Prevents the classic mistake of comparing MB/s with different numerators across formats | LOW | **MVP** (separate columns; the dedicated throughput plot beyond the minimum is **OPTIONAL**). |
| Start-up overhead reported separately and never mixed into operation timings | Makes the subprocess cost visible instead of hiding or silently subtracting it | LOW | **MVP**. |
| Summaries and plots regenerable from raw files alone | Reviewer can verify the pipeline from committed data without rerunning (asv only gets this with its own results tree; most scripts do not) | MEDIUM | **MVP**. |
| Dataset identity via SHA-256 + NumPy version; `validate` reports "dataset differs" instead of silently accepting | Directly addresses the no-cross-version-stream-guarantee fact (N8) | LOW | **MVP**. |
| Separate write/load/preprocess/load+preprocess operations to split parse vs raw-read vs decompress vs compute | Answers RQ2/RQ3 rather than reporting one opaque number | MEDIUM | **MVP**. |
| Explicitly labelled experimental variants (`--fsync`, column-wise `.npz`) never merged into baseline results | Keeps the main comparison format-only | LOW (policy) | **OPTIONAL** extensions; the *policy* is MVP documentation. |
| Per-run recorded system context (governor, load average before/after, power source, fs type) | pyperf documents these as noise sources but only tunes them (root); recording without changing the system suits an unprivileged laptop | MEDIUM | **MVP** (record, do not tune). |
| Curated tracked example run + README tables generated from it | "Show your data" credibility | LOW | **MVP** (Phase 5). |

### Anti-Features (Commonly Requested, Often Problematic)

Features that peer tools have or reviewers might suggest, which this project should explicitly not build.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Auto-calibrated inner loops / "number" per sample (pyperf `--loops`, asv `number`/`sample_time`, pytest-benchmark calibration) | Standard for micro-benchmarks; makes tiny operations measurable | Operations here are whole-file read/write; looping a load would test the warm page cache and repeated allocation, and defeat per-trial peak RSS and process isolation | One operation per fresh subprocess; document that the 10^4-row cells are short and noisier (see DECISION D1) |
| Regression gating / threshold failure (`--benchmark-compare-fail`, `asv continuous`) | Natural in CI | Proposal: benchmarks are not run in CI; timings are machine-dependent; single-machine laptop | Tests assert structure, validity, counts only |
| History across commits, dashboards, GitHub Pages publishing (asv `run` over revisions, `publish`, `gh-pages`) | "Professional" look | Different product (performance tracking of a code base); high maintenance; this project compares file formats, not code revisions | Committed `results/examples/<run_id>/` plus a markdown report and static plots |
| Statistical significance tests (pyperf `compare_to` uses a Student t-test) / bootstrap CIs | Looks rigorous | Proposal non-goal (ADR-010); assumptions are doubtful on noisy laptop timings; invites over-claiming | Median, IQR, min, max, counts; ratios of medians; explicit "no significance claims" |
| Mean +/- standard deviation as headline | pyperf and many tools default to it | Outlier-sensitive on an untuned laptop (pyperf's own docs recommend median/MAD when unstable) | Median + IQR headline; mean/stdev as secondary columns |
| Automatic outlier removal / trimming | Cleaner plots | Hides real variability, which is itself RQ5; destroys the "raw trials preserved" guarantee | Flag, count and show; never delete |
| System tuning commands (`pyperf system tune`, CPU isolation, governor changes, `drop_caches`) | Lower noise | Needs root / boot parameters, system-wide side effects, unportable; contradicts "does not change system settings" | Record governor/load/power; docs advise AC power and an idle machine |
| Wrapping or depending on pyperf, asv, pytest-benchmark, hyperfine | Reuse mature code | Constraint: no pyperf/psutil/typer/pandas in MVP; those tools target loops and code revisions, not isolated per-trial RSS and a correctness gate | Borrow methodology only; cite them in docs |
| Plugin/ABC architecture for formats | "Extensible" | One developer, four variants; adds abstraction without a second implementation (ADR-001) | Flat registry dict with `write(path, array)` / `load(path)` |
| Rich CLI framework (Typer/Click), YAML config, SQLite result store | Nicer UX / queryable | Extra dependencies; five subcommands do not need them (ADR-008/009) | `argparse`, TOML, JSONL; a flatten step for spreadsheets |
| "Winner" banners, universal rankings, or tables comparing to published numbers | Engaging README | Violates the honesty constraint; synthetic data, one machine, warm cache | Describe observed ratios for this run, with caveats; no claim of a universally fastest format |
| Additional formats / pandas loader / mmap / partial reads / parallel loading / missing values / real data / GUI in MVP | Obvious "what about Parquet/HDF5?" requests | Stated non-goals and deferrals; each changes the workload and fairness definition | Keep list in Optional/Deferred below; start only after the baseline is correct and useful |
| Cross-machine result aggregation or leaderboards | Appealing for a public project | Needs trusted metadata normalisation; out of scope for single-developer MVP | Document how to run locally; reviewers compare shape, not absolute numbers |
| Silently relaxed equality (`allclose`) for CSV | Makes failures disappear | Defeats the correctness contract | Investigate writer -> parser -> dtype; any tolerance requires an ADR |

## Feature Dependencies

```
Deterministic dataset (EVENT_DTYPE, seed, SHA-256)
    +--requires--> Config loading/validation (sizes, seed)
    +--requires--> Preflight (disk/RAM) for 10^6 rows (CSV is the big file)

Four format write/load paths (formats.py)
    +--requires--> Deterministic dataset
    +--requires--> Exact-equality validator (validate.py)   [CSV %.17g is the risk: R1]

Preprocess function (single, deterministic)
    +--requires--> Dataset (in-memory array)
    +--enhances--> load_preprocess operation; outputs must be identical across variants (validator)

Worker (timed op + perf_counter_ns + process_time + ru_maxrss + baseline)
    +--requires--> formats.py, preprocess.py, dataset.py
    +--requires--> Per-trial hash check (read ru_maxrss BEFORE hashing: R8)

Runner (warm-ups, shuffled rounds, order_seed, subprocess spawn, failure capture)
    +--requires--> Worker
    +--requires--> Pre-run validation PASS (gate: no timing accepted otherwise)
    +--requires--> Environment capture (run.json)
    +--requires--> results.py (JSONL append, schema_version)

Summaries (median/IQR/min/max/counts, flags, ratios, throughput columns)
    +--requires--> trials.jsonl + run.json only (no rerun)

Plots + markdown report (caveats always included)
    +--requires--> Summaries
    +--requires--> Committed example run for README numbers (Phase 5)

CLI (info, prepare, validate, run, report)
    +--requires--> all of the above, stage by stage
    +--enhances--> docs quickstart

Optional extensions (each independent)
    --fsync write experiment       --enhances--> write operation (separate result stream; conflicts with merging into default write)
    10^7 rows                      --requires--> --allow-large + preflight
    memory/throughput plots        --requires--> summaries (columns already in MVP)
    column-wise .npz               --conflicts--> "format-only" claim (must be labelled a layout study)
    csv_pandas / other formats     --requires--> working baseline + own correctness gate
    cold-cache protocol            --conflicts--> "unprivileged, portable" (needs privileged system-wide op)
```

### Dependency Notes

- **Validator before runner:** timings are only accepted after all variants pass exact equality, so Phase 2 (formats + round-trip, R1 resolved or escalated) must complete before Phase 3's runner can produce accepted data.
- **Worker before scheduler:** the shuffled-round scheduler and failure handling are meaningless until one isolated, timed, hashed trial works end to end.
- **Raw-store before summaries:** because summaries are derived-only, the JSONL/`run.json` schema (`schema_version`) must be frozen before analysis and report code is written, otherwise regeneration breaks.
- **R8 ordering constraint:** per-trial hash check must happen after `ru_maxrss` is read, else the correctness check inflates the memory number.
- **Throughput columns need both sizes:** `logical_bytes` and `file_bytes` must both be recorded per trial (they are in the proposed schema), otherwise the two throughput metrics cannot be regenerated.
- **Optional `--fsync` conflicts with default write results:** must be a separately named operation (`write_fsync`) to avoid mixed data.
- **Plots depend on a committed run:** README numbers/figures come from `results/examples/`, so the example-run curation step is the last dependency of Phase 5.

## MVP Definition

### Launch With (v1) -- the confirmed MVP (PROPOSAL section 2), mapped to the research

- [ ] Deterministic dataset (10^4/10^5/10^6, SHA-256 + NumPy version) -- table stakes
- [ ] Four variants of the same structured array with exact round-trip -- table stakes + differentiator (strict contract)
- [ ] Operations write / load / preprocess / load+preprocess; one documented preprocess -- differentiator (isolates parse vs compute)
- [ ] Subprocess-per-trial runner, 2 warm-ups, 7 rounds, seeded shuffled order, timing in worker, start-up separate -- table stakes (isolation, warm-up, repeats) + differentiator (start-up separation)
- [ ] Per-trial correctness flag and pre-run validation gate -- differentiator (core value)
- [ ] Memory: raw `ru_maxrss` + baseline, difference labelled estimate -- differentiator
- [ ] Logical vs file throughput in separate columns -- differentiator
- [ ] Versioned JSONL trials + `run.json`; `summary.csv` regenerable -- table stakes (raw data, metadata, versioning)
- [ ] Median/IQR/min/max/counts; ratios of medians; noise flags -- table stakes
- [ ] At least a load-time plot and file-size plot (+ load+preprocess per the phase outline) and markdown report with caveats -- table stakes
- [ ] argparse CLI (`info`, `prepare`, `validate`, `run`, `report`) + versioned TOML config + preflight -- table stakes
- [ ] pytest suite (no timing assertions), Ruff, GitHub Actions CI -- table stakes
- [ ] README with honest status, methodology, results only from a committed real run -- table stakes + differentiator

### Add After Validation (v1.x) -- the proposal's OPTIONAL extensions, each independent

- [ ] `--fsync` write experiment (separate `write_fsync` stream) -- trigger: baseline stable and reviewers ask "what about persistence?"
- [ ] 10^7-row stress size behind `--allow-large` + preflight -- trigger: 10^6 results are stable and disk allows
- [ ] Peak-memory and throughput plots beyond the minimum -- trigger: columns already present; plotting only
- [ ] float32 schema variant -- trigger: separate schema study
- [ ] Cold-cache protocol (system-wide, privileged, clearly separate) -- trigger: wanting a device-I/O study (R3)

### Future Consideration (v2+) -- optional/deferred, each its own study

- [ ] `csv_pandas` loader (ADR-013) -- separate loader study after baseline
- [ ] Column-wise `.npz` as a distinct storage-layout study (R5)
- [ ] Per-column projection
- [ ] JSON / HDF5 / Parquet / ROOT variants (note: any ROOT claim stays out of scope)
- [ ] **DEFERRED (new from this research):** `sdplab compare --run A --run B` that prints ratios between two stored runs without significance tests (pyperf `compare_to` / asv `compare` analogue); only after the baseline is reliable; worthwhile mainly to compare a run on different machines or NumPy versions.
- [ ] **DEFERRED (new):** per-trial distribution plot (strip/violin or text histogram, like `pyperf hist`) to show the 7 raw points per cell. A small variation of the required plots, but not in the confirmed list.
- [ ] **DEFERRED (new):** `sdplab check`-style stability report as a separate subcommand (currently the same information is a flag inside `report`).

### Decision flags (not in MVP until the user decides)

| ID | Observation (from peer tools) | Gap in the proposal | Suggested handling | Complexity |
|----|-------------------------------|---------------------|--------------------|------------|
| D1 | pyperf/asv loop short operations; here each trial is one call in a fresh process. At 10^4 rows, `preprocess` (and possibly `npy` load) can take roughly sub-millisecond to a few milliseconds (**unmeasured estimate**, assumption), where process-level noise is relatively large. | Proposal does not state how tiny cells are reported. | Keep one call per trial; state in README that small-size cells are noisy; use the IQR and `n` columns; no inner loops (anti-feature). Revisit only if measured IQR/median is large. | LOW (docs) |
| D2 | asv's tuning guidance asks users to set `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, `OMP_NUM_THREADS`; pyperf records many environment fields. | `run.json` field list does not mention thread-related environment variables or CPU affinity/`nproc` visible to the process. | Optionally record those env vars (if set) inside the existing environment capture; do not set or change them. Tiny addition within `results.py`; needs a user yes/no. | LOW |
| D3 | hyperfine and pyperf print an explicit warning when a result is unstable; pytest-benchmark reports an outliers column. | Proposal flags trials but does not define the threshold `k` or the load-average cutoff. | Define `k` and the load threshold in config (documented defaults) during Phase 3/4 planning, so flags are reproducible from stored data. | LOW |
| D4 | Most surveyed tools ship `--version` / `--help` / exit-code conventions; asv and pyperf treat bad input as non-zero exit. | Exit-code behaviour on gate failure, config error, partial failure (some trials failed) is unspecified. | Make "exit codes and error messages" an explicit requirement: 0 ok, non-zero on validation failure or config error; a run with failed trials returns a documented code but still writes results. | LOW |
| D5 | Peer tools document a reduced-effort path (hyperfine `-r`, asv `--quick`). | Proposal has a tiny-N integration test but no student-facing "quick" config/command. | Ship a small example TOML (e.g. sizes = [1000, 10000], 1 warm-up, 3 rounds) documented as a smoke/demo config. Config only, no new code path. | LOW |

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Exact-equality gate + CSV `%.17g` round-trip (pre-run and per-trial) | HIGH | MEDIUM-HIGH | P1 |
| Subprocess-per-trial worker with in-worker timing | HIGH | MEDIUM | P1 |
| Raw JSONL + `run.json` + `schema_version` | HIGH | MEDIUM | P1 |
| Warm-ups, repeats, shuffled order, recorded seed/order | HIGH | LOW-MEDIUM | P1 |
| Deterministic dataset + SHA-256 + NumPy version | HIGH | LOW | P1 |
| Median/IQR/min/max/counts; ratios of medians | HIGH | LOW | P1 |
| Summaries/plots/report regenerable from raw files | HIGH | MEDIUM | P1 |
| Environment capture (versions, kernel, CPU, governor, load, git dirty) | HIGH | MEDIUM | P1 |
| Config validation (fail-fast, named key) + preflight | MEDIUM | LOW-MEDIUM | P1 |
| README with honest caveats, results only from committed run | HIGH | LOW-MEDIUM | P1 |
| pytest (no timing asserts) + Ruff + Actions CI | MEDIUM | LOW | P1 |
| Memory estimate labelling, throughput split, start-up split | MEDIUM-HIGH | LOW | P1 (data in MVP) |
| Noise flags with documented thresholds (D3) | MEDIUM | LOW | P1 |
| Exit-code requirements (D4), quick demo config (D5), env-var recording (D2) | LOW-MEDIUM | LOW | P2 pending decision |
| Load-time, file-size, load+preprocess plots | HIGH | MEDIUM | P1 |
| Memory and throughput plots beyond minimum | MEDIUM | LOW | P3 (OPTIONAL) |
| `--fsync`, 10^7 rows, float32, cold cache | MEDIUM | LOW-HIGH | P3 (OPTIONAL) |
| csv_pandas, column-wise npz, projection, other formats | MEDIUM | MEDIUM-HIGH | P3 (OPTIONAL, separate studies) |
| Run-vs-run `compare`, per-trial distribution plot, separate `check` | LOW-MEDIUM | LOW-MEDIUM | P3 (DEFERRED) |

**Priority key:** P1 must have for launch; P2 should have when decided; P3 future consideration.

## Competitor Feature Analysis

| Feature | pyperf | asv | pytest-benchmark | hyperfine | Format-benchmark papers/repos | Our Approach |
|---------|--------|-----|------------------|-----------|-------------------------------|--------------|
| Process isolation | Separate worker processes (calibration run + N workers) | Each benchmark in its own process | In-process (pytest) | Each run is a process | Usually in-process loops | One fresh subprocess per trial; timer inside worker |
| Warm-up | One discarded value per worker, `-w` | `warmup_time` (default 0.1 s) | `--benchmark-warmup` (default on PyPy only) | `-w` | Often 1 warm-up discarded | `warmup_rounds = 2`, whole-process |
| Repeats | `-p` processes x `-n` values | `repeat`, `rounds` (default 2), interleaved | rounds from calibration | `-r`, min 10 / ~3 s | Median of ~5 | 7 rounds, every cell once per round, shuffled |
| Headline statistic | Mean +/- std (median/MAD recommended if unstable) | Median (+ IQR) | min/max/mean/stddev/median/IQR/outliers/OPS | Mean, min/max; relative speed | Median or mean | Median + IQR; min/max/mean/stdev secondary |
| Significance testing | Student t-test in `compare_to` | Statistical regression detection | None built-in (threshold gating) | Relative speed only | None | None (non-goal) |
| Raw data kept | JSON incl. all values, `dump` | JSON per machine | `--benchmark-json` (all timings), `--benchmark-save-data` | JSON/CSV export | Rarely | `trials.jsonl`, always, incl. failures |
| Environment metadata | `collect_metadata`/`metadata` | machine file (OS, arch, CPU, RAM) | Recorded in saved JSON (field list not verified here) | Not a focus | Rarely complete | `run.json` with versions, kernel, CPU, governor, load, git dirty, config hash, dataset hash |
| Cache control | n/a | n/a | n/a | `--prepare` (e.g. drop caches) | Rarely stated | Warm only, explicit; cold = optional extension |
| Memory | `--track-memory` (psutil on macOS) | `peakmem_*`, `mem_*` | None | Peak RSS metric | Rare | `ru_maxrss` + baseline stored separately; difference an estimate |
| Correctness check of benchmarked output | None | None | None | None | Rare | Pre-run gate + per-trial flag (differentiator) |
| Reporting | `show`, `stats`, `hist`, `compare_to --table` | `compare`, `publish` HTML | table, histogram SVG, `compare` | Markdown/CSV/JSON export | Tables, bar charts | `summary.csv`, plots, markdown report with caveats |
| System tuning | `system tune` (root) | pointers + `--cpu-affinity` | None | None | None | Record only; docs advise AC power/idle machine |
| History / regression tracking | No | Yes (core) | Save/compare, `--benchmark-compare-fail` | No | No | No (anti-feature) |

## Confidence and sourcing

| Claim group | Tier | Basis |
|-------------|------|-------|
| pyperf worker processes, warm-up, JSON, stats, compare_to t-test, median/MAD advice, CLI list | MEDIUM | pyperf docs pages fetched (run_benchmark, cli, analyze) and consistent with `docs/research/research-notes.md` T3-T6. Seam rates `webfetch` LOW; promoted because it matches an independent earlier fetch plus peer tools. |
| asv process-per-benchmark, median + IQR, interleaved rounds, JSON per machine, `compare`/`publish`/regressions, `peakmem`, tuning guidance | MEDIUM | asv docs pages (using, benchmarks, tuning) fetched; agree with pyperf on isolation and noise advice. Some details (`continuous`, params) were not on the fetched pages. |
| pytest-benchmark columns, save/compare/json/histogram/compare-fail | LOW-MEDIUM | Docs usage page (readthedocs and raw source) fetched; the pages did **not** state `machine_info`/`commit_info` or the JSON schema, so the "machine info recorded" claim in the comparison table is unverified. |
| hyperfine warm-up, `--prepare`, outlier warnings, export formats, memory metric | MEDIUM | GitHub README fetched; consistent with the "explicit cache state" practice. |
| Published format-benchmark practices (config + CSV logging; median of ~5 runs with one warm-up; supported-features-only fairness; omitted-dependency gap) | LOW | Single `websearch` result summary of arXiv/blog sources; not fetched in full. Treat as illustrative; reviewers' expectations here are inferred, not surveyed. |
| Classification of every feature as MVP/OPTIONAL | HIGH | Direct reading of PROPOSAL sections 2, 3, 9, 10 and PROJECT.md. |
| D1 (small-size cells are noisy) | LOW | Assumption: not measured; resolve empirically in Phase 3/4 runs. |

## Sources

- `docs/architecture/PROPOSAL.md` (sections 2, 3, 9, 10, 15): confirmed baseline.
- `docs/research/research-notes.md` (T1-T6, M1-M4, C1-C2, F4, gaps): reused, not re-verified.
- pyperf documentation: https://pyperf.readthedocs.io/en/latest/run_benchmark.html, https://pyperf.readthedocs.io/en/latest/cli.html, https://pyperf.readthedocs.io/en/latest/analyze.html
- asv documentation: https://asv.readthedocs.io/en/stable/using.html, https://asv.readthedocs.io/en/stable/benchmarks.html, https://asv.readthedocs.io/en/stable/tuning.html
- pytest-benchmark documentation: https://pytest-benchmark.readthedocs.io/en/stable/usage.html and https://raw.githubusercontent.com/ionelmc/pytest-benchmark/master/docs/usage.rst
- hyperfine README: https://github.com/sharkdp/hyperfine
- A Comparison of HDF5, Zarr, and netCDF4 in Performing Common I/O Operations: https://arxiv.org/pdf/2207.09503 (known only via a search summary)
- Parquet-vs-CSV tick-data paper (https://arxiv.org/pdf/2608.23053) and the PandasFileFormatBenchmarking repository (via https://redirect.github.com/jaagut/PandasFileFormatBenchmarking): known only via a search summary; used as illustrative, LOW confidence.

---
*Feature research for: reproducible scientific-data file-format performance benchmark (sdplab)*
*Researched: 2026-10-13*
