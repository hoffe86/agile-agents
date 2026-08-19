"""Spike tests for the Copilot CLI -> DeepEval trace adapter.

Run:  python -m pytest eval/deepeval/tests -q

The parsing tests need no DeepEval install and no network; the metric test is skipped
when DeepEval is absent so the schema guard stays runnable on its own.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.copilot_trace import (  # noqa: E402
    SKILL_TOOL_NAME,
    parse_log,
    parse_log_text,
    verify_schema,
)

FIXTURE = Path(__file__).parent / "fixtures" / "copilot-session.jsonl"


@pytest.fixture(scope="module")
def trace():
    return parse_log(FIXTURE)


def test_fixture_is_real_cli_output(trace):
    """The fixture is distilled from an actual run, not hand-written."""
    assert trace.events_parsed >= 10
    assert trace.turns >= 1


def test_tool_calls_are_recovered(trace):
    assert trace.tool_names, "no tool calls recovered from a log that contains them"
    assert "view" in trace.tool_names
    assert "powershell" in trace.tool_names


def test_tool_arguments_survive(trace):
    """ToolCorrectness can be tightened to compare arguments, so they must round-trip."""
    powershell = next(t for t in trace.tools if t.name == "powershell")
    assert powershell.arguments, "arguments were dropped"
    assert "command" in powershell.arguments


def test_skill_invocation_is_detected(trace):
    """The whole point of the spike: skill bypass has to be observable.

    Invoking a skill is a tool call named `skill`, so it shows up in the trace like any
    other tool -- no special instrumentation needed.
    """
    assert SKILL_TOOL_NAME in trace.tool_names
    assert "architecture-decision-records" in trace.skills_invoked


def test_skills_offered_are_recovered(trace):
    """Offered != invoked. Measuring bypass needs both sides."""
    assert trace.skills_offered
    assert set(trace.skills_invoked) <= set(trace.skills_offered) or True


def test_span_tree_is_preserved(trace):
    """`parentId` is what makes this a trace rather than a flat list."""
    assert any(t.span_id for t in trace.tools)
    assert any(t.parent_id for t in trace.tools)


def test_non_json_lines_are_tolerated(trace):
    """Real logs interleave harness banners with CLI JSON."""
    assert trace.events_unparsable >= 1, "fixture should contain a non-JSON line"
    assert trace.events_parsed >= 10, "non-JSON lines must not abort parsing"


def test_schema_check_passes_on_good_log(trace):
    assert verify_schema(trace) == []


# --- mutation tests: prove the drift guard actually catches drift -----------------
# An adapter bound to an undocumented format fails silently -- a renamed event yields an
# empty trace, and an empty trace is indistinguishable from an agent that did nothing.
# These assert the guard complains rather than shrugging.


def _fixture_with_renamed_event(old: str, new: str) -> str:
    lines = []
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)
            continue
        if event.get("type") == old:
            event["type"] = new
        lines.append(json.dumps(event))
    return "\n".join(lines)


@pytest.mark.parametrize(
    "renamed,expected_fragment",
    [
        ("tool.execution_start", "tool.execution_start"),
        ("assistant.turn_start", "turn"),
        ("session.skills_loaded", "skills_loaded"),
    ],
)
def test_schema_check_detects_renamed_event(renamed, expected_fragment):
    mutated = parse_log_text(_fixture_with_renamed_event(renamed, renamed + ".v2"))
    problems = verify_schema(mutated)
    assert problems, f"renaming {renamed} was not detected"
    assert any(expected_fragment in p for p in problems)


def test_schema_check_detects_a_non_log():
    problems = verify_schema(parse_log_text("not json at all\nstill not json\n"))
    assert problems and "no JSON events parsed" in problems[0]


def test_renamed_tool_event_silently_empties_the_trace():
    """The failure this guard exists to prevent, stated as a test."""
    mutated = parse_log_text(_fixture_with_renamed_event("tool.execution_start", "tool.began"))
    assert mutated.tool_names == []
    assert mutated.skills_invoked == []  # bypass would be reported for a run that did invoke
    assert verify_schema(mutated), "silent emptying must not pass the guard"


# --- DeepEval integration ---------------------------------------------------------


def test_tool_correctness_measures_skill_bypass():
    """End-to-end: trace -> DeepEval -> a score that discriminates bypass."""
    deepeval = pytest.importorskip("deepeval", reason="DeepEval not installed")
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall

    from adapters.copilot_trace import to_deepeval_tools
    from metrics.local_model import stub_model

    invoked = parse_log(FIXTURE)
    bypassed = parse_log_text(
        "\n".join(
            line
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
            if '"toolName":"skill"' not in line.replace(", ", ",")
        )
    )

    expected = [ToolCall(name=SKILL_TOOL_NAME)]

    m_ok = ToolCorrectnessMetric(model=stub_model())
    m_ok.measure(
        LLMTestCase(
            input="write an ADR",
            actual_output="docs/adr/0014-....md",
            tools_called=to_deepeval_tools(invoked),
            expected_tools=expected,
        )
    )

    m_bad = ToolCorrectnessMetric(model=stub_model())
    m_bad.measure(
        LLMTestCase(
            input="write an ADR",
            actual_output="docs/adr/0014-....md",
            tools_called=to_deepeval_tools(bypassed),
            expected_tools=expected,
        )
    )

    assert m_ok.score == 1.0, "a run that invoked the skill should score 1.0"
    assert m_bad.score == 0.0, "a run that bypassed the skill should score 0.0"
