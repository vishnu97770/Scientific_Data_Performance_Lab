"""Safe discovery of recorded runs.

Runs are directories named like ``20261015T183730Z-51d4`` that are *direct children* of one results
root and contain ``run.json``. Nothing outside that root is ever read, symlinks are ignored, and
only a fixed whitelist of file names inside a run is ever opened.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

RESULTS_ENV = "SDPLAB_RESULTS_DIR"
RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{4}$")
PLOT_RE = re.compile(r"^[a-z_]+\.png$")

# Fixed artifact names (and size caps in bytes) that may be read or offered for download.
ARTIFACT_LIMITS: dict[str, int] = {
    "run.json": 2_000_000,
    "trials.jsonl": 50_000_000,
    "summary.csv": 5_000_000,
    "report.md": 2_000_000,
}
MAX_PLOT_BYTES = 5_000_000


@dataclass(frozen=True)
class RunRef:
    """A discovered run directory (path is internal and never shown to visitors)."""

    run_id: str
    path: Path


def default_results_root() -> Path:
    """``$SDPLAB_RESULTS_DIR`` if set, otherwise ``<repository>/results/examples``."""
    env = os.environ.get(RESULTS_ENV)
    if env:
        return Path(env).expanduser().resolve()
    repo = Path(__file__).resolve().parents[3]
    if (repo / "results").is_dir():
        return repo / "results" / "examples"
    return (Path.cwd() / "results" / "examples").resolve()


def discover_runs(root: Path) -> list[RunRef]:
    """Direct, non-symlink child directories of ``root`` that look like runs, newest first."""
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        return []
    if not root.is_dir():
        return []
    found: list[RunRef] = []
    for child in root.iterdir():
        if child.is_symlink() or not child.is_dir() or not RUN_ID_RE.match(child.name):
            continue
        if child.resolve().parent != root or not (child / "run.json").is_file():
            continue
        found.append(RunRef(child.name, child))
    return sorted(found, key=lambda r: r.run_id, reverse=True)


def artifact_path(run: RunRef, name: str) -> Path | None:
    """Path of a whitelisted regular, non-symlink artifact within the size cap, else None."""
    if name not in ARTIFACT_LIMITS:
        return None
    path = run.path / name
    try:
        if path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size > ARTIFACT_LIMITS[name]:
            return None
    except OSError:
        return None
    return path


def plot_paths(run: RunRef) -> list[Path]:
    """Whitelisted plot images (``plots/<name>.png``, size-capped), sorted by name."""
    plots = run.path / "plots"
    try:
        if plots.is_symlink() or not plots.is_dir():
            return []
        entries = sorted(plots.iterdir())
    except OSError:
        return []
    return [
        p
        for p in entries
        if PLOT_RE.match(p.name)
        and not p.is_symlink()
        and p.is_file()
        and p.stat().st_size <= MAX_PLOT_BYTES
    ]


def signature(run: RunRef) -> tuple:
    """Cheap change signature (name, mtime_ns, size) of the files a run is built from."""
    sig = []
    for name in sorted(ARTIFACT_LIMITS):
        p = run.path / name
        try:
            st = p.stat()
            sig.append((name, st.st_mtime_ns, st.st_size))
        except OSError:
            sig.append((name, None, None))
    return tuple(sig)
