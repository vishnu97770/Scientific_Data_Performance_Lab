# Architecture Research

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


> **Decision update (2026-10-13):** the user has since resolved the open items raised by this research. Python floor is now **>=3.12** (CI on 3.12 and 3.13; no 3.11 claim, ADR-015); ADR-005 is amended to store raw `ru_maxrss`, worker `VmHWM`/`VmRSS` and the parent's `ru_maxrss` at launch (the parent-floor effect was re-verified, research-notes section 7); `config_schema_version` and `results_schema_version` are separate (ADR-014); `timeout_s`, noise thresholds and `thread_env` are in the initial config (ADR-016); correctness is validated per operation (ADR-017). Where this file says otherwise it is superseded by `docs/architecture/PROPOSAL.md` (revision 3) and `docs/adr/`. Worker input, loop order and `prepare` vs timed `write` remain deferred to Phase 3 planning.


**Domain:** Small, reproducible scientific-data I/O benchmark harness (Python, NumPy, subprocess-per-trial)
**Researched:** 2026-10-13
**Confidence:** HIGH on structure and build order (derived directly from the CONFIRMED PROPOSAL.md); HIGH on the two empirically checked risks (S1, S2: observed locally); MEDIUM on kernel-mechanism explanations and on "typical harness" comparisons (not read from primary sources in depth).

**Scope of this document.** The architecture in `docs/architecture/PROPOSAL.md` (revision 2, CONFIRMED) is taken as given. This file reports (a) the component boundaries and data flow as built, (b) the build order the dependencies impose, and (c) structural risks found. It does not propose a different architecture. Where a risk needs a remedy, the remedy stays inside the confirmed module set and dependency rules, or is flagged as an ADR amendment the roadmap must schedule.

---

## (a) Component Boundaries and Data Flow as Built

### How this matches typical small benchmark harnesses

Small harnesses (pyperf, asv, pytest-benchmark, hand-rolled I/O benchmarks) share one shape: a **driver** that owns scheduling and persistence, a **worker** that owns the timed region, a **raw-record store** that is append-only, and a **derivation layer** (stats, plots) that reads only the stored records. The confirmed design is that shape with three additions that fit a correctness-first goal: a hard validation gate before any timing, per-trial correctness hashing, and a CSV/NPY/NPZ format registry. Nothing in the module list is unusual; the unusual part is the discipline in the contracts between modules (below). (MEDIUM: from general knowledge of those tools, and from the pyperf worker-process model noted in research-notes T6.)

### System overview (as confirmed)

```
                              cli.py  (argparse: info, prepare, validate, run, report)
                                 |
        +------------+-----------+-------------+--------------+
        |            |                         |              |
    config.py     runner.py                analysis.py     report.py   (only matplotlib importer)
   (TOML, schema)    |   \                       |              |
                     |    \--- preflight         |              |
        +------------+-----------+               |              |
        |            |           |               |              |
   dataset.py   formats.py   validate.py          +------+-------+
   (dtype,gen,  (4 variants, (exact equality)            |
    sha256)      registry)        |                  results.py
        ^            ^            v           (records, JSONL, run.json, env capture)
        |            |        dataset.py              ^
        |            |                                 |
        |   subprocess boundary (argv/JSON in, ONE JSON line out)
        |            |                                 |
        +-------- worker.py  ---> preprocess.py        |
          (timed op + RSS + per-trial hash)             |
                     |                                  |
                     +--- result line parsed by runner -+  (runner persists via results.py)
```

### Component responsibilities

