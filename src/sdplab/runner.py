"""Benchmark orchestration: pre-flight, prepare, validation gate, scheduling, persistence.

The runner never imports numpy and holds no datasets: all array work happens in worker
subprocesses, so a worker's ``ru_maxrss`` is not floored by a large parent (ADR-005). Every trial
- warm-up or measured - runs in a fresh worker process, and every observation is appended to
``trials.jsonl``; nothing is discarded. Cache mode is always ``warm``: a process restart does not
clear the OS page cache.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sdplab.results import (
    RESULTS_SCHEMA_VERSION,
    THREAD_VARIABLES,
    append_trial,
    capture_environment,
    loadavg,
    mem_available_bytes,
    nearest_existing,
    new_run_id,
    write_run_json,
)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_GATE = 3
EXIT_PARTIAL = 4
EXIT_PREFLIGHT = 5

ROW_BYTES = 34
LARGE_ROWS = 10_000_000
IN_MEMORY = "in_memory"
DISK_HEADROOM = 2 * 1024**3
DEFAULT_WORKER_CMD = (sys.executable, "-I", "-m", "sdplab.worker")


@dataclass(frozen=True)
class Cell:
    rows: int
    variant: str
    operation: str


@dataclass
class RunOutcome:
    exit_code: int
    run_id: str | None = None
    run_dir: Path | None = None
    message: str = ""
    counts: dict[str, int] = field(default_factory=dict)


def estimate_resources(rows: int) -> dict[str, int]:
    """Conservative estimates (not measurements) of RAM and disk needed for one size."""
    logical = rows * ROW_BYTES
    return {"ram_bytes": logical * 10 + 256 * 1024**2, "disk_bytes": logical * 12 + 64 * 1024**2}


def preflight(
    cfg: dict, *, allow_large: bool, mem_available: int | None, disk_free: int | None
) -> list[str]:
    """Return a list of reasons the run must be refused (empty = go)."""
    problems: list[str] = []
    if cfg["trials"]["fsync"]:
        problems.append(
            "trials.fsync = true is not implemented in this release (planned experiment)"
        )
    sizes = cfg["dataset"]["sizes"]
    if max(sizes) >= LARGE_ROWS and not allow_large:
        problems.append(f"sizes of {LARGE_ROWS} rows or more need the --allow-large flag")
    biggest = estimate_resources(max(sizes))
    if mem_available is not None and biggest["ram_bytes"] > mem_available:
        problems.append(
            f"estimated RAM {biggest['ram_bytes'] // 2**20} MiB exceeds available "
            f"{mem_available // 2**20} MiB for {max(sizes)} rows"
        )
    need_disk = sum(estimate_resources(n)["disk_bytes"] for n in sizes)
    if disk_free is not None and need_disk + DISK_HEADROOM > disk_free:
        problems.append(
            f"estimated disk {need_disk // 2**20} MiB (+2 GiB headroom) exceeds free "
            f"{disk_free // 2**20} MiB"
        )
    return problems


def cells_for(cfg: dict) -> list[Cell]:
    cells: list[Cell] = []
    for rows in cfg["dataset"]["sizes"]:
        for op in cfg["workload"]["operations"]:
            if op == "preprocess":
                cells.append(Cell(rows, IN_MEMORY, op))
            else:
                cells.extend(Cell(rows, v, op) for v in cfg["formats"]["enabled"])
    return cells


def build_schedule(cells: list[Cell], rounds: int, order_seed: int) -> list[list[Cell]]:
    """One shuffled ordering of every cell per round, reproducible from ``order_seed``."""
    rng = random.Random(order_seed)
    schedule = []
    for _ in range(rounds):
        order = list(cells)
        rng.shuffle(order)
        schedule.append(order)
    return schedule


def _parent_maxrss_kib() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def spawn_worker(
    cmd: tuple[str, ...] | list[str], request: dict, timeout_s: float, env: dict[str, str]
) -> tuple[dict | None, int, str | None, str]:
    """Run one worker. Returns ``(result, wall_ns, error, kind)``; kind is ok/failed/timeout."""
    t0 = time.perf_counter_ns()
    try:
        proc = subprocess.run(
            list(cmd),
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, time.perf_counter_ns() - t0, f"timeout after {timeout_s} s", "timeout"
    except OSError as exc:
        return None, time.perf_counter_ns() - t0, f"cannot start worker: {exc}", "failed"
    wall = time.perf_counter_ns() - t0
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
        return None, wall, f"worker exited with code {proc.returncode}: {tail[0][:200]}", "failed"
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if len(lines) != 1:
        return None, wall, f"protocol violation: {len(lines)} stdout lines, expected 1", "failed"
    try:
        result = json.loads(lines[0])
    except json.JSONDecodeError:
        return None, wall, "protocol violation: stdout is not JSON", "failed"
    if not isinstance(result, dict) or "status" not in result:
        return None, wall, "protocol violation: no status field", "failed"
    if result["status"] == "failed":
        return result, wall, str(result.get("error", "worker reported failure")), "failed"
    return result, wall, None, "ok"


def worker_env(cfg: dict) -> dict[str, str]:
    env = dict(os.environ)
    if cfg["environment"]["thread_env"] == "single":
        env.update(dict.fromkeys(THREAD_VARIABLES, "1"))
    return env


def _noisy(before: list[float] | None, after: list[float] | None, cores: int, limit: float) -> bool:
    values = [v[0] for v in (before, after) if v]
    return bool(values) and max(values) / max(cores, 1) > limit


@dataclass
class Prepared:
    expected: dict[int, dict] = field(default_factory=dict)
    datasets: dict[str, dict] = field(default_factory=dict)
    failure: dict | None = None


def prepare_datasets(
    cfg: dict,
    *,
    job: str,
    worker_cmd: tuple[str, ...] | list[str] = DEFAULT_WORKER_CMD,
    env: dict[str, str] | None = None,
    progress: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
) -> Prepared:
    """Run the untimed ``prepare`` (write + validate) or ``validate`` job for every size.

    The first size that fails the bit-exact gate stops the process and is reported in
    ``failure``; nothing is timed before every size has passed.
    """
    out = Prepared()
    timeout_s = max(cfg["trials"]["timeout_s"], 600.0)
    for rows in cfg["dataset"]["sizes"]:
        progress(f"{job}: {rows} rows")
        result, _, error, _ = spawn_worker(
            worker_cmd,
            {
                "job": job,
                "rows": rows,
                "seed": cfg["dataset"]["seed"],
                "data_dir": cfg["dataset"]["data_dir"],
                "variants": cfg["formats"]["enabled"],
                "pt_cut": cfg["workload"]["pt_cut"],
                "eta_cut": cfg["workload"]["eta_cut"],
            },
            timeout_s,
            env if env is not None else worker_env(cfg),
        )
        if result is None or error or result.get("status") != "ok":
            detail = error or json.dumps(result.get("problems", result), sort_keys=True)[:400]
            out.failure = {"rows": rows, "detail": detail}
            return out
        out.expected[rows] = {
            "array_sha256": result["array_sha256"],
            "preprocess_digest": result["preprocess_digest"],
        }
        out.datasets[str(rows)] = {
            "dataset": result["dataset"],
            "file_bytes": result["files"],
            "preprocess_digest": result["preprocess_digest"],
        }
    return out


def run_benchmark(
    cfg: dict,
    *,
    allow_large: bool = False,
    worker_cmd: tuple[str, ...] | list[str] = DEFAULT_WORKER_CMD,
    project_dir: str | Path = ".",
    progress: Callable[[str], None] = lambda msg: print(msg, file=sys.stderr),
    run_id: str | None = None,
) -> RunOutcome:
    data_dir = Path(cfg["dataset"]["data_dir"])
    problems = preflight(
        cfg,
        allow_large=allow_large,
        mem_available=mem_available_bytes(),
        disk_free=shutil.disk_usage(nearest_existing(data_dir)).free,
    )
    if problems:
        return RunOutcome(EXIT_PREFLIGHT, message="pre-flight refused: " + "; ".join(problems))

    run_id = run_id or new_run_id()
    run_dir = Path(cfg["output"]["results_dir"]) / "raw" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    trials_path = run_dir / "trials.jsonl"
    scratch = run_dir / "scratch"
    env = capture_environment(data_dir, project_dir)
    warnings: list[str] = []
    if env.get("filesystem_type") in ("tmpfs", "ramfs", "overlay"):
        warnings.append(
            f"data_dir is on {env['filesystem_type']}: file timings may measure memory copies"
        )
    run: dict[str, Any] = {
        "run_id": run_id,
        "status": "running",
        "started_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": cfg,
        "environment": env,
        "warnings": warnings,
        "datasets": {},
    }
    write_run_json(run_dir / "run.json", run)
    for w in warnings:
        progress(f"warning: {w}")

    timeout_s = cfg["trials"]["timeout_s"]
    cores = env.get("cpu_count") or 1
    wenv = worker_env(cfg)

    # ---- prepare + validation gate (untimed)
    prepared = prepare_datasets(
        cfg, job="prepare", worker_cmd=worker_cmd, env=wenv, progress=progress
    )
    if prepared.failure:
        run.update(status="aborted", gate_failure=prepared.failure)
        write_run_json(run_dir / "run.json", run)
        return RunOutcome(
            EXIT_GATE,
            run_id,
            run_dir,
            "correctness gate failed for "
            f"{prepared.failure['rows']} rows: {prepared.failure['detail']}",
        )
    expected = prepared.expected
    run["datasets"] = prepared.datasets
    write_run_json(run_dir / "run.json", run)

    # ---- trials
    cells = cells_for(cfg)
    warm, measured = cfg["trials"]["warmup_rounds"], cfg["trials"]["measured_rounds"]
    schedule = build_schedule(cells, warm + measured, cfg["trials"]["order_seed"])
    counts = {"trials": 0, "failed": 0, "incorrect": 0}
    for idx, order in enumerate(schedule):
        phase = "warmup" if idx < warm else "measured"
        round_no = idx + 1 if idx < warm else idx - warm + 1
        progress(f"{phase} round {round_no}: {len(order)} trials")
        for position, cell in enumerate(order, start=1):
            before = loadavg()
            parent_peak = _parent_maxrss_kib()
            request = {
                "job": "trial",
                "operation": cell.operation,
                "variant": cell.variant,
                "rows": cell.rows,
                "seed": cfg["dataset"]["seed"],
                "data_dir": str(data_dir),
                "scratch_dir": str(scratch),
                "pt_cut": cfg["workload"]["pt_cut"],
                "eta_cut": cfg["workload"]["eta_cut"],
                "expected": expected[cell.rows],
            }
            result, wall, error, kind = spawn_worker(worker_cmd, request, timeout_s, wenv)
            after = loadavg()
            ok = kind == "ok" and result is not None
            res = (result or {}).get("resources") or {}
            ru = res.get("ru_maxrss_kib")
            rec = {
                "results_schema_version": RESULTS_SCHEMA_VERSION,
                "run_id": run_id,
                "variant": cell.variant,
                "operation": cell.operation,
                "dataset": {
                    "rows": cell.rows,
                    "seed": cfg["dataset"]["seed"],
                    "dtype": run["datasets"][str(cell.rows)]["dataset"]["dtype"],
                    "sha256": expected[cell.rows]["array_sha256"],
                },
                "round": round_no,
                "position": position,
                "phase": phase,
                "status": "ok" if ok else kind,
                "correct": bool(result["correct"]) if ok else None,
                "correctness_check": result.get("correctness_check") if ok else None,
                "timing": {
                    "elapsed_ns": result["timing"]["elapsed_ns"] if ok else None,
                    "process_time_ns": result["timing"]["process_time_ns"] if ok else None,
                    "subprocess_wall_ns": wall,
                },
                "resources": {
                    "ru_maxrss_kib": ru,
                    "vm_hwm_kib": res.get("vm_hwm_kib"),
                    "vm_rss_baseline_kib": res.get("vm_rss_baseline_kib"),
                    "vm_hwm_baseline_kib": res.get("vm_hwm_baseline_kib"),
                    "hwm_reset": res.get("hwm_reset"),
                    "parent_ru_maxrss_kib_at_launch": parent_peak,
                },
                "flags": {
                    "noisy_load": _noisy(before, after, cores, cfg["noise"]["max_load_per_core"]),
                    "maxrss_floor_suspect": bool(
                        ru is not None and parent_peak is not None and ru <= parent_peak
                    ),
                    "outlier_vs_median": False,
                },
                "sizes": (result or {}).get("sizes") or {"logical_bytes": cell.rows * ROW_BYTES},
                "measurement": {
                    "warmup_rounds": warm,
                    "measured_rounds": measured,
                    "fsync": False,
                    "cache_mode": "warm",
                    "primed_imports": bool((result or {}).get("primed")),
                    "thread_env": (result or {}).get("thread_env"),
                    "loadavg_before": before,
                    "loadavg_after": after,
                },
                "error": error,
            }
            append_trial(trials_path, rec)
            counts["trials"] += 1
            counts["failed"] += 0 if ok else 1
            counts["incorrect"] += 1 if ok and not rec["correct"] else 0

    shutil.rmtree(scratch, ignore_errors=True)
    clean = counts["failed"] == 0 and counts["incorrect"] == 0
    run.update(
        status="completed" if clean else "completed_with_failures",
        ended_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        loadavg_at_end=loadavg(),
        counts=counts,
    )
    write_run_json(run_dir / "run.json", run)
    message = f"{counts['trials']} trials recorded in {trials_path}"
    if not clean:
        message += f"; {counts['failed']} failed, {counts['incorrect']} incorrect (all kept)"
    return RunOutcome(EXIT_OK if clean else EXIT_PARTIAL, run_id, run_dir, message, counts)
