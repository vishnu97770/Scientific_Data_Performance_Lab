"""Repository-level guarantees: ignore rules, lock shape, CI file shape, test discipline."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HAS_GIT = shutil.which("git") is not None and (ROOT / ".git").exists()

MUST_BE_IGNORED = [
    ".claude/settings.local.json",
    ".venv/pyvenv.cfg",
    "data/generated/events_1000.csv",
    "results/raw/run-1/trials.jsonl",
    "results/plots/run-1/load.png",
    "results/reports/run-1.md",
]
MUST_STAY_TRACKED = [
    "docs/requirements.md",
    "uv.lock",
    ".python-version",
    "pyproject.toml",
    "src/sdplab/cli.py",
    "tests/test_cli.py",
    ".github/workflows/ci.yml",
    "data/generated/.gitkeep",
    "results/raw/.gitkeep",
    "results/plots/.gitkeep",
    "results/reports/.gitkeep",
    "results/examples/run-1/run.json",
    "docs/adr/ADR-001.md",
]


def _ignored(path: str) -> bool:
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "--", path], cwd=ROOT, check=False, capture_output=True
    )
    return proc.returncode == 0


@pytest.mark.skipif(not HAS_GIT, reason="needs git and a work tree")
@pytest.mark.parametrize("path", MUST_BE_IGNORED)
def test_generated_and_local_paths_are_ignored(path):
    assert _ignored(path), path


@pytest.mark.skipif(not HAS_GIT, reason="needs git and a work tree")
@pytest.mark.parametrize("path", MUST_STAY_TRACKED)
def test_tracked_paths_are_not_ignored(path):
    assert not _ignored(path), path


@pytest.mark.parametrize("path", [p for p in MUST_STAY_TRACKED if p.endswith(".gitkeep")])
def test_gitkeep_files_exist(path):
    assert (ROOT / path).is_file()


def test_lock_has_one_numpy_and_the_python_floor():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = [p["name"] for p in lock["package"]]
    assert names.count("numpy") == 1
    assert lock["requires-python"] == ">=3.12"


def test_pyproject_declares_the_floor_and_build_backend():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    meta = tomllib.loads(text)
    assert meta["project"]["requires-python"] == ">=3.12"
    assert meta["build-system"]["build-backend"] == "uv_build"
    assert "3.11" not in text


def test_workflow_shape():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)(.*)$", text, flags=re.M)
    assert uses
    for ref, rest in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        assert re.search(r"#\s*v\d", rest), ref
    assert '"3.12"' in text
    assert '"3.13"' in text
    for command in ("uv sync --locked", "ruff check", "ruff format --check", "pytest"):
        assert command in text
    assert "permissions:\n  contents: read" in text
    assert "workflow_dispatch" in text
    assert "pull_request:\n    branches: [main]" in text
    for command in ("sdplab --help", "sdplab check-run", "--no-group dashboard", "streamlit run"):
        assert command in text
    assert "secrets." not in text
    assert "upload-artifact" not in text
    assert "sdplab run" not in text


def test_tests_have_no_hardcoded_digest_or_timing_calls():
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name == "test_repo_hygiene.py":
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\b[0-9a-fA-F]{64}\b", text), path.name
        assert not re.search(
            r"\bperf_counter|\btime\.process_time\(|\btime\.time\(|\btimeit\b", text
        ), path.name
