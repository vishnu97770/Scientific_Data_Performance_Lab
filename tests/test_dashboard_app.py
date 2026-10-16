"""Streamlit pages rendered headlessly with AppTest against the real recorded example run."""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
pytest.importorskip("pandas")
pytest.importorskip("altair")

from streamlit.testing.v1 import AppTest

from sdplab.dashboard.discovery import discover_runs

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "results" / "examples"
TIMEOUT = 90


def page_script(page: str, root: str) -> None:
    from pathlib import Path

    import streamlit as st

    from sdplab.dashboard import app
    from sdplab.dashboard.discovery import discover_runs

    runs = discover_runs(Path(root))
    st.session_state["run_ref"] = runs[0] if runs else None
    st.session_state["repo_url"] = app.DEFAULT_REPO_URL
    st.session_state["pages"] = []
    getattr(app, page)()


def run_page(page: str, root=EXAMPLES) -> AppTest:
    return AppTest.from_function(page_script, args=(page, str(root)), default_timeout=TIMEOUT).run()


def all_text(at: AppTest) -> str:
    parts = []
    for kind in (
        "markdown",
        "info",
        "error",
        "warning",
        "success",
        "caption",
        "code",
        "title",
        "subheader",
    ):
        parts += [str(e.value) for e in getattr(at, kind)]
    parts += [f"{m.label} {m.value}" for m in at.metric]
    return "\n".join(parts)


def test_the_full_app_starts_and_shows_the_recorded_run():
    at = AppTest.from_file(str(ROOT / "streamlit_app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception
    assert [t.value for t in at.title] == ["Scientific Data Performance Lab"]
    run_id = discover_runs(EXAMPLES)[0].run_id
    assert any(run_id in str(s.value) for s in at.success)


def test_overview_metrics_come_from_the_records():
    from sdplab.dashboard.data import load_run, overview_facts

    facts = overview_facts(load_run(discover_runs(EXAMPLES)[0]))
    at = run_page("page_overview")
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Formats compared"] == str(len(facts["formats"]))
    assert metrics["Dataset sizes"] == str(len(facts["sizes"]))
    assert metrics["Measured trials"] == f"{facts['trials_measured']:,}"
    assert metrics["Failed / incorrect trials"] == f"{facts['failed']} / {facts['incorrect']}"
    assert any("not affiliated" in str(c.value) for c in at.caption)
    assert any("recorded measurements" in str(w.value) for w in at.warning)


@pytest.mark.parametrize(
    "page", ["page_comparison", "page_results", "page_methodology", "page_about"]
)
def test_every_page_renders_without_error(page):
    at = run_page(page)
    assert not at.exception
    assert at.title


def test_comparison_filters_drive_the_findings():
    at = run_page("page_comparison")
    for op in ("write", "load", "preprocess", "load_preprocess"):
        at.selectbox[0].select(op).run()
        assert not at.exception, op
        assert any(
            "this run" in str(m.value) for m in at.markdown if "median time" in str(m.value)
        ), op
    at.selectbox[0].select("load").run()
    at.selectbox[1].select(10_000).run()
    assert any("10,000 rows" in str(m.value) for m in at.markdown)
    at.multiselect[0].set_value([]).run()
    assert any("Select at least one format" in str(i.value) for i in at.info)


def test_results_page_offers_downloads_and_filters_trials():
    at = run_page("page_results")
    assert not at.exception
    assert len(at.dataframe) >= 2
    at.multiselect[0].set_value(["measured", "warmup"]).run()
    assert not at.exception
    assert any("trials match" in str(c.value) for c in at.caption)


def test_no_local_filesystem_paths_are_rendered():
    forbidden = [str(ROOT), "/home/"]
    for page in (
        "page_overview",
        "page_comparison",
        "page_results",
        "page_methodology",
        "page_about",
    ):
        text = all_text(run_page(page))
        for needle in forbidden:
            assert needle not in text, (page, needle)


def test_missing_results_show_a_helpful_empty_state(tmp_path):
    at = run_page("page_overview", tmp_path / "none")
    assert not at.exception
    assert [t.value for t in at.title] == ["No recorded run found"]
    assert any("sdplab run" in str(i.value) for i in at.info)


def test_a_corrupted_run_shows_a_safe_error(tmp_path):
    src = discover_runs(EXAMPLES)[0]
    dest = tmp_path / src.run_id
    shutil.copytree(src.path, dest)
    (dest / "run.json").write_text("{broken", encoding="utf-8")
    at = run_page("page_overview", tmp_path)
    assert not at.exception
    assert [t.value for t in at.title] == ["This run cannot be displayed"]
    assert str(tmp_path) not in all_text(at)


def test_an_inconsistent_run_is_not_shown_as_valid(tmp_path):
    src = discover_runs(EXAMPLES)[0]
    dest = tmp_path / src.run_id
    shutil.copytree(src.path, dest)
    lines = (dest / "trials.jsonl").read_text(encoding="utf-8").splitlines()
    (dest / "trials.jsonl").write_text("\n".join(lines[:-3]) + "\n", encoding="utf-8")
    at = run_page("page_comparison", tmp_path)
    assert not at.exception
    assert [t.value for t in at.title] == ["This run did not pass validation"]
    assert not at.dataframe  # no charts, tables or rankings for an invalid run
    assert not at.success


def test_the_app_offers_no_execution_or_upload_controls():
    for page in (
        "page_overview",
        "page_comparison",
        "page_results",
        "page_methodology",
        "page_about",
    ):
        at = run_page(page)
        assert not at.get("file_uploader")
        assert not at.text_input
        assert not at.text_area
        assert not any("run benchmark" in b.label.lower() for b in at.button)
