# Pitfalls Research

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


> **Decision update (2026-10-13):** the user has since resolved the open items raised by this research. Python floor is now **>=3.12** (CI on 3.12 and 3.13; no 3.11 claim, ADR-015); ADR-005 is amended to store raw `ru_maxrss`, worker `VmHWM`/`VmRSS` and the parent's `ru_maxrss` at launch (the parent-floor effect was re-verified, research-notes section 7); `config_schema_version` and `results_schema_version` are separate (ADR-014); `timeout_s`, noise thresholds and `thread_env` are in the initial config (ADR-016); correctness is validated per operation (ADR-017). Where this file says otherwise it is superseded by `docs/architecture/PROPOSAL.md` (revision 3) and `docs/adr/`. Worker input, loop order and `prepare` vs timed `write` remain deferred to Phase 3 planning.


**Domain:** Reproducible scientific-data file-format performance benchmark (Python 3.11+/NumPy 2.x, subprocess-per-trial, CSV vs `.npy` vs `.npz` vs compressed `.npz` of one structured array)
**Researched:** 2026-10-13
**Confidence:** HIGH for the NumPy/JSON/stdlib behaviours marked "Observed" (run locally; versions below). MEDIUM for kernel/page-cache and statistics-practice items (general knowledge, not re-read from primary sources). LOW only where explicitly flagged.

## How to read this file

- **Observed** = I ran it on this machine. Environment: Python 3.13.5; **NumPy 2.1.3** (anaconda interpreter) and **NumPy 2.5.4** (a throwaway `uv` venv in the session scratchpad; 2.5.x is what STACK.md expects the lock to resolve on Python >= 3.12); Linux 7.0.0-38-generic; ext4 root (88% full) and tmpfs `/tmp`; Intel i5-12450H. Where a result differs between the two NumPy versions it is stated; where nothing is said, both gave the same result. **NumPy 2.4.x (the Python 3.11 resolution) was not tested.** Every "Observed" behaviour must be re-run under the locked versions in the phase named; none of it is a cross-version guarantee.
- **Sourced** = stated by a primary document (cited in `docs/research/research-notes.md`, STACK.md, ARCHITECTURE.md, or fetched this session and named).
- **General knowledge** = standard practice, not re-fetched. Treat as MEDIUM.
- Phases are PROPOSAL section 16: **P1** Foundation & dataset, **P2** Format variants, **P3** Measurement & runner, **P4** Analysis/reports/CLI, **P5** Release hardening.
- The experiment scripts live in the session scratchpad only (not in the repo). Nothing here is a benchmark result and none of these numbers may be quoted in the README.

## Pitfall index

| ID | Pitfall | Severity | Owning phase |
|----|---------|----------|--------------|
| M1 | Worker `ru_maxrss` floored by the parent's peak (inherited across exec) | Critical | P3 |
| M2 | Timed region covers the wrong thing (lazy `.npz` member, setup, hashing, JSON) | Critical | P2 (return type), P3 |
| M3 | Page cache / filesystem not what the README says (tmpfs, dirty pages, "restart = cold") | Critical | P3, P5 |
| R1 | CSV float text round trip: what is exact and what is not | Critical | P2 |
| S1 | Structured-array identity: packed vs aligned, endianness, padding, hash scope | Critical | P1, P2 |
| D1 | README overclaiming | Critical | every phase; enforced in P5 |
| M4 | Subprocess-per-trial warms the page cache but not the interpreter; tiny-N timings are first-call dominated | High | P3, P4, P5 |
| M5 | Asymmetric work in the comparison (Python-loop CSV writer, `loadtxt` only, fixed compression) | High | P2, P4, P5 |
| M6 | Noise: battery + `powersave`, thermal drift, order effects, n = 7 | High | P3, P4 |
| M7 | Statistics: quantile-method ambiguity, survivorship, ratios of medians | High | P4 |
| S2 | `.npy`/`.npz` mechanics: extension auto-append, per-access decompression, version-dependent `savez` kwargs | High | P2, P3 |
| G1 | RNG stream stability and dataset identity | High | P1 |
| V1 | Result-schema versioning and JSONL robustness | High | P3, P4, P5 |
| C1 | CI flakiness: timing in disguise, subprocess cost, warnings-as-errors, missing sysfs | High | P1, P3, P4 |
| M8 | Subprocess overhead leaks: `__init__` imports, stdout pollution, residual "start-up" | Medium | P3 |
| D2 | Data/size hygiene: example-run bloat, scratch files | Medium | P3, P5 |

---

## Critical Pitfalls

### M1: Worker `ru_maxrss` is floored by the parent's high-water mark

