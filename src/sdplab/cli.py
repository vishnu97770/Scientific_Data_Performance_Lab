"""Command-line interface: info, prepare, validate, run, report.

Exit codes (documented in --help and the README):
  0 success
  1 unexpected internal error
  2 usage or configuration error
  3 correctness gate failed (nothing timed is accepted), or check-run found problems
  4 run completed but some trials failed, timed out or were incorrect (all raw data kept)
  5 pre-flight refused (insufficient RAM/disk, --allow-large missing, unsupported option)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from importlib import metadata
from pathlib import Path

from sdplab import config
from sdplab.config import ConfigError
from sdplab.results import ResultsError, capture_environment, validate_run

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_GATE, EXIT_PARTIAL, EXIT_PREFLIGHT = 0, 1, 2, 3, 4, 5
EXIT_CODES_HELP = (
    "exit codes: 0 success; 1 internal error; 2 usage or configuration error; "
    "3 correctness gate failed or check-run found problems; "
    "4 run completed with failed/timed-out/incorrect trials (raw data kept); "
    "5 pre-flight refused"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdplab",
        description=(
            "Scientific Data Performance Lab: a reproducible benchmark of CSV vs NumPy "
            ".npy/.npz loading on a deterministic synthetic dataset."
        ),
        epilog=EXIT_CODES_HELP,
    )
    parser.add_argument(
        "--version", action="version", version=f"sdplab {metadata.version('sdplab')}"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    p = sub.add_parser(
        "info", help="print versions and the machine environment", epilog=EXIT_CODES_HELP
    )
    p.add_argument("--config", help="TOML config; validated, and its data_dir is inspected")

    for name, text in (
        ("prepare", "generate the dataset, write every variant, and run the bit-exact gate"),
        ("validate", "re-check the existing files against the regenerated dataset (bit-exact)"),
    ):
        p = sub.add_parser(name, help=text, epilog=EXIT_CODES_HELP)
        p.add_argument("--config", required=True, help="TOML config file")

    p = sub.add_parser(
        "run",
        help="prepare, gate, then run the subprocess-per-trial benchmark",
        epilog=EXIT_CODES_HELP,
    )
    p.add_argument("--config", required=True, help="TOML config file")
    p.add_argument("--allow-large", action="store_true", help="permit 10^7 rows or more")

    p = sub.add_parser(
        "report",
        help="write summary.csv, plots and a markdown report from saved raw results only",
        epilog=EXIT_CODES_HELP,
    )
    p.add_argument("--run", required=True, help="a results/raw/<run_id> directory")
    p.add_argument(
        "--example-dir",
        help="also write a self-contained copy (raw files, summary, plots, report) to "
        "<example-dir>/<run_id>/ for committing as an example; refuses to overwrite",
    )

    p = sub.add_parser(
        "check-run",
        help="check that a run directory is internally consistent (raw files only)",
        epilog=EXIT_CODES_HELP,
    )
    p.add_argument("--run", required=True, help="a results/raw/<run_id> directory")
    return parser


def _say(message: str) -> None:
    print(message, flush=True)


def _cmd_info(args: argparse.Namespace) -> int:
    cfg = config.load(args.config) if args.config else config.defaults()
    out = {
        "sdplab": metadata.version("sdplab"),
        "environment": capture_environment(cfg["dataset"]["data_dir"]),
        "config_schema_version": cfg["config_schema_version"],
        "config_source": args.config or "built-in defaults",
    }
    _say(json.dumps(out, indent=2, sort_keys=True))
    return EXIT_OK


def _cmd_prepare_or_validate(args: argparse.Namespace) -> int:
    from sdplab.runner import prepare_datasets

    cfg = config.load(args.config)
    prepared = prepare_datasets(
        cfg, job=args.command, progress=lambda msg: print(msg, file=sys.stderr)
    )
    if prepared.failure:
        print(
            f"correctness gate failed for {prepared.failure['rows']} rows: "
            f"{prepared.failure['detail']}",
            file=sys.stderr,
        )
        return EXIT_GATE
    for rows, info in prepared.datasets.items():
        _say(f"{rows} rows: all variants bit-exact; sha256 {info['dataset']['sha256']}")
        for variant, size in sorted(info["file_bytes"].items()):
            _say(f"  {variant}: {size} bytes")
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    from sdplab.runner import run_benchmark

    cfg = config.load(args.config)
    outcome = run_benchmark(cfg, allow_large=args.allow_large)
    stream = sys.stdout if outcome.exit_code in (EXIT_OK, EXIT_PARTIAL) else sys.stderr
    print(outcome.message, file=stream)
    if outcome.run_dir:
        _say(f"run directory: {outcome.run_dir}")
        if outcome.exit_code in (EXIT_OK, EXIT_PARTIAL):
            _say(f"next: sdplab report --run {outcome.run_dir}")
    return outcome.exit_code


def _cmd_check_run(args: argparse.Namespace) -> int:
    problems = validate_run(Path(args.run))
    if problems:
        for problem in problems:
            print(f"problem: {problem}", file=sys.stderr)
        print(f"{len(problems)} problem(s) found in {args.run}", file=sys.stderr)
        return EXIT_GATE
    _say(f"{args.run}: consistent (schema, hashes, counts and trial totals agree)")
    return EXIT_OK


def _cmd_report(args: argparse.Namespace) -> int:
    from sdplab.report import build_report  # imports matplotlib; only this command needs it

    result = build_report(Path(args.run), Path(args.example_dir) if args.example_dir else None)
    _say(f"summary: {result['summary']}")
    _say(f"report:  {result['report']}")
    for path in sorted(result["plots"].values()):
        _say(f"plot:    {path}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handlers = {
        "info": _cmd_info,
        "prepare": _cmd_prepare_or_validate,
        "validate": _cmd_prepare_or_validate,
        "run": _cmd_run,
        "report": _cmd_report,
        "check-run": _cmd_check_run,
    }
    try:
        return handlers[args.command](args)
    except (ConfigError, ResultsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (FileNotFoundError, NotADirectoryError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except Exception as exc:
        if os.environ.get("SDPLAB_DEBUG"):
            traceback.print_exc()
        print(f"internal error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR
