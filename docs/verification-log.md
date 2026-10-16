# Verification log (local, uncommitted)

Evidence as of 2026-10-16, written by hand from commands actually run in this working tree; it was not produced by a verification tool. Nothing here has been committed or run on hosted CI.

## Commands run and results

| Check | Result |
|---|---|
| `uv sync --locked` in throwaway environments outside the repo, Python 3.12.15 and 3.13.5 | succeeded; NumPy 2.5.4, matplotlib 3.11.2 on both |
| `ruff check`, `ruff format --check` on both Pythons | clean |
| `pytest` on both Pythons | 419 passed, 4 deselected (`slow`), about 35 s each |
| `pytest -m slow` (10^6-row round trips, all four variants) | 4 passed |
| Declared floors: `uv run --isolated --no-build --resolution lowest-direct pytest` on both Pythons (NumPy 2.1.0, matplotlib 3.10.8) | 419 passed each; `uv.lock` byte-identical afterwards |
| `uv lock --check` | lock current, 18 packages, one NumPy |
| Mutation checks in throwaway copies (earlier milestone; validator -> `array_equal`; validator -> per-field `allclose`; hash without dtype text; hash without shape; no canonical check; `>` -> `>=` in selection) | each caught by a dedicated test |
| Malformed-input tests for all loaders (wrong dtype, 2-D, big-endian, missing fields, padded dtype, wrong CSV header, missing/extra column, non-numeric, `1.0` in an integer column, int16 overflow, blank cell, garbage, truncated, empty, wrong member name, `.npy` loaded as `.npz`, pickled objects) | all rejected with `FormatError`; found and fixed a file-handle leak in corrupt-file loading |
| Full documented benchmark with the hardened code (`configs/benchmark.toml`, 10^4/10^5/10^6 rows, 2 warm-up + 7 measured rounds) | run `20261015T183730Z-51d4`: 351 trials, 0 failed, 0 incorrect, 0 high-load flags, 0 floor-suspect flags; `sdplab check-run` consistent; curated copy in `results/examples/20261015T183730Z-51d4/` |
| End-to-end CLI tests (`prepare -> validate -> run -> check-run -> report`) | pass (each about 7 s) |
| Docs hygiene (`tests/test_docs.py`): local links, anchors, fence balance, Mermaid block starts | pass |
| README results block vs committed example run (`tests/test_readme_results.py`) | passes |
| Streamlit dashboard (ADR-021): 40 dashboard tests (discovery safety, data loading, AppTest page rendering); full suite 465 passed on Python 3.12.15 and 3.13.5; engine-only env (no Streamlit) 419 passed + dashboard tests skipped; 4 slow tests pass; ruff clean; `uv lock --check` ok; real server started on 127.0.0.1 (health `ok`), pages checked at desktop and phone width with a headless browser; fresh example-config run -> `check-run` -> `report` -> dashboard load ok | pass |
| CI workflow rework (jobs `core`, `floors`, `dashboard`; `workflow_dispatch`; check-run of the example; uv pinned to 0.13.0): every step run locally: engine-only install, Ruff, format, 425 passed + 2 skipped on 3.12 and 3.13, CLI smoke, `check-run` on the example, floors run (lock unchanged), dashboard tests (40 passed on both) and a real app health check; workflow YAML parses; action SHAs match the upstream tags `v7.0.1` and `v10.3.0` | pass locally; **not run on GitHub** |
| GSD cleanup (user-approved 2026-10-16): npx cache for `@opengsd/gsd-core`, `~/.cache/gsd`, `.planning/` (backed up outside the repo, useful content moved to `docs/`) | done; Node, fnm, npm, Claude Code, `~/.claude`, the Matt Pocock plugin and Git history verified intact |

## Not done

- The dashboard is **not deployed** (needs a push and a Streamlit Community Cloud sign-in by the owner); whether Community Cloud honours uv default dependency groups is unverified (`deployment.md`).
- GitHub Actions has **never run** (needs a push). `.github/workflows/ci.yml` is checked by a test for shape (SHA-pinned actions, 3.12 and 3.13 matrix, required commands) and its commands were run locally.
- No 10^7-row run; `--allow-large` is covered only by pre-flight unit tests.
- One benchmark run per code version on one machine (laptop, `powersave` governor, AC power, warm cache).
- No independent code review; the same author wrote code and tests.

## Known limits recorded elsewhere

[`limitations.md`](limitations.md), [`benchmark-methodology.md`](benchmark-methodology.md), README "What is not covered", ADR-018/019/020, and [`research/research-notes.md`](research/research-notes.md) sections 7.1-7.5.
