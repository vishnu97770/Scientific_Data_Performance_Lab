# Architecture decision records

Status of the project: **Phases 1-4 are implemented and tested locally (see `docs/verification-log.md`); hosted CI has not been run.** Source of record for rationale: `docs/architecture/PROPOSAL.md` (revision 3) and `docs/research/research-notes.md`.

| ADR | Title | Status |
|---|---|---|
| [001](ADR-001.md) | One flat package `sdplab` | Accepted (2026-10-13) |
| [002](ADR-002.md) | Canonical in-memory form is one structured array (`EVENT_DTYPE`) | Accepted (user decision 2026-10-13) |
| [003](ADR-003.md) | MVP variants: csv, npy, npz, npz_compressed | Accepted |
| [004](ADR-004.md) | One fresh subprocess per trial; timing inside the worker; start-up reported separately | Accepted |
| [005](ADR-005.md) | Memory measurement (amended 2026-10-13) | Accepted - amended by user decision 2026-10-13 |
| [006](ADR-006.md) | Warm-cache benchmark only | Accepted |
| [007](ADR-007.md) | Strict exact-equality correctness contract | Accepted (reaffirmed 2026-10-13) |
| [008](ADR-008.md) | Raw results as JSONL + run.json; derived, regenerable summary.csv | Accepted (user decision 2026-10-13) |
| [009](ADR-009.md) | argparse + TOML (`tomllib`) | Accepted |
| [010](ADR-010.md) | Median/IQR headline; no significance tests | Accepted |
| [011](ADR-011.md) | Narrow gitignore; curated example runs are tracked | Accepted (user decision 2026-10-13) |
| [012](ADR-012.md) | Default write timing excludes fsync | Accepted |
| [013](ADR-013.md) | pandas excluded from the MVP | Accepted |
| [014](ADR-014.md) | Separate `config_schema_version` and `results_schema_version` | Accepted (user decision 2026-10-13) |
| [015](ADR-015.md) | Python >= 3.12; primary 3.13; CI tests 3.12 and 3.13 | Accepted (user decision 2026-10-13) |
| [016](ADR-016.md) | Initial config key set includes `timeout_s`, noise thresholds, thread-env control; documented exit codes; example config | Accepted (user decision 2026-10-13) |
| [017](ADR-017.md) | Per-operation correctness validation | Accepted (user decision 2026-10-13) |
| [018](ADR-018.md) | Workers prime lazy imports and first-call paths before the timer | Accepted (engineering decision, 2026-10-15) |
| [019](ADR-019.md) | Phase 3 design points settled: worker input, loop order, prepare vs timed write | Accepted (engineering decisions, 2026-10-15; these were deferred to Phase 3 by the user) |
| [020](ADR-020.md) | Loaders validate the schema and never cast; generator is versioned | Accepted (engineering decision, 2026-10-16) |
| [021](ADR-021.md) | Read-only Streamlit results explorer as an optional dependency group | Accepted (engineering decision, 2026-10-16) |
