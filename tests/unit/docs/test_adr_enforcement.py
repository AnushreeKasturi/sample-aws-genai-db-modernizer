"""Every numbered ADR decision names the test that guards it (#623).

An ADR that is only read does not stop the code drifting from it (ADR-031 was
accepted while table-first scoping and name-based tie rules lived on). So an
ADR that numbers its decisions (``### N. Title`` under ``## Decision(s)``) also
carries an ``## Enforcement`` table with one row per decision:

    | Decision | Enforced by |
    |---|---|
    | 1. The query is the unit | `tests/unit/x/test_y.py::TestClass::test_name`<br>`tests/unit/z.py` |
    | 5. Cost is a dimension | none yet -- #638 |

Lettered (``### A.``) and ``### Decision N:`` headings count too. Each ``Enforced by`` cell lists guard tests separated by ``<br>``. An entry is a
path under ``tests/``, optionally followed by ``::Class`` and ``::function``
names that must exist in that file. A decision with no guard says
``none yet -- #N`` (the follow-up issue that adds one) instead of inventing a
weak test; it is never left blank. Sections of ADRs that predate this rule are
listed in ``PENDING_ADOPTION`` (#641) and leave that list when their table is
added.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TESTS_DIR = REPO_ROOT / "tests"
ADR_DIR = REPO_ROOT / "docs" / "architecture" / "decisions"

# ADRs with numbered decisions that have no Enforcement table yet (#641).
# Remove an entry when its table lands; the test below fails if you forget.
PENDING_ADOPTION = frozenset(
    {
        "ADR-004-rds-tools-and-aws-integration.md",
        "ADR-013-core-infrastructure-cost-optimization.md",
        "ADR-017-analysis-agent-scoring-framework.md",
        "ADR-018-reality-check-and-human-gate.md",
        "ADR-026-reality-check-in-assessment-core.md",
        "ADR-028-aurora-relational-schema-design-agents.md",
        "ADR-028-customer-assignment-review-gate.md",
        "ADR-029-assignment-reentry-and-feasibility-review.md",
    }
)

DECISION_HEADING = re.compile(r"^### (?:Decision\s+)?(\d+|[A-Z])[.:]\s+\S", re.MULTILINE)
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.MULTILINE | re.DOTALL)
SECTION_HEADING = re.compile(r"^## (.+?)\s*$", re.MULTILINE)
ROW = re.compile(r"^\|\s*(?:Decision\s+)?(\d+|[A-Z])[.:][^|]*\|(.*)\|\s*$")
NONE_YET = re.compile(r"^none yet\s+(?:--|—)\s+#\d+(?:\s+\(.*\))?$")
TEST_ENTRY = re.compile(r"^`(tests/[\w./-]+\.py)((?:::\w+)*)`$")


def _sections(text: str) -> dict[str, str]:
    """Top-level (``##``) section bodies keyed by heading text.

    Fenced code blocks are blanked first so a ``## `` line inside one does not
    cut a section short.
    """
    text = FENCE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    matches = list(SECTION_HEADING.finditer(text))
    out: dict[str, str] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[m.group(1)] = text[m.end() : end]
    return out


def decision_numbers(text: str) -> list[str]:
    """Labels (``1``, ``A``) of the decision headings in every ``## Decision*`` section."""
    body = "\n".join(b for title, b in _sections(text).items() if title.startswith("Decision"))
    return DECISION_HEADING.findall(body)


def enforcement_rows(text: str) -> dict[str, str]:
    """Decision number -> raw ``Enforced by`` cell, from the Enforcement table."""
    body = _sections(text).get("Enforcement")
    if body is None:
        return {}
    rows: dict[str, str] = {}
    for line in body.splitlines():
        m = ROW.match(line.strip())
        if m:
            number = m.group(1)
            assert number not in rows, f"decision {number} has two Enforcement rows"
            rows[number] = m.group(2).strip()
    return rows


def _members(node: ast.AST) -> dict[str, ast.AST]:
    return {
        n.name: n
        for n in getattr(node, "body", [])
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }


def entry_problems(entry: str) -> list[str]:
    """Why one cell entry is not a valid guard reference (empty when valid)."""
    if NONE_YET.match(entry):
        return []
    m = TEST_ENTRY.match(entry)
    if not m:
        return [f"{entry!r} is neither a `tests/...py[::Name]` reference nor 'none yet -- #N'"]
    rel = m.group(1)
    if ".." in Path(rel).parts:
        return [f"{rel} must not contain '..'"]
    path = (REPO_ROOT / rel).resolve()
    if not path.is_relative_to(TESTS_DIR):
        return [f"{rel} is outside tests/"]
    if not (path.name.startswith("test_") or path.stem.endswith("_test")):
        return [f"{rel} is not a test module (test_*.py or *_test.py)"]
    if not path.is_file():
        return [f"{rel} does not exist"]
    names = [n for n in m.group(2).split("::") if n]
    if len(names) > 2:
        return [f"{entry}: use at most Class::function"]
    scope = _members(ast.parse(path.read_text()))
    walked = rel
    for depth, name in enumerate(names):
        node = scope.get(name)
        if node is None:
            return [f"{walked} has no {name!r}"]
        is_class = isinstance(node, ast.ClassDef)
        collected = (is_class and name.startswith("Test")) or (
            not is_class and name.startswith("test")
        )
        if (
            not collected
            or (depth == 1 and is_class)
            or (depth == 0 and not is_class and len(names) > 1)
        ):
            return [f"{walked}::{name} is not a collected test (Test* class or test_* function)"]
        walked += f"::{name}"
        scope = _members(node)
    return []


def cell_problems(cell: str) -> list[str]:
    entries = [e.strip() for e in cell.split("<br>") if e.strip()]
    if not entries:
        return ["the Enforced by cell is empty"]
    return [p for e in entries for p in entry_problems(e)]


def _adrs() -> list[Path]:
    return sorted(ADR_DIR.glob("ADR-*.md"))


def _in_force(text: str) -> bool:
    status = re.search(r"\*\*Status:\*\*\s*(\w+)", text)
    return not status or status.group(1) not in {"Superseded", "Deprecated", "Rejected"}


def _checked_adrs() -> list[Path]:
    """ADRs whose numbered decisions must each have a guard (not pending)."""
    return [
        p
        for p in _adrs()
        if p.name not in PENDING_ADOPTION
        and decision_numbers(p.read_text())
        and _in_force(p.read_text())
    ]


def test_adr_031_is_checked() -> None:
    """The rule must actually cover the ADR it was written for."""
    assert "ADR-031-query-first-routing-and-engine-rule-catalog.md" in [
        p.name for p in _checked_adrs()
    ]


@pytest.mark.parametrize("adr", _checked_adrs(), ids=lambda p: p.name)
def test_every_numbered_decision_names_an_existing_guard(adr: Path) -> None:
    text = adr.read_text()
    numbers = decision_numbers(text)
    rows = enforcement_rows(text)
    problems = [
        f"decision {n} has no row in the Enforcement table" for n in numbers if n not in rows
    ]
    problems += [
        f"Enforcement row {n} matches no numbered decision" for n in rows if n not in numbers
    ]
    for n, cell in rows.items():
        problems += [f"decision {n}: {p}" for p in cell_problems(cell)]
    assert not problems, f"{adr.name}:\n" + "\n".join(problems)


def test_pending_list_only_holds_adrs_that_still_need_a_table() -> None:
    by_name = {p.name: p for p in _adrs()}
    stale = []
    for name in sorted(PENDING_ADOPTION):
        if name not in by_name:
            stale.append(f"{name} does not exist")
            continue
        text = by_name[name].read_text()
        if not decision_numbers(text):
            stale.append(f"{name} has no numbered decisions")
        elif enforcement_rows(text):
            stale.append(f"{name} has an Enforcement table: remove it from PENDING_ADOPTION")
    assert not stale, "\n".join(stale)


def test_every_adr_with_numbered_decisions_is_checked_or_pending() -> None:
    """A new ADR cannot dodge the rule by simply omitting the table."""
    unchecked = [
        p.name
        for p in _adrs()
        if decision_numbers(p.read_text())
        and _in_force(p.read_text())
        and not enforcement_rows(p.read_text())
        and p.name not in PENDING_ADOPTION
    ]
    assert not unchecked, f"no Enforcement table: {unchecked}"


# --- the checker itself must reject the failures it exists to catch ----------


def _adr(decisions: int, table: str) -> str:
    heads = "\n\n".join(f"### {i}. Title {i}\n\nbody" for i in range(1, decisions + 1))
    return f"# ADR\n\n**Status:** Accepted\n\n## Decision\n\n{heads}\n\n## Enforcement\n\n{table}\n"


def test_checker_finds_a_decision_with_no_row() -> None:
    text = _adr(2, "| Decision | Enforced by |\n|---|---|\n| 1. A | none yet -- #1 |")
    assert decision_numbers(text) == ["1", "2"]
    assert set(enforcement_rows(text)) == {"1"}


def test_checker_rejects_blank_and_unparseable_cells() -> None:
    assert cell_problems("") == ["the Enforced by cell is empty"]
    assert cell_problems("TBD")
    assert cell_problems("none yet")


def test_checker_rejects_missing_file_class_and_function() -> None:
    here = "tests/unit/docs/test_adr_enforcement.py"
    assert cell_problems(f"`{here}`") == []
    assert cell_problems(f"`{here}::test_checker_rejects_blank_and_unparseable_cells`") == []
    assert cell_problems("`tests/unit/docs/test_does_not_exist.py`")
    assert cell_problems(f"`{here}::TestNope`")
    assert cell_problems(f"`{here}::test_nope`")


def test_checker_accepts_the_explicit_marker_only_with_an_issue_number() -> None:
    assert cell_problems("none yet -- #638") == []
    assert cell_problems("none yet — #638") == []
    assert cell_problems("none yet -- later")


def test_checker_accepts_several_entries_in_one_cell() -> None:
    here = "tests/unit/docs/test_adr_enforcement.py"
    assert cell_problems(f"`{here}`<br>none yet -- #1") == []
    assert cell_problems(f"`{here}`<br>`tests/nope.py`")


def test_checker_rejects_paths_that_escape_tests() -> None:
    assert cell_problems("`tests/../src/agents/referee/tie_break.py::break_tie`")
    assert cell_problems("`tests/unit/../../src/agents/referee/tie_break.py`")


def test_checker_rejects_helpers_conftest_and_non_test_modules() -> None:
    assert cell_problems("`tests/e2e/routing_snapshot.py`")
    assert cell_problems("`tests/conftest.py`")
    assert cell_problems("`tests/e2e/conftest.py::run`")


def test_checker_rejects_names_that_are_not_collected_tests() -> None:
    mod = "tests/unit/test_assignment_resolver.py"
    assert cell_problems(f"`{mod}::_make_triage`")
    assert cell_problems(f"`{mod}::TestOpenSearchNeverOwnsAWrite::_helper`")
    assert cell_problems(f"`{mod}::TestOpenSearchNeverOwnsAWrite::TestNested`")
    assert cell_problems(f"`{mod}::TestOpenSearchNeverOwnsAWrite::test_a::extra`")
    assert cell_problems(f"`{mod}::TestOpenSearchNeverOwnsAWrite`") == []


def test_checker_finds_decisions_in_other_heading_styles() -> None:
    outcome = "# A\n\n## Decision Outcome\n\n### Decision 1: One\n\nx\n\n### Decision 2: Two\n"
    assert decision_numbers(outcome) == ["1", "2"]
    lettered = "# A\n\n## Decision\n\n### A. First\n\n### B. Second\n"
    assert decision_numbers(lettered) == ["A", "B"]
    row = "| Decision A: First | none yet -- #1 |"
    assert set(enforcement_rows(f"## Enforcement\n\n{row}\n")) == {"A"}


def test_checker_ignores_a_heading_line_inside_a_code_fence() -> None:
    text = "## Decision\n\n### 1. One\n\n```text\n## not a heading\n```\n\n### 2. Two\n"
    assert decision_numbers(text) == ["1", "2"]
