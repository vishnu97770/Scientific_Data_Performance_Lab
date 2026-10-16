# Limitations

Stated plainly; none of these is hidden by the results.

## Scope
- Synthetic, HEP-inspired data with no missing values. It says nothing about real detector data or CERN-scale workloads. The project is independent and is not affiliated with or endorsed by CERN or CERN-HSF.
- Four storage variants of one row-wise structured array. No JSON, HDF5, Parquet, ROOT, pandas loaders, column-wise `.npz`, partial or column reads, memory-mapping, or streaming.
- A text (`%.17g`) CSV cannot carry NaN payloads; the dataset contains no NaN.

## Measurement
- **Warm cache only.** No cold-cache mode.
- **Write timing is not persistence time** (no `fsync`; `trials.fsync = true` is refused).
- **Imports are excluded from timings** (priming, ADR-018); a one-shot command-line user would pay them once.
- `process_time_ns` is process-wide CPU time and can be inflated by spinning threads; compare `elapsed_ns`.
- Memory counters are Linux-only process high-water marks, include the interpreter, and the workload estimate is an estimate. A child's `ru_maxrss` can be floored by its parent's peak.
- Results come from one machine and, by default, 7 measured rounds. There are no significance tests. Background load, thermal state and the CPU governor affect timings; they are recorded and flagged, not controlled.
- 10^7 rows is accepted only with `--allow-large` and has not been run.

## Reproducibility
- The same seed gives identical data only within one NumPy version and platform; `GENERATOR_VERSION` and the NumPy version are recorded, and a differing regenerated hash is reported.
- Preprocessing outputs are bit-identical for bit-identical inputs in one environment, not across NumPy versions or CPUs.

## Dashboard
- Read-only viewer of recorded runs; it shows one machine's results and cannot rerun or compare machines.
- Public deployment is prepared but not performed; see [deployment.md](deployment.md).
- "Fastest"/"smallest" statements are scoped to one operation, dataset size and run and are not general claims.

## Platform and tooling
- Linux only (uses `/proc`, `getrusage` in KiB). Other platforms are untested.
- The GitHub Actions workflow is configured but its status is reported by GitHub, not by this repository; see the README status line for whether it has been run.
