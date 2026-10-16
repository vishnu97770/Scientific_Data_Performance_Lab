# Deployment (Streamlit Community Cloud)

**Status: deployed** at <https://scientificdataperformancelab-roqu95p6pjugyri9fg7xwd.streamlit.app/> (owner-created; opened in fresh browser contexts on 2026-10-16 and all five pages rendered without errors). Which commit the host is running and its Python version are visible only in the Community Cloud account, so they are not verified here.

The app is a read-only viewer of the committed example run (`results/examples/`). It cannot run benchmarks, accept uploads or read arbitrary paths, so a public host exposes nothing but the recorded results.

## What the host needs

| item | value |
|---|---|
| Repository | the GitHub repository, branch `main` |
| Main file path | `streamlit_app.py` (repository root) |
| Dependencies | `uv.lock` (Community Cloud prefers it over other dependency files; `pyproject.toml` is lowest in its detection order) |
| Python | 3.13 (the primary version; 3.12 is also tested). Choose it under *Advanced settings* |
| Config | `.streamlit/config.toml` at the repository root (theme, headless, XSRF protection, no usage statistics) |
| Data | `results/examples/<run_id>/` is tracked in Git; no secrets or environment variables are required |

Optional environment variables (Advanced settings, *Secrets* are not needed): `SDPLAB_RESULTS_DIR` (another results root) and `SDPLAB_REPO_URL` (source link shown in the sidebar).

## Steps

1. Commit and push (requires the owner's decision; nothing has been committed yet).
2. Sign in at <https://share.streamlit.io> with GitHub and choose *Create app* then *Deploy a public app from GitHub*.
3. Pick the repository and branch, set the main file path to `streamlit_app.py`, and open *Advanced settings* to choose Python 3.13.
4. Deploy and wait for the build log to finish.

Reference: <https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app>.

## Dependency groups: note and fallback

The deployment started and rendered, so the host installed Streamlit and the package. `pyproject.toml` declares `[tool.uv] default-groups = ["dev", "dashboard"]`, so `uv sync` (and, presumably, the host's lock-based install) installs Streamlit. The exact install mechanism is not visible from outside. If a future build log shows `ModuleNotFoundError: streamlit` or `sdplab`, use one of these fixes and redeploy:

- move `streamlit` from the `dashboard` group into `[project] dependencies` and run `uv lock` (simplest; makes Streamlit a core dependency of the package), or
- remove `uv.lock` from the deployed branch and add a root `requirements.txt` with `streamlit>=1.66,<2` and `-e .` (the host's detection order then falls through to it; this loses the pinned versions).

## Post-deployment checks

- Overview shows run `20261015T183730Z-51d4`, 351 trials, 0 failed, 0 incorrect.
- Format comparison: changing operation, size and formats updates the table, findings and charts.
- Detailed results: the downloads (`summary.csv`, `run.json`, `trials.jsonl`, `report.md`, plots) work.
- No absolute local path or Python traceback appears on any page, including at phone width.
- The footer/sidebar states the project is independent and not affiliated with CERN.

## Running the same app locally

```bash
uv sync --locked
uv run streamlit run streamlit_app.py --server.address 127.0.0.1
```

Streamlit binds all network interfaces by default; `--server.address 127.0.0.1` keeps the local server private. Restart the server after editing Python modules of the package.