| Component | Owns | Must not do | Talks to |
|-----------|------|-------------|----------|
| `config.py` | TOML parse (only module reading TOML), schema_version, defaults, fail-fast on unknown keys/types | Touch the filesystem for data; know about trials | cli, runner |
| `dataset.py` | `EVENT_DTYPE`, `DatasetSpec`, seeded `generate()`, `array_sha256()` | Import anything from the package | formats, validate, worker, runner |
| `formats.py` | `write(path, array)` / `load(path) -> array` per variant, registry dict | Time anything; validate; subclass hierarchies | worker (timed), runner (untimed prepare/validate) |
| `preprocess.py` | The single workload function (mask, `sum(pt)`, z-scored `pt`) | Read config; know variants | worker, runner/validate (known-answer, cross-variant check) |
| `validate.py` | Exact equality: dtype, shape, bytes/SHA-256, preprocess outputs; rejects 1-ULP change | Timing; spawn processes | runner |
| `worker.py` | One timed operation in a fresh process; `perf_counter_ns` + `process_time_ns`; RSS samples; per-trial hash; ONE JSON line to stdout | Read TOML; write result files; know about rounds/order | formats, preprocess, dataset; parent via subprocess pipe only |
| `runner.py` | Preflight, scheduling (warm-up + shuffled measured rounds), spawn/timeout/collect, failure-to-record conversion, persistence calls | Compute statistics; import matplotlib | config, dataset, formats, validate, results; worker only via `subprocess` |
| `results.py` | Trial/run record dataclasses, JSONL append, `run.json`, environment capture, schema_version enforcement | Compute statistics | runner (write), analysis, report (read) |
| `analysis.py` | Summary statistics (median/IQR etc.), gate on `correct` and status, noise flags | Rerun anything; import matplotlib | results |
| `report.py` | Plots + markdown with mandatory caveats | Be imported by anything but `cli` | analysis |
| `cli.py` | argparse subcommands, user-facing errors | Contain logic; be imported | runner, analysis, report, config |

### Data flow (direction explicit)

```
config.toml --config.py--> Config
Config --dataset.generate(seed,N)--> canonical structured array (parent, in memory)
canonical array --formats.write--> variant files in data_dir          [untimed prepare]
variant files --formats.load--> arrays --validate vs canonical sha/bytes--> GATE (abort on any mismatch)
GATE passed --results.capture_env--> run.json (start)
runner: for each (size, round): shuffled cells --> spawn worker(request) --> one JSON line --> results.append(trials.jsonl)
trials.jsonl + run.json --analysis--> summary.csv (derived, regenerable)
summary + records --report--> plots/*.png + reports/<run_id>.md
```

Direction is strictly one way: config -> dataset -> formats -> (validate gate) -> worker trials -> JSONL -> analysis -> report. Nothing downstream of `results` ever calls back upstream; this is what makes `sdplab report --run <dir>` possible without rerunning.

### Process boundary (the only runtime coupling)

The runner and worker share **no Python imports**. The coupling is a protocol: a request (variant, operation, size, file paths, `pt_cut`/`eta_cut`, expected `dataset_sha256`, expected preprocess digest, seed) in, one JSON line out. This is a deliberate strength (clean per-process RSS, ADR-004) and the single most under-specified interface in the proposal (see S5).

---

## (b) Build Order and Dependencies

### Dependency graph (what must exist before what)

```
dataset  <-- formats  <-- worker  (+ preprocess)
   ^           ^
   +-- validate +                      config (independent leaf)
results (independent leaf, pure data)
runner  needs: config, dataset, formats, validate, results, and a working worker
analysis needs: results (schema only, can use fixture JSONL)
report  needs: analysis
cli     needs: everything it dispatches to (grows incrementally)
```

Leaves with no package dependencies: `dataset`, `config`, `results` (schema/IO half), `preprocess`.

### Verdict on the PROPOSAL section 16 five-phase outline

**The dependency analysis supports the outline. No hard conflicts.** Phases 1 -> 2 -> 3 -> 4 -> 5 is a valid topological order and matches the stated critical path. Evidence per phase:

