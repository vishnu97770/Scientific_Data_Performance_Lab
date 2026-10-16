"""Raw result storage (JSON Lines + run.json) and environment capture.

``trials.jsonl`` holds one self-contained JSON object per trial and is append-only, so a crash
loses at most the line being written. ``run.json`` holds the configuration, environment, dataset
hashes and run status. Summaries and plots are derived from these files only. The result schema
is versioned separately from the configuration schema (ADR-014). This module deliberately does
not import numpy: the runner process stays small (ADR-005).
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

RESULTS_SCHEMA_VERSION = 1
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)
RUN_STATUSES = ("running", "completed", "completed_with_failures", "aborted")
TRIAL_KEYS = (
    "results_schema_version",
    "run_id",
    "variant",
    "operation",
    "dataset",
    "round",
    "position",
    "phase",
    "status",
    "correct",
    "correctness_check",
    "timing",
    "resources",
    "flags",
    "sizes",
    "measurement",
    "error",
)


class ResultsError(ValueError):
    """A results file is malformed, truncated in the middle, or has an unknown schema version."""


def new_run_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{secrets.token_hex(2)}"


def check_trial(rec: Any) -> dict:
    if not isinstance(rec, dict):
        raise ResultsError("trial record is not a JSON object")
    version = rec.get("results_schema_version")
    if version != RESULTS_SCHEMA_VERSION:
        raise ResultsError(f"unsupported results_schema_version {version!r}")
    missing = [k for k in TRIAL_KEYS if k not in rec]
    if missing:
        raise ResultsError(f"trial record is missing keys: {missing}")
    return rec


def append_trial(path: str | Path, rec: dict) -> None:
    """Append one trial as one line. NaN/Infinity are refused (they are not valid JSON)."""
    check_trial(rec)
    line = json.dumps(rec, sort_keys=True, allow_nan=False, separators=(",", ":"))
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(line + "\n")
        fh.flush()


def read_trials(path: str | Path) -> tuple[list[dict], bool]:
    """Read every trial. Returns ``(trials, truncated)``.

    A final line that is not valid JSON and is not newline-terminated is the signature of an
    interrupted run: it is dropped and ``truncated`` is True. Any other malformed line raises.
    """
    text = Path(path).read_text(encoding="utf-8")
    lines = text.split("\n")
    ended_with_newline = text.endswith("\n")
    if ended_with_newline:
        lines.pop()
    trials: list[dict] = []
    truncated = False
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            if last and not ended_with_newline:
                truncated = True
                continue
            raise ResultsError(f"{path}: line {i + 1} is not valid JSON") from exc
        trials.append(check_trial(rec))
    return trials, truncated


def write_run_json(path: str | Path, run: dict) -> None:
    """Atomically write run.json (temp file + rename)."""
    run = {**run, "results_schema_version": RESULTS_SCHEMA_VERSION}
    if run.get("status") not in RUN_STATUSES:
        raise ResultsError(f"run status must be one of {RUN_STATUSES}")
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(run, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, path)


def read_run_json(path: str | Path) -> dict:
    run = json.loads(Path(path).read_text(encoding="utf-8"))
    version = run.get("results_schema_version")
    if version != RESULTS_SCHEMA_VERSION:
        raise ResultsError(f"unsupported results_schema_version {version!r}")
    return run


# ---------------------------------------------------------------- environment capture


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _cpu_model() -> str | None:
    text = _read("/proc/cpuinfo")
    if text:
        m = re.search(r"^model name\s*:\s*(.+)$", text, flags=re.M)
        if m:
            return m.group(1).strip()
    return None


def _ram_bytes() -> int | None:
    text = _read("/proc/meminfo")
    if text:
        m = re.search(r"^MemTotal:\s+(\d+) kB", text, flags=re.M)
        if m:
            return int(m.group(1)) * 1024
    return None


def mem_available_bytes() -> int | None:
    text = _read("/proc/meminfo")
    if text:
        m = re.search(r"^MemAvailable:\s+(\d+) kB", text, flags=re.M)
        if m:
            return int(m.group(1)) * 1024
    return None


def nearest_existing(path: str | Path) -> Path:
    """Resolve ``path`` and walk up to the nearest directory that exists."""
    p = Path(path).resolve()
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def filesystem_type(path: str | Path) -> str | None:
    """Filesystem type of the mount containing ``path`` (nearest existing parent)."""
    p = nearest_existing(path)
    text = _read("/proc/mounts")
    if not text:
        return None
    best: tuple[int, str] | None = None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        mount = parts[1].replace("\\040", " ")
        inside = p == Path(mount) or str(p).startswith(mount.rstrip("/") + "/") or mount == "/"
        if inside and (best is None or len(mount) > best[0]):
            best = (len(mount), parts[2])
    return best[1] if best else None


def _power_source() -> str | None:
    root = Path("/sys/class/power_supply")
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return None
    for e in entries:
        kind = _read(str(e / "type"))
        online = _read(str(e / "online"))
        if kind == "Mains" and online == "1":
            return "ac"
    for e in entries:
        if _read(str(e / "type")) == "Battery":
            return f"battery ({_read(str(e / 'status')) or 'unknown'})"
    return "unavailable" if not entries else "unknown"


def _git_state(cwd: str | Path) -> dict:
    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=20
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain") if commit else None
    return {"commit": commit, "dirty": (bool(status) if status is not None else None)}


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def loadavg() -> list[float] | None:
    try:
        return [round(x, 3) for x in os.getloadavg()]
    except OSError:
        return None


def capture_environment(data_dir: str | Path, project_dir: str | Path = ".") -> dict:
    """Describe the machine and software that produced a run. Missing sources are None."""
    unavailable = None
    fs_type = filesystem_type(data_dir)
    uname = platform.uname()
    return {
        "python": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "numpy": _version("numpy"),
        "matplotlib": _version("matplotlib"),
        "sdplab": _version("sdplab"),
        "os": f"{uname.system} {uname.release}",
        "machine": uname.machine,
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "ram_bytes": _ram_bytes(),
        "data_dir": str(Path(data_dir)),
        "filesystem_type": fs_type,
        "cpu_governor": _read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")
        or unavailable,
        "power_source": _power_source(),
        "loadavg_at_start": loadavg(),
        "thread_env": {name: os.environ.get(name) for name in THREAD_VARIABLES},
        "git": _git_state(project_dir),
        "disk_free_bytes": shutil.disk_usage(nearest_existing(data_dir)).free,
    }


# ---------------------------------------------------------------- consistency check of a run


def _expected_trials_per_round(cfg: dict) -> int:
    per_size = sum(
        1 if op == "preprocess" else len(cfg["formats"]["enabled"])
        for op in cfg["workload"]["operations"]
    )
    return per_size * len(cfg["dataset"]["sizes"])


def validate_run(run_dir: str | Path) -> list[str]:
    """Check that a run directory is internally consistent; return a list of problems.

    Uses only ``run.json`` and ``trials.jsonl``. An empty list means every check passed; it does
    not mean the benchmark conditions were good (that is what the flags and report are for).
    """
    run_dir = Path(run_dir)
    problems: list[str] = []
    try:
        run = read_run_json(run_dir / "run.json")
    except (OSError, ValueError) as exc:
        return [f"run.json: {exc}"]
    try:
        trials, truncated = read_trials(run_dir / "trials.jsonl")
    except (OSError, ValueError) as exc:
        return [f"trials.jsonl: {exc}"]
    if truncated:
        problems.append("trials.jsonl ends with a truncated line (interrupted run)")
    status = run.get("status")
    if status not in ("completed", "completed_with_failures"):
        problems.append(f"run status is {status!r}: the run did not finish")
    cfg = run.get("config", {})
    datasets = run.get("datasets", {})
    seen: set[tuple] = set()
    for i, t in enumerate(trials, start=1):
        where = f"trial {i}"
        if t["run_id"] != run.get("run_id"):
            problems.append(f"{where}: run_id {t['run_id']!r} differs from run.json")
        if t["phase"] not in ("warmup", "measured"):
            problems.append(f"{where}: unknown phase {t['phase']!r}")
        if t["status"] not in ("ok", "failed", "timeout"):
            problems.append(f"{where}: unknown status {t['status']!r}")
        rows = str(t["dataset"]["rows"])
        recorded = datasets.get(rows, {}).get("dataset", {}).get("sha256")
        if recorded is None:
            problems.append(f"{where}: no dataset record for {rows} rows in run.json")
        elif t["dataset"]["sha256"] != recorded:
            problems.append(f"{where}: dataset hash differs from run.json for {rows} rows")
        if t["operation"] not in cfg.get("workload", {}).get("operations", []):
            problems.append(
                f"{where}: operation {t['operation']!r} is not in the run configuration"
            )
        if t["status"] == "ok":
            if not isinstance(t["correct"], bool):
                problems.append(f"{where}: ok trial without a boolean 'correct'")
            elapsed = t["timing"]["elapsed_ns"]
            if not isinstance(elapsed, int) or elapsed <= 0:
                problems.append(f"{where}: ok trial without a positive integer elapsed_ns")
        elif t["correct"] is not None or t["timing"]["elapsed_ns"] is not None:
            problems.append(f"{where}: {t['status']} trial must have null 'correct' and elapsed_ns")
        key = (t["phase"], t["round"], t["position"])
        if key in seen:
            problems.append(f"{where}: duplicate (phase, round, position) {key}")
        seen.add(key)
    counts = run.get("counts")
    if counts is not None:
        computed = {
            "trials": len(trials),
            "failed": sum(1 for t in trials if t["status"] != "ok"),
            "incorrect": sum(1 for t in trials if t["status"] == "ok" and t["correct"] is False),
        }
        if counts != computed:
            problems.append(f"run.json counts {counts} differ from the trials {computed}")
    if status in ("completed", "completed_with_failures") and cfg:
        expected = _expected_trials_per_round(cfg) * (
            cfg["trials"]["warmup_rounds"] + cfg["trials"]["measured_rounds"]
        )
        if len(trials) != expected and not truncated:
            problems.append(
                f"expected {expected} trials for this configuration, found {len(trials)}"
            )
    return problems
