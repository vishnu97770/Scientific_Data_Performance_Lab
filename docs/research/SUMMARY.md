# Project Research Summary

> **Historical research report.** Produced during an earlier planning workflow that has since been removed from this repository. Mentions of GSD, `.planning/`, `.claude/`, phases, plans or decision IDs refer to files and tooling that no longer exist here (a copy of the original planning directory is in `~/Documents/sdplab-planning-backup-2026-10-15.tar.gz`). Technical findings remain useful; the project's current state is described by the README, `docs/` and the code.


> **Decision update (2026-10-13):** the user has since resolved the open items raised by this research. Python floor is now **>=3.12** (CI on 3.12 and 3.13; no 3.11 claim, ADR-015); ADR-005 is amended to store raw `ru_maxrss`, worker `VmHWM`/`VmRSS` and the parent's `ru_maxrss` at launch (the parent-floor effect was re-verified, research-notes section 7); `config_schema_version` and `results_schema_version` are separate (ADR-014); `timeout_s`, noise thresholds and `thread_env` are in the initial config (ADR-016); correctness is validated per operation (ADR-017). Where this file says otherwise it is superseded by `docs/architecture/PROPOSAL.md` (revision 3) and `docs/adr/`. Worker input, loop order and `prepare` vs timed `write` remain deferred to Phase 3 planning.


**Project:** Scientific Data Performance Lab (`sdplab`)
**Domain:** Small reproducible scientific-data file-format I/O benchmark (Python/NumPy, Linux-first, single developer)
**Researched:** 2026-10-13
**Confidence:** MEDIUM-HIGH

> Persisted by the orchestrator: the synthesizer subagent's write was rejected by a subagent write restriction and it returned the full document inline (GSD #222 self-heal). Content is the synthesizer's; nothing was committed.

## Executive Summary

sdplab is a correctness-first benchmark harness shaped like pyperf and asv. A runner owns scheduling and persistence. A worker subprocess owns the timed region. An append-only store (JSONL plus `run.json`) holds raw results. A derivation layer (summary, plots, report) reads only that store. All four researchers took the confirmed PROPOSAL rev. 2 as given, and none found a hard conflict with the five-phase outline. What sets the project apart is discipline:

- a pre-run exact-equality gate
- a per-trial correctness flag
- raw trials always kept
- honest labelling of anything that is only an estimate

Build in dependency order: dataset and validator, then format variants (with the CSV exactness gate), then worker and runner, then analysis/report/CLI, then release hardening. The biggest risk is the memory metric: two independent probes found a child's `ru_maxrss` is floored by the parent's peak RSS, which could make RQ4 silently wrong while every record looks valid. That touches an approved decision (ADR-005), so it is listed below as open and not resolved.

Other key risks: timer scope (lazy `.npz` member access, setup or hashing inside the timed region), page-cache/filesystem misdescription (tmpfs, dirty pages), README overclaiming, first-call-dominated timings at 10^4 rows. Each has a prevention that stays inside the confirmed module set. Phase 3 is the largest and riskiest phase and the only one that clearly needs a research pass before planning.

## Open decisions requiring user approval

None of these are decided. Nothing below silently adopts any of them.

