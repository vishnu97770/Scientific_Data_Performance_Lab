# Benchmark methodology

What is measured, how, and what each number does and does not mean. Results are workload-, machine- and cache-state-dependent; nothing here supports a claim that one format is universally fastest.

## Experimental design
- **One canonical dataset** per size (fixed seed), shared by all variants; its SHA-256 (dtype description + shape + bytes), the NumPy version and the generator version are recorded. A different NumPy version may generate different values for the same seed; `validate` reports that as "dataset differs".
- **Correctness first.** Before any timing, every variant is loaded back and compared bit for bit with the regenerated dataset (dtype, shape, bytes), and the preprocessing outputs are compared too. Any mismatch aborts the run (exit 3). The contract has no tolerance.
- **Per-trial verification.** After the timer stops and after memory counters are read, the worker checks its own output: `load` (hash of the loaded array), `write` (an untimed read-back and hash), `preprocess` (digest of the three outputs), `load_preprocess` (both). Incorrect trials are recorded, counted and excluded from accepted summaries.

## Operations and timing boundaries
Timing is `time.perf_counter_ns()` differences taken **inside the worker process** around the operation only.

| operation | timed region | not timed |
|---|---|---|
| `write` | the variant's writer, to file close (no `fsync`; may include OS buffering) | dataset generation, verification read-back |
| `load` | the variant's loader (open, parse/decode, schema check, array materialised) | the correctness hash |
| `preprocess` | the shared function on an in-memory array (run once per size; not per variant) | array generation |
| `load_preprocess` | loader then preprocess, one timer | the correctness checks |

Process start-up, interpreter and import time are **outside** the timer. `subprocess_wall_ns` (spawn to exit) is recorded separately and is never added to an operation time; `median_non_operation_ms` in the summary is the difference and includes start-up, setup, priming, verification and teardown. Before the timer, each worker runs the same operation once on an 8-row array ("priming", ADR-018) so lazy imports and first-call paths are not measured; this does not warm the page cache for the data under test.

## Cache state
The benchmark is a **warm-cache** benchmark: files have just been written or read, and the OS page cache is expected to hold them (this is not verified by the tool). Starting a fresh process does not clear the page cache. A cold-cache protocol would need privileged, system-wide actions and is not implemented, so no cold-cache claim is made.

## Trials, order and noise
Defaults: 2 warm-up rounds and 7 measured rounds. Each round runs every (size, variant, operation) cell once in an order shuffled with `order_seed`; the realised order is stored (`round`, `position`). Warm-ups are recorded (`phase = warmup`) and excluded from summaries. Every trial runs in a fresh subprocess with a hard `timeout_s`. A failed, timed-out or incorrect trial is kept in the raw file and counted. Noise is **flagged, never removed**: a trial is flagged if the 1-minute load average per core before or after exceeded `noise.max_load_per_core`, or if its time is at least `noise.outlier_factor` times its cell median. The environment (CPU governor, power source, load, filesystem, thread variables, versions, git commit) is recorded in `run.json`.

## Statistics
Per cell (size x variant x operation) over accepted measured trials: median (the headline), Q1, Q3, IQR, min, max, mean and sample standard deviation. Quantiles use linear interpolation ("R-7", NumPy's default) and the method is written into every row. No significance tests are performed, and ratios are ratios of medians. Cells where every trial failed still appear with empty statistics.

## Throughput
- **Logical-payload throughput** = `rows x 34 B / median time`, the same numerator for every variant.
- **File throughput** = `on-disk bytes / median time`, which differs per variant.
They are separate columns and separate plots and must not be compared with each other.

## Memory metrics
All are Linux-only, in **KiB**, and describe the **worker** process unless noted. None is exact workload memory.

| field | source | current or peak | includes interpreter and libraries | notes |
|---|---|---|---|---|
| `ru_maxrss_kib` | `getrusage(RUSAGE_SELF).ru_maxrss` | peak since process start | yes | A child's value can be floored by the parent's peak at launch (observed). Flagged `maxrss_floor_suspect` when it does not exceed the parent's launch value. |
| `vm_hwm_kib` | `/proc/self/status` `VmHWM` | peak (high-water RSS) | yes | Independent of the parent's peak. The worker resets it after setup (`/proc/self/clear_refs`, best effort, `hwm_reset`) so it reflects the timed region plus the baseline. |
| `vm_rss_baseline_kib` | `VmRSS` | current, sampled just before the timer | yes | A point sample. |
| `vm_hwm_baseline_kib` | `VmHWM` | peak, sampled just before the timer | yes | Shows what setup alone reached. |
| `parent_ru_maxrss_kib_at_launch` | runner's `ru_maxrss` before spawning | peak | yes | Used for the floor flag; the runner stays small (no numpy). |

`estimated_workload_rss_kib = vm_hwm_kib - vm_rss_baseline_kib` is an **estimate**: both values are process-wide, the baseline is a point sample, and allocator and page-cache behaviour are not modelled. A metric that cannot be read is stored as `null`.

## Validity limits
Synthetic data; one machine per run; laptop power and thermal effects; `process_time_ns` is process-wide CPU time across all threads and is inflated by spinning worker threads unless `thread_env = "single"` (see [`research/research-notes.md`](research/research-notes.md) section 7.4); the data directory should not be on tmpfs (a warning is recorded). See also [`limitations.md`](limitations.md).
