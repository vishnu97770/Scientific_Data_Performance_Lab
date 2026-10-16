"""Documentation hygiene: local links resolve, fences are balanced, Mermaid blocks look valid."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
MERMAID_STARTS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "stateDiagram",
    "classDiagram",
    "erDiagram",
)


def _anchors(text: str) -> set[str]:
    out = set()
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            slug = re.sub(r"[^\w\- ]", "", m.group(2).lower()).replace(" ", "-")
            out.add(slug)
    return out


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_code_fences_are_balanced(path):
    assert path.read_text(encoding="utf-8").count("```") % 2 == 0


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_local_links_and_anchors_resolve(path):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\((?!https?://|mailto:)([^)\s]+)\)", text):
        file_part, _, anchor = target.partition("#")
        dest = path if not file_part else (path.parent / file_part)
        assert dest.exists(), f"{path.name}: missing link target {target}"
        if anchor and dest.suffix == ".md":
            assert anchor in _anchors(dest.read_text(encoding="utf-8")), f"{path.name}: {target}"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: str(p.relative_to(ROOT)))
def test_mermaid_blocks_start_with_a_diagram_keyword(path):
    for block in re.findall(r"```mermaid\n(.*?)```", path.read_text(encoding="utf-8"), flags=re.S):
        first = block.strip().splitlines()[0]
        assert first.startswith(MERMAID_STARTS), first
        assert block.count("[") == block.count("]")