**What goes wrong:** A child process reports `ru_maxrss >=` the parent's peak RSS at spawn, so a cheap loader (`npy` at 10^4 rows) can look as memory-hungry as `csv` at 10^6 if the runner earlier generated or validated large arrays. RQ4 would be silently wrong while every record is `correct: true`.
**Why it happens:** Linux carries the high-water mark across `exec`, so `RUSAGE_SELF` inside the worker is not "the worker's own peak" unless the parent was small.
**Evidence:** Sourced/Observed in ARCHITECTURE.md S1 and STACK.md C1 (two independent probes; e.g. parent 353,692 KiB peak -> child `ru_maxrss` 353,692 KiB while the child's `VmHWM` was 9,548 KiB). Not re-derived here.
**How to avoid:**
1. Record `VmHWM` and `VmRSS` from `/proc/self/status` in the worker next to raw `ru_maxrss` (needs an ADR-005 amendment before P3 planning).
2. Record the runner's own `ru_maxrss` at each spawn; analysis flags trials where `ru_maxrss <= parent_peak_at_spawn` as floored and shows "n/a (floored)" instead of a number.
3. Keep the runner lean at spawn time: no generated array held while spawning, `cli` lazy-imports `report`/matplotlib (importing `matplotlib.pyplot` costs about 290 ms and tens of MB), heavy `validate` in its own invocation.
4. `write`/`preprocess` need an in-memory input inside the worker; that setup sets the high-water mark before the timed region (ARCHITECTURE.md S2). Decide where the input comes from, sample the baseline immediately before the timed region, and consider resetting the peak after setup with `/proc/self/clear_refs` <- `5` (only meaningful when the floor is absent).
5. `rss_baseline_kib` is a point sample and cannot subtract a prior peak, so `peak - baseline` can be 0 or negative for cheap loaders. Never clamp or hide it; show raw values and label any difference `estimated_workload_rss_kib`.
**Warning signs:** `peak_rss_kib` nearly identical across variants and sizes within one run; worker `VmHWM` far below `ru_maxrss`; an estimate of exactly 0.
**Phase to address:** P3. A test reproduces the probe (parent allocates ~200 MiB, spawns a bare worker, asserts the floor detector fires with a large margin, not an exact number).

### M2: The timer surrounds the wrong region

**What goes wrong:** The number labelled "load time" is not the time to get a usable array.
1. **`.npz` is lazy per access.** `np.load("x.npz")` returns an `NpzFile`; bytes are read (and, for the compressed variant, inflated) only when `z["events"]` is evaluated, and **every** evaluation re-reads and re-inflates. Observed, both NumPy versions: the second access returns a new object (`x is y` is `False`) and costs the same as the first (10^5 rows: 2.2 ms then 2.1 ms uncompressed and 13.6 ms then 13.6 ms compressed on 2.1.3; 1.5/1.3 ms and 13.9/13.0 ms on 2.5.4). A loader that returns the `NpzFile`, or a timer that stops before the member access, measures nothing; a loader that touches the member twice doubles its cost. This resolves research-notes gap 3 for these versions.
2. Not closing the archive inside the loader (descriptor leak; Sourced N5). Arrays stay valid after `close()` (Observed), so materialise first, close inside the timed function.
3. Setup leaking into the region: dataset generation for `write`/`preprocess`, `os.stat` for file size, first-use `import` statements inside the function (see M4).
4. Per-trial hashing, JSON encoding or the RSS read placed before the timer stops (PROPOSAL R8 requires: timer -> RSS read -> hash).
5. `load_preprocess` timed as two timers summed; `preprocess` run on a freshly page-faulted array in one variant and a different memory state in another. Define the input of `preprocess` once ("array produced by `generate` in the same process") and use it for every variant.
6. Garbage collection or deallocation of a previous array happening inside the timed span.
**How to avoid:** One function per (variant, operation) with the contract "path -> `np.ndarray` that owns its data"; the timer wraps only that call; `gc.collect()` before the timer, and record whether GC was disabled during it; unit test that `npz`/`npz_compressed` loaders return `type(x) is np.ndarray` with `x.dtype == EVENT_DTYPE` and never an `NpzFile`; a test with an injected fake clock asserting exactly which calls fall inside the span. Write the "what is timed" sentence per operation in the README from PROPOSAL section 9, not from memory.
**Warning signs:** `npz` load faster than `npy` at all sizes; `npz_compressed` load nearly equal to `npz`; load time flat across sizes.
**Phase to address:** P2 (loader return-type contract and test), P3 (timed span in `worker.py`).

### M3: The page-cache / filesystem story in the README is not the story on disk

**What goes wrong:** Claims such as "cold start", "disk read speed" or "write throughput" are made about a path that is RAM-backed or a cache hit.
**Specifics:**
- A restarted process does not clear the OS page cache (Sourced C2). The only supported mode is "ordinary warm-cache benchmark" (PROPOSAL section 9, ADR-006). Never describe process restarts as cache clearing.
- **This machine's `/tmp` is tmpfs** (Observed `df -T`); the repo's disk is ext4. A `data_dir` under `/tmp` (the default location for `tempfile`, many pytest setups and CI scratch space) turns every file benchmark into a memory copy and can change which variant wins. Overlayfs (containers) and compressing filesystems (btrfs/zfs) have their own effects.
- **Default `write` leaves dirty pages behind.** Observed on ext4: `Dirty:` in `/proc/meminfo` was 10,140 kB before and 76,508 kB immediately after `np.save` of a 68 MB array returned (so ~66 MB still to be flushed); on tmpfs it did not change. The kernel flushes these during later, shuffled trials, adding noise to unrelated neighbours (ARCHITECTURE.md S3). This is also exactly why default `write` time is "time to hand bytes to the page cache and close", not persistence time (ADR-012).
- "Warm" is assumed, not checked. `fincore` (util-linux) exists on this machine and reported the freshly written 64.9 MiB file as 100% resident on both filesystems (Observed). An optional residency probe is cheap, but is not in the MVP; do not claim the tool verified warmth unless it does.
- Memory pressure: with ~14 GiB RAM, many CSV copies or the 10^7-row extension can evict pages and turn a "warm" run partly cold.
**How to avoid:** Record the filesystem type and mount of `data_dir` in `run.json` (already in the PROPOSAL environment list); warn loudly (config override recorded as a flag) when it is `tmpfs`/`ramfs`/`overlay`; default `data_dir` is the repo's gitignored `data/generated/`, never `/tmp`; label the metric "write (no fsync)"; README says "ordinary warm-cache benchmark on one machine".
**Warning signs:** `csv` load throughput near memory bandwidth; `write` time nearly independent of file size; `run.json` shows a RAM filesystem.
**Phase to address:** P3 (environment capture, warning, scratch-path policy), P5 (README wording).

### R1: "CSV round trip is exact" - what is and is not true

Closes research-notes gap 4 and informs PROPOSAL R1/ADR-007. **Observed on NumPy 2.1.3 and 2.5.4 unless stated; re-run under the locked versions in P2.**

**Verified exact (finite float64):** `%.17g` write + `np.loadtxt(dtype=EVENT_DTYPE, delimiter=",", skiprows=1)` reproduced the exact bytes for: an 18-value edge set (`5e-324`, `-5e-324`, `2.2250738585072009e-308`, `2.2250738585072014e-308`, `±1.7976931348623157e308`, `nextafter(1.0, 2)`/`(1.0, 0)`, `±0.0`, `0.1`, `1/3`, `1e22`, `1e23`, `2**53` and `2**53+2`, `pi`; each also negated and reversed into the other float columns), **199,901 random finite bit patterns** (uniform over the 64-bit space, hence many subnormals and extreme exponents), 50,000 random subnormals, and 10^5 realistic rows. `-0.0` keeps its sign bit.
**Why this probably holds (MEDIUM):** the NumPy C `loadtxt` parser converts each float field with CPython's `PyOS_string_to_double` (Sourced: `numpy/_core/src/multiarray/textreading/conversions.c`, `double_from_ucs4`, fetched from NumPy `main`; the file makes no rounding claim). The writer is Python's `%` formatting. My understanding that both use CPython's own correctly rounded dtoa code, independent of the platform libc, is general knowledge and was not verified at source; the empirical test carries the weight and covers one platform.
**Also Sourced (gap 1 resolved):** `loadtxt` was reimplemented in C in NumPy 1.23 ("most of it is now implemented in C", 1.23.0 release notes) and "may now fail to convert certain strings ... previously successfully read" (workaround `converters=`). The note gives no speed or memory figures, so relative speed is something to measure and never to assert.

**Not exact, or traps, relevant to test design:**

| Case | Observed | Consequence |
|------|----------|-------------|
| `nan` with payload / negative NaN | text is just `nan`; round trip gives canonical `0x7ff8000000000000` (payload `...0123` and sign lost). `inf`/`-inf` round-trip | Bytes equality fails for any NaN. The dataset contains no NaN/inf; edge tests must exclude NaN or treat it separately and say so. |
| `np.array_equal` on structured arrays | NaN compares unequal; `equal_nan=True` **raises `TypeError`** on structured dtypes | Compare per field if NaN ever matters. |
| `np.array_equal(0.0, -0.0)` | `True`, bytes differ | `array_equal` alone would miss a lost sign of zero. The bytes/SHA-256 check is the real gate; it must be mandatory, not "plus". |
| `np.savetxt(fmt="%.17g")` with a single fmt on the structured array | works, but pushes the `int64` through float: `event_id = 2**62+1` -> `4.6116860184273879e+18` | Always pass a per-field `fmt` list (`%d` for integers); test integers > 2**53 (the real `event_id < 10^7` hides this). |
| `np.savetxt` default header | written as `# event_id,pt,...` | Pass `comments=""`; otherwise the header is a comment line and `skiprows=1` removes a *data* row. |
| 1-row file | `loadtxt` returns a **0-d** array (`shape == ()`) | Use `ndmin=1`; test N = 1. |
| Header-only file | shape `(0,)` plus `UserWarning: input contained no data` | Becomes an error under `filterwarnings = ["error"]` (STACK.md); test N = 0 deliberately. |
| Integer field containing `"1.0"` | **2.1.3:** accepted with `DeprecationWarning` (deprecated in 1.23, Sourced). **2.5.4:** `ValueError` (deprecation has expired) | Behaviour differs across the versions the lock may pick. The writer emits `%d` for integer fields so neither path is exercised. |
| `int16` field with `40000` | **2.1.3:** wraps to `-25536` with only that DeprecationWarning. **2.5.4:** `ValueError` | On older NumPy with the default warning filter this is silent corruption. Add a validator test feeding an out-of-range code; the CI warning policy is the safety net. |
| Truncated last line | `ValueError` (column count) | Loud; good. |
| CRLF line endings | loads identically | fine |

**Not verified:** correct rounding on other platforms/libc; behaviour under NumPy 2.4.x; locale effects (Python `%` formatting does not use the C locale, but this was not tested under another `LC_ALL`).
**Prevention:** write the edge-value test **before** accepting the CSV writer (PROPOSAL section 12); keep both a seeded random-bit-pattern property test (~10^5 values, sub-second) and the explicit edge list; per-field `fmt`; `ndmin=1`; document that NaN/inf are outside the contract. If anything fails, follow R1: investigate writer -> parser -> dtype before any ADR to loosen the contract.
**Warning signs:** a 1-ULP mismatch in one field; shape `()`; unexpected DeprecationWarnings during tests.
**Phase to address:** P2 (gate before P3).

### S1: Structured-array identity is more than "same values"

**What goes wrong:** Two arrays pass `np.array_equal` or hash alike and are not the same artefact; or are the same artefact and hash differently.
**Observed (both NumPy versions):**
- **Packed vs aligned.** `np.dtype(..., align=True)` gives itemsize 40 (padding field `|V6`), `dtype == EVENT_DTYPE` is `False`, `tobytes()` is 4,000,000 B vs 3,400,000 B at 10^5 rows, the `.npy` file is 4,000,192 B vs 3,400,192 B, yet `np.array_equal` is `True`. If anything introduces alignment (a dtype literal with `align=True`, a conversion), the "34 B/row" logical payload and the throughput numerator are wrong with no value-level test failing.
- **Padding is uninitialised.** Two aligned arrays with equal values and different junk in padding: `array_equal` `True`, bytes differ. A hash of `tobytes()` becomes non-deterministic if the array came from `np.empty`. Packed `EVENT_DTYPE` has no padding (PROPOSAL section 7); make that an enforced invariant.
- **Endianness.** `astype('>f8', ...)` keeps values equal, bytes differ, `dtype ==` is `False`; `.npy` preserves the big-endian descr on round trip, so the SHA differs from the little-endian original. All fields are explicitly `<`; the check must be on `dtype ==` plus bytes, not on values.
- **A bytes hash does not cover field names.** A `.view(renamed_dtype)` of the same buffer has an identical SHA-256. The identity hash must include the dtype description and shape.
- **Hashing views.** `hashlib.sha256(a[::2])` raises `ValueError: ndarray is not C-contiguous`. `hashlib.sha256(arr)` on a contiguous structured array works directly (Observed; consistent with R8's zero-copy hashing), so use `np.ascontiguousarray` first and assert contiguity.
**How to avoid:** One `EVENT_DTYPE` constant. An `assert_canonical(arr)` helper in `dataset.py` used on every loader output: `arr.dtype == EVENT_DTYPE`, `ndim == 1`, C-contiguous, `itemsize == 34`, not `isalignedstruct`. `array_sha256` hashes `(dtype.descr, shape, buffer)`. Tests that deliberately feed an aligned, big-endian and renamed array to the validator and expect rejection.
**Warning signs:** `.npy` `file_bytes` equals `N*40 + 192`; the validator accepting a dtype it should not.
**Phase to address:** P1 (dtype, hash, canonical check), P2 (each loader's output checked).

### D1: README overclaiming

**What goes wrong:** The existing 823-line README draft already describes the finished system while the repo has no implementation. Typical failures here: "implemented"/"verified" for planned features; result tables before a committed real run; "CSV is N x slower" read as a property of CSV rather than of `np.loadtxt` + this writer on one laptop; "cold cache" or "restart clears cache"; memory presented as exact; "reproducible" read as "same timings" (only the dataset is deterministic); "HEP data"/"CERN-like" wording; universal-fastest claims; throughput compared across different numerators.
**How to avoid:**
- Status vocabulary limited to {planned, implemented, tested, verified-by-committed-run}; every CLI command marked planned until its phase lands.
- Every benchmark number in the README is generated from, or pasted verbatim from, the committed `results/examples/<run_id>/`; a P5 check asserts each README number appears in that run's `summary.csv`.
- Name the measured thing precisely: "`np.loadtxt` on a `%.17g` CSV", "write without fsync", "warm page cache", "`ru_maxrss`-derived estimate".
- Banned in README/report without a run id and the words "in this run, on this machine": "faster than", "significant", "cold", any ROOT/CERN performance statement.
- Always include the caveat block (PROPOSAL section 9) plus the run's power source, governor and filesystem type copied from `run.json`.
- Compression results depend on the synthetic distributions (sequential ids; `eta` clipped, with 3,657 of 10^5 rows exactly at +-2.5 in the informal check; `.npz` compressed was 2,686,321 of 3,400,192 B = 79% of raw, informal, not quotable). Say so and never generalise.
**Warning signs:** adjectives ("blazing", "dramatically"); numbers without a run id; "validated"/"verified" with no test or run cited.
**Phase to address:** every phase for status wording; P4 report templates carry the caveat block so it cannot be dropped; enforced in P5 (merge the draft README, number-provenance check).

---

## High-Priority Pitfalls

### M4: Subprocess-per-trial still measures first-call behaviour

**What goes wrong:** Each trial is a fresh interpreter, so the 2 warm-up rounds warm the OS page cache and `.pyc` files, **not** in-process state: lazy imports, allocator arenas, CPU caches, page faults on newly mapped memory. Observed on NumPy 2.1.3 (10^4 rows, repeated calls in one process): `npy` load 0.338 ms first call vs ~0.08 ms steady; `npz` 0.63 vs 0.44 ms; `csv` ~5-6.5 ms. Also Observed (both versions): `import numpy` does not import `zipfile`; the first `np.load` of an `.npz` does, so `npz` first-call cost includes that import. At 10^4 rows the `npy` timed region is a few hundred microseconds while the whole worker costs tens of milliseconds to start (M8), so ratios at the smallest size are dominated by first-call cost and noise.
**Consequences:** RQ5 ("does ordering stay stable across sizes") can be answered wrongly; "throughput" at 10^4 is not a steady-state property; csv/npy ratios at 10^4 are inflated by first-call cost.
**How to avoid:** State the metric as "fresh process, warm page cache, first call" (a legitimate real-world workload, not steady state). Report sizes separately; never extrapolate 10^4 throughput. A second in-process repetition may be added later as a separate, labelled field (extension, not MVP). Warm-ups must also absorb first-run `.pyc` generation, which they do unless `PYTHONDONTWRITEBYTECODE` is set.
**Warning signs:** largest relative IQR at 10^4 rows; ordering flips between 10^4 and 10^6.
**Phase to address:** P3 (metric definition in code and docs), P4 (display), P5 (README).

### M5: Asymmetric work makes the comparison dishonest without anyone lying

- **The CSV writer is not "CSV".** Exact text output comes from a Python-level per-row formatter (`%`-format loop or `np.savetxt` with a per-field fmt list, which also formats row by row). CSV write time therefore measures Python string formatting. Label it "CSV via Python formatter", and do not compare it to `np.save` as a format property.
- **`%.17g` vs shortest `repr`.** Both round-trip exactly (Observed). Sizes at 10^5 rows: 6,603,871 B (`%.17g`) vs 6,466,355 B (shortest repr), about 2% here. It is a free design choice that changes CSV size and parse time; document the choice and rationale (fixed, algorithm-independent rule).
- **`np.loadtxt` is the only CSV loader** (pandas out of scope, ADR-013); any sentence about "CSV" is a sentence about `loadtxt` for this dtype.
- **Copy counts differ by loader** (accepted, PROPOSAL section 7); do not "fix" one side (e.g. `mmap` for `npy` only).
- **Compression is one fixed setting.** `np.savez_compressed` takes no level argument in either NumPy version (Observed signatures: 2.1.3 `(file, *args, **kwds)`, 2.5.4 `(file, *args, allow_pickle=True, **kwds)`), so results are for NumPy's default DEFLATE only.
- **Different throughput numerators** must stay in separate columns/plots (PROPOSAL section 9).
**How to avoid:** a "what each number measures" table (variant x operation: function called, work included); no per-variant tuning; axis labels name the implementation; a limitations paragraph.
**Phase to address:** P2 (implementations and docs), P4 (labels), P5 (README).

### M6: Noise on a consumer laptop can exceed the effects being claimed

**What goes wrong:** Differences between `npy` and uncompressed `npz` are small; a governor or thermal change between rounds produces apparent winners.
**Observed at research time on this machine:** AC adapter `online = 0`, battery `Discharging`, CPU0 governor `powersave`, `intel_pstate/no_turbo = 0`, load average 0.48. A run started in this state is only honestly labelled if env capture reads these files.
**Specifics:**
- Position effects: shuffling per round is good, but each cell sees few positions in 7 rounds; keep `position` in records and let analysis look for position/round correlation.
- Loop order "sizes outer, rounds inner" lets slow drift confound cross-size comparison (ARCHITECTURE.md S10).
- Load average is sampled before/after, not per trial (ARCHITECTURE.md S7), so noise flags are run-level only.
- An outlier threshold k chosen after seeing the data is p-hacking; fix k in config and store it in `run.json`.
- `platform.processor()` returns `''` on this Linux (Observed); read `/proc/cpuinfo` `model name` ("12th Gen Intel(R) Core(TM) i5-12450H"). `os.cpu_count()` equals the affinity set here but not under cgroups/taskset; also record `len(os.sched_getaffinity(0))`.
**How to avoid:** capture governor, `no_turbo`, power-supply state, load average, CPU model, affinity, every capture tolerant of absent files (`null`, never a crash); a run-quality banner in the report when on battery or governor is `powersave` (warn, do not block); README advises AC power and an idle machine but still reports results with their conditions.
**Warning signs:** IQR/median above ~10% in many cells; monotone drift of elapsed time with `round`; the last round consistently slower than the first.
**Phase to address:** P3 (capture, loop order), P4 (position/drift diagnostics, banner).

### M7: Statistics that quietly mislead

- **"IQR" is not one number at n = 7.** For values 1..7, `statistics.quantiles(..., n=4)` (default `exclusive`) gives Q1 = 2.0, Q3 = 6.0 (IQR 4.0); `method="inclusive"` and `np.percentile` (linear) give 2.5 and 5.5 (IQR 3.0) (Observed). A 33% change in the headline spread from an unstated default. Pick one method, write it into the summary metadata, and test it on fixed vectors.
- **Small-n degenerate cases (Observed):** `statistics.stdev` raises `StatisticsError` for one value; `statistics.median([])` raises; `statistics.quantiles` on one value returns without error (a degenerate result, not an exception). A cell where every trial failed must still appear in `summary.csv` with `n_ok = 0` and empty statistics, not vanish.
- **Survivorship:** statistics over `status == ok and correct` only hide that a loader failed 3/7 times (e.g. timeouts at 10^6). Always emit `n_ok`, `n_failed`, `n_incorrect` next to each statistic and highlight `n_ok < measured_rounds`.
- **Ratios:** ratios of medians carry no uncertainty; with 7 rounds quote at most two significant figures and do not call differences smaller than the observed IQR an ordering. No significance tests (ADR-010), hence no "significantly".
- Plots: draw raw points (jittered strip) over median/IQR; do not show mean +- stdev beside the median.
**How to avoid:** one `quantile()` helper in `analysis.py`; fixed-vector tests (PROPOSAL section 12) including n = 1, 2, empty, ties, and the method choice; summary schema carries `n_*` columns and `quantile_method`.
**Phase to address:** P4.

---

## Moderate Pitfalls

### S2: `.npy` / `.npz` mechanics that bite this harness

**Observed (both NumPy versions unless stated):**
- **Extension auto-append.** `np.save("noext", a)` writes `noext.npy` (no file `noext`); `np.savez("x.tmp", ...)` writes `x.tmp.npz` (no file `x.tmp`). A write-to-temp-then-rename pattern, or `os.path.getsize(path)` on the path you passed, silently targets a different or missing file. An **open file object** keeps the name. Prescribe: `write()` receives a path that already ends in `.npy`/`.npz`; assert `exists` and record `getsize` right after writing.
- **Version-dependent `savez` keyword arguments.** On NumPy 2.1.3 `np.savez(p, events=a, allow_pickle=False)` silently stores an *extra array member named `allow_pickle`* (members: `['events', 'allow_pickle']`); on 2.5.4 the kwarg is real (`allow_pickle` is a parameter) and members are `['events']`. With the declared floor `numpy>=2.0`, never pass `allow_pickle` to `savez`; assert `z.files == ["events"]` after every write/load so a stray member cannot slip in.
- **`mmap_mode` on `.npz`** is silently ignored: an `NpzFile` whose members are plain `ndarray`, no warning. Resolves research-notes gap 2 for 2.1.3 and 2.5.4. Mmap is out of scope; never pass it.
- **Members are lazy and re-read each access** (M2); resolves gap 3.
- **`.npz` files are byte-reproducible** across two writes (zip member timestamp fixed at 1980-01-01 00:00:00). Do not rely on this across NumPy versions; the identity is the in-memory array hash, never the file hash.
- **`.npy` header** pads so data starts on a 64-byte multiple (Sourced N1; Observed). `file_bytes - logical_bytes` is a small constant, not overhead that scales with N.
- `np.load(allow_pickle=False)` is the default; still pass it explicitly (PROPOSAL section 11) so a refactor cannot enable it.
**Phase to address:** P2 (writers/loaders, path and member contracts), P3 (file-size recording).

### G1: RNG stream stability and dataset identity

**What goes wrong:** Tests or docs pin a SHA-256 that changes on another NumPy; adding one column reorders all the others; "same seed" is claimed across versions.
**Facts:** `Generator` has no cross-version stream guarantee (Sourced N8). STACK.md C2: the lock resolves different NumPy minors per Python version; NumPy 2.5 changed `binomial`/`multinomial` streams.
**Observed:**
- With **one `SeedSequence(seed).spawn(4)` child generator per column**, the first 10^4 rows of a 10^6-row dataset are byte-identical to the 10^4-row dataset (lognormal, normal+clip, uniform and `choice(p=)`; chunked `normal`/`choice` draws also equal whole draws). With a single shared stream, swapping two draws changes the other column. `random(dtype=float32)` is not the float64 stream cast down, so the optional float32 schema is a different dataset.
- For a throwaway generator of this shape (100,000 rows, seed 12345; lognormal, clipped normal, uniform, 5-way weighted category), **the whole-array SHA-256 and every per-field hash were identical on NumPy 2.1.3 and 2.5.4**, and `choice(p=...)` gave the same categories as `searchsorted(cumsum(p), rng.random(n), side="right")`. That is an observation for these two versions and these distributions only; it is not the project's final generator and not a guarantee.
**How to avoid:** per-column child streams from `SeedSequence(seed).spawn(k)` with a fixed column order; sizes are then nested prefixes (useful for RQ5: size effects are not draw effects) - claim this only after a property test passes under the locked NumPy; derive the categorical explicitly via `searchsorted` on `rng.random(n)` so it depends only on the core uniform stream; use only `normal`, `lognormal`, `uniform`, `random`; never legacy `np.random.seed`/`RandomState` (Ruff `NPY`); **never commit a hard-coded dataset SHA** (STACK C2) - test determinism across two fresh processes plus bounds/shape/dtype; the committed example run records NumPy version and `dataset_sha256`, and `validate` reports "dataset differs" on mismatch (PROPOSAL R7).
**Warning signs:** a CI leg failing only on hash equality; a column's data changing after another column is added.
**Phase to address:** P1.

### V1: Result-schema versioning and JSONL robustness

**What goes wrong:** A schema change after the example run is committed makes the example unreadable; old and new runs mix in one summary; a crash leaves a half-written line.
- PROPOSAL uses one name, `schema_version = 1`, for the **config file** and for **result records**; they evolve independently. Name them `config_schema_version` and `results_schema_version` (or document an intentional lockstep) before the first record is written.
- State the reader policy: reject unknown/newer versions (as designed); for *older* versions either migrate or reject with a pointer. Additive-only changes within a version.
- **Golden-file tests:** a tiny fixture run (P3) and the committed example run (P5) must load with the current reader; only this catches an accidental break.
- **JSON hazards (Observed):** `json.dumps(np.int64(5))` and `np.int16(3)` raise `TypeError`; `np.float64(1.5)` serialises (float subclass); `json.dumps(float("nan"))` emits invalid JSON `NaN` unless `allow_nan=False` (then `ValueError`). Convert NumPy scalars to Python `int`/`float` at the record boundary and use `allow_nan=False` so a NaN statistic cannot hide in a file. Python ints > 2**53 survive Python's json but not JavaScript consumers.
- **Append safety** (ARCHITECTURE.md S7): one `write()` of a complete line + newline per trial, append mode, flush per trial; the reader tolerates a truncated *final* line (flag it) but rejects a corrupt middle line; `run.json` carries `status` (`running`/`complete`/`interrupted`).
- **Regeneration** needs every analysis parameter in `run.json` (quantile method, k for outlier flags, load-average threshold), not the current defaults.
- Store `dtype` as an explicit field list (`dtype.descr`) rather than `str(dtype)`/`repr`, whose text may differ across NumPy versions (General knowledge, MEDIUM; not tested).
**Phase to address:** P3 (freeze schema, I/O and fixtures before P4 consumes it), P4 (summary carries its own metadata), P5 (golden example).

### C1: CI flakiness and test-suite traps

- **Timing assertions in disguise.** "csv > npz > npy ordering holds", "compressed smaller than raw" on random-ish floats (data-dependent), a noise flag firing in the e2e test, `elapsed_ns < X`. Extend PROPOSAL's "never assert on timings" to anything derived from real timings or compressibility. Assert structure, counts, types, positivity (`elapsed_ns > 0`).
- **Subprocess cost on shared runners.** Observed start-up here: bare interpreter ~11 ms, `import numpy` ~61-77 ms (so ~64 e2e workers cost at least ~5 s before any work; importing matplotlib in a worker would add ~290 ms each). The `< 30 s` target is plausible but still unmeasured; give every worker a generous timeout, mark `@pytest.mark.e2e`, and size the budget from a real measurement on the first CI run.
- **Warnings promoted to errors** (`filterwarnings = ["error"]`, STACK.md) fail on the NumPy `loadtxt` cases in R1 (the "no data" `UserWarning`; the integer-via-float `DeprecationWarning` on 2.1.3) and on `ResourceWarning` from unclosed files (seen when running my scripts with `-W default`). Use `with open(...)` everywhere, test warning behaviour with `pytest.warns`, add narrowly scoped ignores with reasons.
- **Two NumPy minors in CI** (3.11 vs 3.13 legs): any test asserting a version-specific value (dataset hash, dtype `repr`, compressed size, warning-vs-error behaviour from R1) can fail on one leg only (G1).
- **Missing sysfs/proc files** on runners and containers (cpufreq governor, power supply, `no_turbo`): env capture returns `null` and tests accept either.
- **Memory tests asserting numbers** (`VmHWM < 100 MB`) are kernel-dependent; assert presence/positivity and the floor-detector logic on synthetic inputs, plus the one real reproducing probe with a large margin.
- `tmp_path` may be tmpfs: fine for correctness tests, wrong for anything about on-disk behaviour (M3).
- Git capture must degrade to `null` on shallow clone or tarball.
- Declared floors (`numpy>=2.0`, `matplotlib>=3.9`) are untested unless a `--resolution lowest-direct` job exists (STACK.md). The `savez` kwarg difference in S2 is a concrete example of why that matters.
**Phase to address:** P1 (pytest/CI/warning policy), P3 (worker contract and e2e tests), P4 (stats fixtures).

### M8: Subprocess overhead leaks into numbers or breaks the protocol

- A `sdplab/__init__.py` that imports `cli` or `report` pulls matplotlib into **every worker**: slower start-up (~290 ms for `pyplot` here) and a larger `rss_baseline_kib` in every record. Keep `__init__.py` empty; the worker imports only `numpy` plus `sdplab.formats/preprocess/dataset`.
- `startup_overhead_ns = subprocess_wall_ns - (operation + validation + output)` is a **residual**; the output emission cannot be self-timed (ARCHITECTURE.md S10). Name it "residual: interpreter start, imports, JSON write, pipe, reap" and never use it to correct operation times.
- stdout carries exactly one JSON line; a library warning on stdout, a stray `print`, or a crash after partial output must become `status="failed"` with captured stderr (ARCHITECTURE.md S5), never a runner exception; `timeout_s` must exist in the TOML schema.
- Environment inheritance (`PYTHONHASHSEED`, `OMP_NUM_THREADS`, `PYTHONDONTWRITEBYTECODE`, `PYTHONPATH`) changes worker behaviour: pass a controlled environment or record the relevant variables in `run.json`.
- `RUSAGE_CHILDREN` must not be used (Sourced M3); `resource` is Unix-only, so import it only in the worker.
**Phase to address:** P3.

### D2: Data and size hygiene

`data/generated/` and `results/raw|plots|reports/` are ignored but `results/examples/` is tracked. Copying a whole run directory is fine (JSONL + `run.json` + `summary.csv` are small), but a stray 10^6-row CSV (about 66 MB, extrapolated from 6.6 MB at 10^5 rows, Observed) in `examples/` bloats history permanently. Add a P5 check that `results/examples/` contains only the expected file types and sizes. Disk is 88% full: preflight and cleanup of scratch write files (ARCHITECTURE.md S3) matter.
**Phase to address:** P3 (cleanup), P5 (check).

---

## Minor Pitfalls

- `time.perf_counter_ns` is the right clock (Observed `clock_gettime(CLOCK_MONOTONIC)`, resolution 1 ns); never log absolute values (Sourced T1). `process_time_ns` covers all threads; use it only as a diagnostic next to elapsed time.
- `sys.executable -m sdplab.worker` needs the package installed in that environment (STACK.md). A missing install looks like a failed trial; the pre-run gate should smoke-spawn one worker.
- Config rejects unknown keys, so adding a key later (e.g. `timeout_s`) is a schema change; fix the full key set in P1 (ARCHITECTURE.md refinement 3).
- Do not put the project's real data in any path that `.gitignore` does not already cover; check `git status` before the example-run copy.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hard-code an expected dataset SHA in tests | Simple test | Breaks on another NumPy minor (G1) | Never; use cross-process determinism |
| `np.array_equal` as the validator | One line | Misses `-0.0`, NaN, padding, dtype (S1, R1) | Only as a secondary check beside bytes + dtype |
| `ru_maxrss` only | Matches the ADR | Silently floored (M1) | Never alone; store `VmHWM` too |
| One `schema_version` for config and results | Fewer fields | Coupled evolution (V1) | Only if documented as intentional lockstep |
| `write` targets the canonical file | No scratch dir | Failure cascades (ARCHITECTURE.md S3) | Never |
| README numbers typed by hand | Fast | Drift from the run (D1) | Never |
| Pass `allow_pickle` to `savez` | Looks safe | Extra member on NumPy 2.1.x (S2) | Never under `numpy>=2.0` |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `np.loadtxt` | Default `ndmin`/comments; ints silently coerced | `ndmin=1`, explicit dtype, writer/reader agree on header handling, tests run with warnings as errors |
| `np.savetxt` | One `fmt` over a structured array | Per-field `fmt` list; `comments=""` |
| `np.load` on `.npz` | Returning the `NpzFile`; double member access | Access once, copy out, close, return `ndarray` |
| `np.save`/`np.savez` | Path without the right extension | Path already ends in `.npy`/`.npz`; assert existence |
| `subprocess.run` | Mixed stdout, no timeout | One JSON line, `timeout=timeout_s`, a failure record on every error path |
| `hashlib` + NumPy | Hashing a non-contiguous view; bytes only | `ascontiguousarray`; hash dtype descr + shape + bytes |
| `json` | NumPy scalars, NaN | Convert to Python scalars; `allow_nan=False` |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `loadtxt` memory at large N (R2) | RAM spike on a 14 GiB machine | Preflight; report as a finding | 10^7 rows |
| Sub-millisecond timed regions | Huge relative IQR, flipping order | Report sizes separately; state first-call metric (M4) | 10^4 rows, `npy` |
| tmpfs data dir | Implausibly fast file ops | Filesystem check and warning (M3) | Any run under `/tmp` |
| Dirty-page writeback | Noisy neighbours after `write` trials | Scratch files, shuffled order, document (M3) | Large `csv` write |

## "Looks Done But Isn't" Checklist

- [ ] **CSV exactness:** edge-value + random-bit-pattern tests under the *locked* NumPy; N = 0 and 1 cases; per-field `fmt`; an integer > 2**53 (P2).
- [ ] **Identity:** aligned/big-endian/renamed dtypes are rejected by the validator; hash covers dtype + shape (P1-P2).
- [ ] **Memory:** floor-detector test reproduces M1; `VmHWM` stored; estimates labelled (P3).
- [ ] **Timers:** every loader returns `ndarray`; `.npz` member accessed once; timer excludes hashing/JSON (P2-P3).
- [ ] **Env capture:** governor, power source, filesystem type, affinity, CPU model; all tolerant of missing files (P3).
- [ ] **Stats:** one quantile method named in outputs; `n_ok/n_failed/n_incorrect` shown; empty cells present (P4).
- [ ] **Schema:** two version counters, golden-file load test, `allow_nan=False`, NumPy scalar conversion (P3-P5).
- [ ] **README:** every number traced to the committed run; status words correct; caveat block present (P5).

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| M1 | P3 | Test reproducing the parent-floor probe; analysis flags floored trials |
| M2 | P2 (return type), P3 (timed span) | Loader type test; injected-clock test |
| M3 | P3, P5 | `run.json` has fs type; tmpfs warning test; README wording review |
| M4 | P3, P4, P5 | Metric definition documented; 10^4 results not extrapolated |
| M5 | P2, P4, P5 | "What each number measures" table present |
| M6 | P3, P4 | Env capture test with missing files; banner test |
| M7 | P4 | Fixed-vector stat tests incl. n = 1/empty/quantile method |
| M8 | P3 | Worker contract test; empty `__init__` check |
| R1 | P2 | Edge + property round-trip tests pass under locked NumPy |
| S1 | P1, P2 | Wrong-dtype rejection tests |
| S2 | P2, P3 | Path/member contract assertions; `file_bytes` recorded post-write |
| G1 | P1 | Two-process determinism test; no hard-coded SHA |
| V1 | P3, P4, P5 | Golden-file load test; truncated-line test |
| C1 | P1, P3, P4 | CI green with no timing asserts; warning policy documented |
| D1 | all, P5 | Number-provenance check |
| D2 | P3, P5 | Size/type check on `results/examples/` |

## Phase-Specific Warnings (for roadmap use)

| Phase | Likely Pitfalls | Mitigation | Needs deeper phase research? |
|-------|-----------------|------------|------------------------------|
| P1 Foundation & dataset | G1 (stream/hash), S1 (dtype identity, hash scope), C1 (warning policy, two NumPy legs), full config key set | Per-column `SeedSequence` streams; `assert_canonical`; no hard-coded SHA; decide `timeout_s` and the schema-version naming now | No; patterns are settled |
| P2 Format variants | R1, S2, M2 (loader return type), M5 (writer labelling) | Edge + property tests first; per-field fmt; explicit paths; `z.files == ["events"]` | Only if R1 fails (escalate via ADR) |
| P3 Measurement & runner | M1, M2, M3, M4, M6, M8, V1 (freeze), D2 | VmHWM + spawn-time parent peak; fs check; empty `__init__`; fixtures and golden files; fault-injection tests | **Yes**: ADR-005 amendment, `clear_refs` reset behaviour, input acquisition for `write`/`preprocess`, loop order |
| P4 Analysis, reports, CLI | M7, M6 diagnostics, M5 labels, D1 caveat block | One quantile helper; `n_*` columns; raw-point plots; banner | No |
| P5 Release hardening | D1, M3 wording, D2, V1 golden example | Number-provenance check; size check on examples; README status vocabulary | No |

## Verified vs unverified

**Verified by me this session (local, small, read-only experiments; scratchpad scripts, Python 3.13.5, NumPy 2.1.3 and 2.5.4 unless noted):**
- CSV `%.17g` round trip exact for edge values, ~200k random finite bit patterns, subnormals; `-0.0` preserved; NaN payload/sign lost; `inf` preserved.
- `loadtxt` shape `()` for 1 row; "no data" `UserWarning`; int-via-float and `int16` overflow: warning + wrap on 2.1.3, `ValueError` on 2.5.4; single-fmt `savetxt` loses `int64` precision; `savetxt` default `# ` header.
- `np.array_equal` blind to `-0.0` and padding; `equal_nan=True` raises on structured arrays.
- Packed vs aligned (40 vs 34 B/row), big-endian, padding nondeterminism, renamed-field hash collision, non-contiguous hashing error.
- `.npz`: lazy and uncached member access; `mmap_mode` ignored silently; extension auto-append for `np.save`/`np.savez`; byte-reproducible files; `savez` `allow_pickle` kwarg stored as a member on 2.1.3 (but not 2.5.4); lazy `zipfile` import on first `np.load`.
- Per-column `SeedSequence` streams: prefix property across sizes; identical dataset hash on 2.1.3 and 2.5.4 for the throwaway generator.
- `statistics.quantiles` vs `np.percentile` at n = 7; `statistics` small-n behaviour; `json` behaviour for NumPy scalars and NaN.
- Environment facts: tmpfs `/tmp`, ext4 repo disk, `powersave` governor, on battery, `platform.processor()` empty, dirty-page jump on ext4 after `np.save`, `fincore` available, start-up costs (bare ~11 ms, `import numpy` ~61-77 ms, `matplotlib.pyplot` ~290 ms).
- Sourced this session: NumPy 1.23.0 release notes (C `loadtxt`; float-to-int parsing deprecation); NumPy `main` `conversions.c` (`PyOS_string_to_double`).

**Cited from other project files, not re-derived:** child `ru_maxrss` floor (ARCHITECTURE.md S1, STACK.md C1); `RUSAGE_CHILDREN` semantics, `perf_counter_ns` semantics, `NpzFile` must be closed, RNG has no stream guarantee (research-notes M3, T1, N5, N8).

**Not verified (do not state as fact in the README):**
- Anything under NumPy 2.4.x, other kernels, other filesystems (btrfs/zfs/overlayfs), or macOS/Windows.
- That Python's `%` formatting and `PyOS_string_to_double` are correctly rounded on every platform (consistent with the empirical tests; mechanism not read at source).
- That `str(np.dtype)` text differs across NumPy versions (recommendation is precautionary).
- That `fincore` residency can be used inside the harness without side effects, and `clear_refs` peak-reset behaviour under a floored process beyond ARCHITECTURE.md's probe.
- Speed or memory of `loadtxt` relative to anything else (research-notes gap 1 resolved only for "implemented in C since 1.23"); any compression ratio beyond the informal one-off.
- Research-notes gaps 5 (Parquet projection), 6 (`drop_caches` root requirement), 7 (macOS units), 8 (pyperf worker rationale) were out of this dimension and remain open.

## Sources

- `docs/architecture/PROPOSAL.md` sections 7, 9, 10, 11, 12, 14, 16 (confirmed baseline) - HIGH for what it states.
- `docs/research/research-notes.md` (N1, N5, N8, T1, M1-M4, C2, gaps 1-9) - HIGH for what it states.
- `docs/research/ARCHITECTURE.md` S1-S10 and `docs/research/STACK.md` C1-C4 - cited, not re-derived.
- NumPy 1.23.0 release notes, https://numpy.org/doc/stable/release/1.23.0-notes.html - HIGH (fetched this session; fetch tool summarised the page).
- NumPy source, https://raw.githubusercontent.com/numpy/numpy/main/numpy/_core/src/multiarray/textreading/conversions.c - MEDIUM (`main` branch, summarised by the fetch tool; may differ from the released 2.1.3/2.5.4 source).
- Local experiments (scratchpad scripts, not committed): Python 3.13.5, NumPy 2.1.3 and 2.5.4, Linux 7.0.0-38, ext4/tmpfs, Intel i5-12450H - HIGH for this machine and these versions only.