| Phase | Contents (PROPOSAL) | Dependency check | Verdict |
|-------|---------------------|------------------|---------|
| 1 Foundation & dataset | project/CI, config, dataset, preprocess, validate | `validate` depends only on `dataset`; `preprocess` on NumPy only; all unit-testable with synthetic arrays | Supported |
| 2 Format variants | formats + round-trip tests, R1 gate | needs `dataset`; produces the arrays `validate` then checks for real | Supported; R1 is the correct gate for everything after |
| 3 Measurement & runner | worker, metrics, env, scheduling, preflight, JSONL/run.json | needs 1 and 2; internally has its own order (below) | Supported; largest and riskiest (L) |
| 4 Analysis, reports, CLI | summaries, plots, report, CLI, e2e test | `analysis` needs only the `results` schema; `report` needs `analysis` | Supported; can start from fixture JSONL once schema is frozen |
| 5 Release hardening | committed example run, README numbers | needs a real run (a human-dependent step on the user's machine) | Supported |

### Refinements the dependencies call for (not conflicts)

1. **Order inside Phase 3.** Build `results.py` record schema + JSONL/`run.json` I/O **first** (pure, no subprocess, fully testable), then `worker.py` with its request/response protocol and a contract test, then `runner.py`. Rationale: `results` is the hub consumed by runner, analysis and report; freezing it first lets Phase 4 analysis be developed against fixture JSONL without waiting for the whole runner. Consider splitting Phase 3 into two plans (3a record schema + worker + env capture; 3b runner scheduling, preflight, failure handling) because it is the L-effort phase with the highest structural risk.
2. **CLI should land incrementally, not only in Phase 4.** `cli.py` is listed under Phase 4 but `info`/`prepare`/`validate` become meaningful at Phase 1-2 and `run` at Phase 3. Without early entry points the developer has no way to exercise earlier phases except ad hoc scripts. Keep Phase 4 as "CLI polish and `report`" only; add each subcommand in the phase that makes it real.
3. **The `config` schema must be complete at Phase 1 even though trials/output sections are first consumed in Phase 3.** The proposal requires unknown keys to fail fast, so the full section list (`dataset`, `formats`, `workload`, `trials`, `output`) must be defined once up front. Low risk; just do not defer sections.
4. **R1 (CSV exactness) is the true gate between Phase 2 and 3.** If it fails, the exact-equality contract (ADR-007) is in question and nothing downstream is meaningful. Informal local check supports optimism (see S9) but is not validation.
5. **Phase 5 needs a capability no module owns:** copying a curated run into `results/examples/`. There is no `export` subcommand in the five-subcommand set. Treat it as a documented manual copy of the whole run directory, unmodified, then verify `report --run` regenerates identical `summary.csv`.

---

## (c) Structural Risks

Ordered by how badly they damage the Core Value ("every reported number is trustworthy"). S1 and S2 were checked empirically in a scratchpad on this machine (Python 3.13.5, NumPy 2.1.3, Linux 7.x); they are observations of this environment, not general proofs.

### S1 (CRITICAL, verified): worker `ru_maxrss` is floored by the parent's high-water mark

**What happens.** A child started by `subprocess` (also with `os.posix_spawn`) reports `ru_maxrss` equal to the **parent's** peak at spawn time whenever that exceeds the child's own peak. Observed: parent at 46 MiB peak -> bare child reported the identical 46,244 KiB (its true usage was about 9.5 MiB); parent at ~353,692 KiB peak -> child reported 353,692 KiB, while the same child's `VmHWM` from `/proc/self/status` read 9,548 KiB (9,616 KiB under `posix_spawn`) and 45,808 KiB after importing NumPy. Freeing the parent's memory does not lower it. This is consistent with Linux carrying the high-water mark across `exec` (the original getrusage patch discussion describes exec preserving it; MEDIUM on mechanism, HIGH on observation).

**Why it breaks this design.** ADR-005 makes `ru_maxrss` the headline memory metric, and `rss_baseline_kib` (current RSS after imports) does **not** reveal the floor. The runner process imports `dataset/formats/validate`, generates the canonical array and (per workflow step E) loads all four variants for validation, including `np.loadtxt` at 10^6 rows. The informal CSV experiment left a parent at 194,256 KiB peak. Every worker spawned afterwards would then report at least that, so `npy` at 10^4 rows (true peak about 50 MB) and `csv` at 10^6 rows could look near-identical. RQ4 would be silently wrong while every record looked valid and `correct: true`.

**Prevention (within the confirmed modules).**
- `worker.py` records `VmHWM` from `/proc/self/status` as an additional raw field alongside `ru_maxrss` (Linux-only, same platform constraint as ADR-005). This needs an ADR-005 amendment; schedule it before Phase 3.
- `runner.py` records its own `ru_maxrss` immediately before each spawn (`runner_peak_rss_kib_at_spawn`); `analysis.py` flags any trial whose `ru_maxrss` is not greater than that value as floored and unusable for peak comparison.
- `cli.py` must **lazy-import** `report` (matplotlib) so the `run` path never loads matplotlib into the parent. Importing it at module top would inflate the parent floor even though "only `report` imports matplotlib" holds on paper.
- Prefer keeping heavy validation out of the process that spawns trials (e.g. `validate` as its own invocation before `run`); at minimum, the detection above must exist.

**Detection.** `peak_rss_kib` identical or nearly identical across variants and sizes within one run; worker `VmHWM` far below `ru_maxrss`.

### S2 (HIGH, partly verified): memory baseline and input acquisition are undefined for `write` and `preprocess`

**What happens.** `write` and `preprocess` need an in-memory array inside the worker, but the proposal does not say where it comes from (regenerate via `dataset.generate`, or read a canonical file). Either way, setup allocates memory that sets the high-water mark before the timed region (a 5M-element lognormal temporary raised `VmHWM` from about 52 MB to about 91 MB in a throwaway test). The documented baseline ("RSS sampled after imports, before the operation") is a point sample and cannot subtract a prior peak, so `peak - baseline` misattributes setup memory to the operation.

**Prevention.** Decide in the Phase 3 plan: (1) input acquisition for `write`/`preprocess` (regenerating through `dataset.generate` is allowed by the dependency rules and avoids a fifth canonical file); (2) the exact sample point of `rss_baseline_kib` (immediately before the timed region, after setup); (3) the worker resets the `VmHWM` peak after setup by writing `5` to `/proc/self/clear_refs` (observed to work unprivileged). Note this reset lowers `VmHWM` and `ru_maxrss` only when the floor in S1 is absent, which is another reason S1 detection is required.

### S3 (HIGH): `write` trials can corrupt or perturb the files that `load` trials read

If `write` targets the same canonical variant path that `load` reads, a killed or failed write leaves a truncated file and every later load trial in that round fails or reports `correct: false`, cascading from one fault. Dirty-page writeback from a large write also overlaps neighbouring shuffled trials. **Prevention:** `write` trials write to a separate scratch path (per trial or per cell) and are removed after the correctness read-back; canonical variant files are written once in untimed `prepare` and never touched by timed trials. Document the writeback overlap as a known noise source (shuffling mitigates, does not remove).

### S4 (HIGH): two competing definitions of "timed write"

PROPOSAL section 5 step D says "Write each variant; time write; record file bytes" in the main workflow, while section 9 says all timing is inside the worker and `write` is a worker operation. These are two timing paths for the same quantity. **Resolution:** `prepare` writes variant files **untimed** (needed so loads have inputs and so file sizes exist for `run.json`); the only timed write is the worker `write` operation. Fix the workflow diagram wording in the README merge.

### S5 (HIGH): the worker protocol is an unowned interface

`runner` and `worker` may not import each other and `worker` may not import `results` (dependency rules), so request and response schemas exist only as implicit agreement. Drift produces failed parses that look like failed trials. Specific gaps:
- No `timeout_s` key exists in the section 10 TOML, although section 11 requires timeout handling. Add it to the schema at Phase 1/3.
- stdout must carry exactly one JSON line; library warnings, stray prints, or a crash after partial output must become `status="failed"` with captured stderr, never a runner exception.
- Nonzero exit with a valid JSON line, valid exit with unparseable output, and timeout must each map to a defined failed-trial record.
- The expected preprocess-output digest must be computed by the runner (during validation) and passed in the request, otherwise the worker cannot run the per-trial check for `preprocess` / `load_preprocess`.

**Prevention:** a contract test (spawn a real worker at tiny N, assert the exact key set and types) plus fault-injection tests (kill, timeout, garbage stdout). Keep the key set defined in one place that the test imports; do not weaken the dependency rules.

### S6 (MEDIUM): per-trial correctness is defined for `load` only

"Hash the produced array" is clear for `load`. For `write` the produced artifact is a file (needs a read-back after the timer and after the RSS read), for `preprocess` it is outputs, for `load_preprocess` both. Define per-operation correctness in the Phase 3 plan and keep the order timer -> RSS read -> hash/read-back, as R8 requires.

### S7 (MEDIUM): `results.py` is a hub whose schema is hard to change later

Runner (writer), analysis and report (readers), and the example-run policy all depend on it. Additional gaps to settle at freeze time:
- JSONL append-safety: a crash can leave a truncated final line; readers need a defined behaviour (tolerate-and-flag vs reject).
- `run.json` is written at start and completed at end; define a `status` field so an interrupted run is recognisable.
- Regeneration "from `trials.jsonl` + `run.json` alone" means every parameter used by analysis flags (the k x median threshold, load-average threshold) must be stored in `run.json`, not read from current config or defaults.
- Noise flag "run's load average is high" is run-level only; per-trial load is not in the trial schema, so per-trial flags cannot be computed. Either flag at run level only or add a per-trial field.

### S8 (MEDIUM): `cli` dependency rules vs the subcommand set

Rules allow `cli -> {runner, analysis, report, config}`, but `prepare` and `validate` need `dataset/formats/validate`. Either expose them as runner entry points (`runner` already uses them for the pre-run gate) or add edges `cli -> dataset/formats/validate`. Prefer runner entry points to keep the rules as written; this makes the runner larger, which is acceptable for about 10 modules.

### S9 (informational): R1 CSV risk looks tractable, but only an informal check exists

Throwaway check on this machine: `%.17g` write via `np.savetxt` and `np.loadtxt(dtype=EVENT_DTYPE)` were byte-identical on an 8-row edge set (subnormal `5e-324`, `-0.0` with sign preserved, `1.797...e308`, `nextafter` neighbours) and on 10^4, 10^5 and 10^6 generated rows (66 MB file at 10^6, load about 0.6 s). Treat as a hint only: it is not the Phase 2 test, covers one platform, and says nothing about timing claims. Also informally observed: `.npz` structured-array round-trip is byte-exact with `allow_pickle=False`, and `.npz` compressed size at 10^5 rows is about 78% of `.npy` (random-ish floats compress poorly; do not state this in docs until produced by the tool).

### S10 (minor): scheduling choices to settle in the Phase 3 plan

- Loop order of sizes vs rounds: "sizes outer, rounds inner" bounds disk and RAM but lets thermal drift confound the size-ordering stability asked by RQ5; "rounds outer" needs all sizes' files resident (fine to 10^6, heavy at 10^7).
- `startup_overhead_ns = subprocess_wall_ns - (operation + validation + output time)`: output (JSON emit) time cannot be self-measured before it is emitted, so define it as a residual and label it so.
- Git commit/dirty capture must degrade gracefully outside a git checkout (tarball, CI shallow clone).
- The e2e smoke test spawns about 64 workers at 1,000 rows; estimate roughly 0.1-0.3 s each (NumPy import), so the < 30 s target is plausible but unmeasured.

---

## Patterns to Follow

### Pattern 1: Append-only raw records, derived views
**What:** Each trial is a self-contained JSONL line; everything else (`summary.csv`, plots, report) is regenerated from raw files.
**When:** Always; it is what makes `report --run` rerun-free and keeps failures visible.
**Trade-off:** A flatten step for spreadsheets; readers must handle partial trailing lines (S7).

### Pattern 2: Thin driver, fat-contract worker
**What:** Worker does one thing and emits one line; runner owns all policy (order, retries, timeouts, persistence).
**When:** Whenever a measurement must be isolated from the harness (here: RSS and start-up cost).
**Trade-off:** The request/response protocol is the real API and needs its own tests (S5).

### Pattern 3: Validation gate before measurement, correctness flag after
**What:** Pre-run `validate` aborts the run; per-trial `correct` flag excludes bad trials from summaries but keeps them in raw data.
**When:** Always; this is the project's Core Value mechanism.
**Trade-off:** Two checks must stay consistent (S6).

## Anti-Patterns to Avoid

### Anti-Pattern 1: Heavy work in the spawning process
**What people do:** Generate, validate and import plotting libraries in the same process that launches workers.
**Why it's wrong:** The parent's high-water mark floors every worker's `ru_maxrss` (S1).
**Do this instead:** Keep the runner lean at spawn time, lazy-import `report`, record the parent's peak per spawn, and capture `VmHWM` in the worker.

### Anti-Pattern 2: Timed trials mutating shared inputs
**What people do:** Let a `write` benchmark overwrite the same file other benchmarks read.
**Why it's wrong:** One failure cascades and ordering becomes a hidden variable (S3).
**Do this instead:** Scratch paths for timed writes; canonical files written once, untimed.

### Anti-Pattern 3: Hidden schema in code paths
**What people do:** Let the producer and consumer of a process boundary agree implicitly.
**Why it's wrong:** Silent drift appears as "failed trials" (S5).
**Do this instead:** One key-set definition plus a real-subprocess contract test.

## Scaling Considerations

| Scale | Adjustment |
|-------|------------|
| 10^4-10^6 rows (MVP) | Current design is sufficient; preflight needed only for disk (about 66 MB CSV at 10^6, 29 GB free) and not RAM. |
| 10^7 rows (optional) | Roughly 10x file and array sizes (CSV about 660 MB); `--allow-large` + preflight; revisit S10 loop order (rounds outer would hold all sizes). |
| Beyond | Out of scope (no streaming, mmap, parallel loading). |

## Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| runner <-> worker | subprocess; request in, ONE JSON line out | Unowned interface (S5); the only place RSS isolation is decided (S1) |
| runner -> results | direct calls (append JSONL, write run.json) | Hub schema; freeze early (S7) |
| analysis/report -> results | read-only files | Must work with no benchmark rerun |
| cli -> logic | direct calls, lazy import of `report` | Lazy import protects the S1 floor |

## Sources

- `docs/architecture/PROPOSAL.md` sections 4-11, 15, 16 (CONFIRMED baseline) - HIGH
- `docs/research/research-notes.md` (T6, M1-M4, N5, C2, gap 4) - HIGH for what it states
- Local throwaway experiments in the session scratchpad (Python 3.13.5, NumPy 2.1.3, Linux 7.x): child `ru_maxrss` floor, `VmHWM` independence, `clear_refs` reset, CSV/NPY/NPZ round-trips - HIGH for this machine only; not benchmark results and not to be cited in the README
- [getrusage ru_maxrss LKML patch thread](https://lkml.iu.edu/hypermail/linux/kernel/0812.3/01351.html) and [follow-up review](https://lkml.iu.edu/hypermail/linux/kernel/0812.3/01349.html) - MEDIUM (2008-era; mechanism corroboration only, current kernel source not read)
- General knowledge of pyperf / asv / pytest-benchmark harness structure - MEDIUM (not re-fetched)

---
*Architecture research for: reproducible scientific-data I/O benchmark*
*Researched: 2026-10-13*