| # | Open decision | Baseline says | Research found | Evidence | Options | Blocks |
|---|---|---|---|---|---|---|
| OD1 | Memory metric (amends ADR-005) | `ru_maxrss` raw plus post-import `rss_baseline_kib`; the difference labelled an estimate | A child's `ru_maxrss` is floored by the parent's peak at spawn. A parent at ~354 MiB gave a child `ru_maxrss` of 353,692 KiB while the child's `VmHWM` was 9,548 KiB. `rss_baseline_kib` is a point sample and cannot reveal the floor, so `peak - baseline` can read 0. | **Verified** by two probes (Python 3.13.5, kernel 7.0.0-38, one machine). Kernel mechanism MEDIUM (2008 LKML thread). | (a) keep as is, accept silent-floor risk (not recommended). (b) amend ADR-005: also store worker `VmHWM`/`VmRSS` and runner `ru_maxrss` at each spawn (`parent_maxrss_kib`), flag floored trials in analysis, keep the runner lean (lazy-import `report`, no held arrays, heavy `validate` in its own invocation). (c) additionally reset the peak after setup via `/proc/self/clear_refs` (works unprivileged, only meaningful without a floor). | Phase 3 planning |
| OD2 | Schema version naming | One `schema_version=1` for TOML config and result records | The two evolve independently; coupling forces needless bumps | Reasoned (PITFALLS V1) | (a) one counter, documented lockstep. (b) split into config and results counters, decided before the first record is written. | Phases 1, 3 |
| OD3 | Python floor vs NumPy 2.5 | `requires-python >=3.11`, `numpy>=2.0` | NumPy 2.5.4 requires Python >=3.12; 2.4.x supports 3.11. A universal `uv.lock` should give 2.5.x for >=3.12 and 2.4.x for 3.11 | PyPI metadata verified; actual `uv lock` outcome **unverified** (PyPI throttled); NumPy 2.4.x untested | (a) keep 3.11 floor, 3.11 CI smoke leg, 3.13 primary, never hard-code a dataset SHA (STACK's recommendation). (b) raise floor to 3.12. (c) pin `numpy<2.5`. | Phase 1 |
| OD4 | Input array for `write`/`preprocess` | Unspecified | Setup allocation sets the high-water mark before the timed region (5M-element temporary raised `VmHWM` ~52→~91 MB) | Partly verified | (a) regenerate via `dataset.generate` in the worker (research preference). (b) read a canonical file. Also fix the exact sample point of `rss_baseline_kib`. | Phase 3 planning |
| OD5 | Loop order | Unspecified | Sizes-outer bounds disk/RAM but lets thermal drift confound size comparison (RQ5); rounds-outer needs all sizes resident | Reasoned | (a) rounds outer. (b) sizes outer. Revisit if 10^7 enabled. | Phase 3 planning |
| OD6 | `timeout_s` config key | Section 11 requires timeouts; section 10 TOML has no key; unknown keys fail fast | Adding later is a schema change | Verified by document comparison | Add `timeout_s`, fix the complete key set in Phase 1 | Phase 1 |
| OD7 | Smaller baseline ambiguities | Timed write appears twice (section 5 step D vs section 9); per-trial correctness defined only for `load`; `cli` rules vs `prepare`/`validate` | — | Verified by document comparison | Proposed: `prepare` writes untimed and only worker `write` is timed; `write` goes to scratch paths; define per-operation correctness; expose `prepare`/`validate` as runner entry points | Phases 2-3 |
| OD8 | Feature flags D1-D5 | Not in proposal | D1 wording for noisy small-N cells; D2 record thread env vars; D3 noise-flag thresholds in config; D4 explicit exit codes; D5 quick demo config | Reasoned | All low cost; none is in the MVP until approved. D3 and D4 matter most. | Phases 3-4 |

## Key Findings

### Recommended Stack

The PROPOSAL stack is confirmed; research verified versions and configuration only. `uv` handles environment, lock, Python install and CI. `uv_build` is required: without it the worker spawned via `sys.executable -m sdplab.worker` cannot import `sdplab`.

**Core technologies (versions verified on PyPI 2026-10-13 unless noted):**
- **CPython** >=3.11 floor, 3.13 as dev/CI primary (see OD3).
- **NumPy** `>=2.0` declared; lock expected to resolve 2.5.4 on >=3.12 and 2.4.x on 3.11 (**unverified**). Avoid `Generator.binomial`/`multinomial` (stream changed in 2.5).
- **matplotlib** `>=3.9` declared, latest 3.11.2; plots only, Agg backend, only `report.py` imports it.
- **uv** 0.13.0 with `uv_build>=0.13.0,<0.14`; commit `uv.lock`; pin `required-version`.
- **pytest** 9.1.1 with native `[tool.pytest]` and `strict=true`.
- **Ruff** 0.17.0 capped `<0.18`, explicit `lint.select` (default set unverified and moving).
- **CI:** `ubuntu-24.04`; pin `actions/checkout` and `astral-sh/setup-uv` by full commit SHA (setup-uv has no floating tags, verified); `uv sync --locked`; benchmarks never run in CI.

**Not to use:** pandas, psutil, pyperf, typer, pydantic, tomli/tomli-w, pytest-benchmark, tox/nox, poetry. The declared floors (`numpy>=2.0`, `matplotlib>=3.9`) are untested; run a `--resolution lowest-direct` check or raise them.

### Expected Features

Nearly everything peer tools (pyperf, asv, pytest-benchmark, hyperfine) treat as table stakes is already in the confirmed MVP.

**Must have (table stakes, all MVP):** process isolation with in-worker timing; discarded warm-ups and 7 kept repeats; median/IQR/min/max; seeded shuffled order; explicit warm-cache statement; pre-run exact-equality gate; deterministic dataset with SHA-256; raw JSONL + `run.json` + `schema_version` + regenerable `summary.csv`; staged argparse CLI (`info`, `prepare`, `validate`, `run`, `report`); preflight; honest README with a committed example run; lockfile; tests with no timing assertions.

**Differentiators (already MVP):** per-trial correctness flag; bit-exact contract; raw memory and baseline stored separately (subject to OD1); separate logical vs on-disk throughput; separate start-up overhead; summaries/plots regenerable from raw files; recorded, not tuned, system context.

**Defer:** `--fsync`; 10^7 rows; extra memory/throughput plots; float32; cold cache; `csv_pandas`; column-wise `.npz`; other formats; run-vs-run `compare`; per-trial distribution plot; separate `check` subcommand.

**Anti-features:** inner-loop calibration; regression gating; dashboards; significance tests; outlier removal; system tuning; wrapping pyperf/asv; ABC plugin architecture; "winner" banners; `allclose` for CSV.

### Architecture Approach

Data flows one way: config → dataset → formats → validation gate → worker trials → JSONL → analysis → report. Runner and worker share no Python imports; coupling is a request / one-JSON-line protocol, the most under-specified interface, needing a contract test plus fault-injection tests. `results.py` is the hub: freeze its schema early; it must carry a run `status` and all analysis parameters and tolerate a truncated final JSONL line.

**Major components:**
1. `dataset.py` — `EVENT_DTYPE`, seeded `generate()`, canonical check, `array_sha256` over dtype descr + shape + bytes.
2. `formats.py` — four variants with `write`/`load`; `load` returns an owning `ndarray` (never an `NpzFile`).
3. `validate.py`, `preprocess.py` — exact equality and the single deterministic workload.
4. `worker.py` — one timed operation per fresh process: timer, RSS read, hash; exactly one JSON line.
5. `runner.py` — preflight, scheduling, spawn/timeout/collect, failure-to-record conversion; lean at spawn time.
6. `results.py`, `analysis.py`, `report.py`, `cli.py`, `config.py` — schema/I/O hub, statistics, sole matplotlib importer (lazy-imported by `cli`), argparse dispatch, sole TOML reader.

### Critical Pitfalls

1. **Worker `ru_maxrss` floored by the parent's peak (M1).** See OD1. If approved: store `VmHWM`/`VmRSS`, record parent peak per spawn, flag floored trials, keep the runner lean; Phase 3 pytest reproduces the probe with a large margin (not exact numbers).
2. **Timer wraps the wrong region (M2).** `.npz` members are lazy and re-read on every access. Loaders return an owning `ndarray`, close the archive, access the member once. Add a loader return-type test and an injected-clock test.
3. **CSV exactness (R1).** `%.17g` + `loadtxt` was exact on edge values and ~200k random bit patterns on NumPy 2.1.3 and 2.5.4, one platform only. Design around: per-field `fmt` (single fmt mangles `int64` above 2**53); `comments=""`; `ndmin=1`; NaN payload lost; `array_equal` blind to `-0.0` so bytes/SHA must be the real gate; integer parsing differs by version (2.1.3 warns, 2.5.4 raises).
4. **Structured-array identity (S1).** Packed (34 B/row) vs aligned (40), endianness, padding, renamed fields all pass value-level checks. Enforce `assert_canonical` on every loader output; hash dtype descr + shape + bytes.
5. **Filesystem/cache story (M3) and README overclaiming (D1).** `/tmp` here is tmpfs; default `write` leaves dirty pages; process restarts do not clear the page cache. Record filesystem type and warn on tmpfs/overlay; keep `data_dir` off `/tmp`; label write "no fsync"; generate every README number from the committed run; status words limited to planned / implemented / tested / verified-by-committed-run.

Also: `savez(allow_pickle=...)` stores a stray member on NumPy 2.1.x (never pass it; assert `z.files == ["events"]`); `.npy`/`.npz` paths auto-append extensions; per-column `SeedSequence` streams and never a hard-coded dataset SHA; pick one IQR quantile method (n=7 differs by method); `write` must target scratch paths.

## Implications for Roadmap

The PROPOSAL section 16 order is a valid topological order. The suggestions below keep it with the refinements research supports.

### Phase 1: Foundation and dataset
- **Rationale:** `dataset`, `config`, `preprocess`, `validate` are leaves. Fix the full config key set now (unknown keys fail fast).
- **Delivers:** skeleton (`uv_build`, src layout, SHA-pinned CI, Ruff/pytest config); complete versioned config schema; deterministic generator with per-column `SeedSequence` streams; `assert_canonical` and `array_sha256`; `preprocess` and exact-equality validator; `info` subcommand.
- **Avoids:** G1, S1, C1. Run `uv lock` here and record the NumPy fork.
- **Needs from user:** OD2, OD3, OD6.

### Phase 2: Format variants
- **Rationale:** the CSV exactness gate (R1) gates everything after it.
- **Delivers:** four writers/loaders with a registry; edge-value and random-bit-pattern round-trip tests under the locked NumPy; `prepare` and `validate` subcommands (pending OD7).
- **Avoids:** R1, S2, M2, M5. If R1 fails, escalate via an ADR; never loosen equality.

### Phase 3: Measurement and runner (split 3a / 3b)
- **Rationale:** largest and riskiest. Build `results.py` schema/I/O first, then the worker with a protocol contract test, then the runner.
- **3a delivers:** results schema; environment capture tolerating missing files; worker (timer, RSS read, hash); contract test.
- **3b delivers:** preflight; scheduling; timeouts and fault-injection tests; failure-to-record conversion; scratch-path write policy; `run` subcommand.
- **Avoids:** M1 (pending OD1), M2, M3, M4, M6, M8, V1 (schema freeze, golden fixtures), D2.
- **Needs from user:** OD1, OD4, OD5, OD7, D3/D4 from OD8.

### Phase 4: Analysis, reports, CLI polish
- **Rationale:** `analysis` needs only the frozen `results` schema; can start from fixture JSONL.
- **Delivers:** summaries with `n_ok`/`n_failed`/`n_incorrect` (empty cells kept); noise and floored-trial flags; ratios of medians; load-time, file-size, load+preprocess plots with raw points; markdown report with mandatory caveat block; e2e smoke test (structure only).
- **Avoids:** M7 (one `quantile()` helper, method stored, fixed-vector tests), M5, M6, D1.

### Phase 5: Release hardening
- **Rationale:** needs a real run on the user's machine (human-dependent).
- **Delivers:** committed `results/examples/<run_id>/` (manual whole-directory copy, then check `report --run` regenerates an identical `summary.csv`); merged and corrected README; number-provenance check; size/type check on examples; golden-file load test.
- **Avoids:** D1, D2, V1.

### Phase Ordering Rationale
- Validator before runner, so Phase 2 precedes Phase 3.
- Results schema frozen first in Phase 3 so analysis can be built against fixtures.
- CLI subcommands land incrementally (`info`, then `prepare`/`validate`, then `run`).
- OD2, OD3, OD6 gate Phase 1; OD1, OD4, OD5 gate Phase 3 planning.

### Research Flags
- **Needs research-phase:** Phase 3 only (ADR-005 amendment, `clear_refs` under a floored process, input acquisition, loop order, worker protocol key set and exit-path mapping, per-operation correctness).
- **Skip research-phase:** Phases 1, 2 (unless R1 fails), 4, 5.

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack | HIGH, three MEDIUM items | PyPI and git tags verified. Unverified: actual `uv lock` result, exact Ruff 0.17 default set, dependency floors. |
| Features | MEDIUM | MVP classification HIGH; peer-tool claims MEDIUM where two tools agree; published format-study practices and D1 LOW. |
| Architecture | HIGH structure; MEDIUM kernel mechanism | Parent-floor behaviour and `VmHWM` independence observed locally; mechanism rests on a 2008 LKML thread. |
| Pitfalls | HIGH observed; MEDIUM general knowledge | Experiments on Python 3.13.5, NumPy 2.1.3 and 2.5.4, one machine. |

**Overall confidence:** MEDIUM-HIGH. All observations are single-machine, none are benchmark results, none may be quoted in the README.

### Verified vs unverified

**Verified (local experiment or fetched primary source):**
- Child `ru_maxrss` floor and `VmHWM` independence (two probes); `clear_refs` reset works unprivileged.
- CSV `%.17g` exactness on edge cases and ~200k random bit patterns (NumPy 2.1.3 and 2.5.4); `-0.0` preserved, NaN payload lost; `loadtxt`/`savetxt` traps hold.
- Packed vs aligned dtype, endianness, padding, renamed-field hash collision.
- `.npz` members lazy and uncached; `savez` `allow_pickle` stray member on 2.1.3 only; `np.save`/`np.savez` auto-append extensions.
- Package versions/tags; `setup-uv` has no floating tags; NumPy 2.5 requires Python >=3.12.
- Environment: tmpfs `/tmp`, ext4 repo disk, `powersave` governor on battery, dirty-page jump after `np.save`, start-up costs (bare interpreter ~11 ms, `import numpy` ~61-77 ms, `matplotlib.pyplot` ~290 ms).

**Unverified (do not state as fact):**
- NumPy 2.4.x, other kernels/filesystems, macOS/Windows.
- Actual `uv lock` fork outcome; exact Ruff 0.17 defaults; untested dependency floors.
- Exec high-water-mark mechanism on current kernel source.
- Correct rounding of Python `%` / `PyOS_string_to_double` on every platform.
- Relative `loadtxt` speed/memory; compression ratio beyond an informal one-off.
- Whether the e2e run (~64 workers) fits under 30 s.
- pytest-benchmark machine-info claim; published format-study practices; D1 noise magnitude.
- Open research-notes gaps 5-8.

### Gaps to Address
- Run `uv lock` in Phase 1 and record the NumPy fork (OD3).
- Resolve OD1 before Phase 3 planning; write the reproducing probe as a pytest.
- Add a `--resolution lowest-direct` check in Phase 5, or raise dependency floors.
- Verify the Ruff rule set and `filterwarnings=["error"]` on first real code.
- Measure e2e runtime budget on the first CI run.
- Measure small-N (10^4) noise before wording D1.
- Choose and document the IQR quantile method in Phase 4.

## Sources

- **Primary (HIGH):** PyPI JSON and `git ls-remote` (2026-10-13); uv, setup-uv, pytest, Ruff docs; NumPy 2.5.0 and 1.23.0 release notes; Python stdlib docs; PROPOSAL.md and research-notes.md; local scratchpad experiments (this machine only).
- **Secondary (MEDIUM):** pyperf, asv, hyperfine docs; NumPy `conversions.c` (via fetch summary); LKML getrusage thread (2008).
- **Tertiary (LOW):** pytest-benchmark internals; arXiv 2207.09503 and a Parquet-vs-CSV tick-data paper (via search summaries).

Detailed files: `STACK.md`, `FEATURES.md`, `ARCHITECTURE.md`, `PITFALLS.md` in this directory.

---
*Research completed: 2026-10-13*
*Ready for roadmap: yes, once OD2, OD3, OD6 are decided (Phase 1) and OD1, OD4, OD5 before Phase 3 planning.*
