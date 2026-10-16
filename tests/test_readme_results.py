"""Every number in the README results block must come from the committed example run."""

from pathlib import Path

from sdplab.analysis import summarize
from sdplab.report import README_MARKERS, readme_results_block
from sdplab.results import read_run_json, read_trials

ROOT = Path(__file__).resolve().parent.parent


def _examples():
    return sorted(
        p for p in (ROOT / "results" / "examples").iterdir() if (p / "run.json").is_file()
    )


def test_the_readme_results_block_is_regenerated_from_the_committed_example():
    examples = _examples()
    assert examples, "no committed example run"
    ex = examples[-1]
    run = read_run_json(ex / "run.json")
    trials, truncated = read_trials(ex / "trials.jsonl")
    assert truncated is False
    rows = summarize(trials, run["config"]["noise"]["outlier_factor"])
    expected = readme_results_block(run, rows, f"results/examples/{ex.name}")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    start, end = README_MARKERS
    assert readme.count(start) == readme.count(end) == 1
    actual = readme[readme.index(start) : readme.index(end) + len(end)]
    assert actual == expected


def test_the_example_run_is_complete_and_clean():
    ex = _examples()[-1]
    run = read_run_json(ex / "run.json")
    assert run["status"] == "completed"
    assert run["counts"]["failed"] == run["counts"]["incorrect"] == 0
    assert (ex / "summary.csv").is_file()
    assert (ex / "report.md").is_file()
    assert any((ex / "plots").glob("*.png"))
