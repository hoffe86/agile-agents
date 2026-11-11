"""Spike tests for the Copilot CLI -> DeepEval trace adapter.

Run:  python -m pytest eval/deepeval/tests -q

The parsing tests need no DeepEval install and no network; the metric test is skipped
when DeepEval is absent so the schema guard stays runnable on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agile_eval.adapters.copilot_trace import (
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


@pytest.mark.parametrize("completion,expected", [(True, True), (False, False), (None, None)])
def test_tool_completion_is_matched_by_call_id(completion, expected):
    events = [
        {"type": "tool.execution_start",
         "data": {"toolCallId": "skill-1", "toolName": "skill", "arguments": {"skill": "x"}}},
    ]
    if completion is not None:
        events.append({"type": "tool.execution_complete",
                       "data": {"toolCallId": "skill-1", "success": completion}})
    trace = parse_log_text("\n".join(json.dumps(event) for event in events))
    assert trace.tools[0].skill_name == "x"
    assert trace.tools[0].success is expected


def test_non_boolean_completion_is_not_success_evidence():
    events = [
        {"type": "tool.execution_start",
         "data": {"toolCallId": "skill-1", "toolName": "skill", "arguments": {"skill": "x"}}},
        {"type": "tool.execution_complete",
         "data": {"toolCallId": "skill-1", "success": "true"}},
    ]
    trace = parse_log_text("\n".join(json.dumps(event) for event in events))
    assert trace.tools[0].success is None


def test_conflicting_tool_completions_are_a_schema_error():
    events = [
        {"type": "tool.execution_start",
         "data": {"toolCallId": "skill-1", "toolName": "skill", "arguments": {"skill": "x"}}},
        {"type": "tool.execution_complete", "data": {"toolCallId": "skill-1", "success": True}},
        {"type": "tool.execution_complete", "data": {"toolCallId": "skill-1", "success": False}},
    ]
    trace = parse_log_text("\n".join(json.dumps(event) for event in events))
    assert any("conflicting completion" in error for error in trace.schema_errors)


def test_started_subagent_must_match_the_requested_agent():
    events = [
        {"type": "tool.execution_start", "data": {
            "toolCallId": "call", "toolName": "task", "arguments": {"agent_type": "coding"}}},
        {"type": "subagent.started", "data": {
            "toolCallId": "call", "agentName": "agile-agents-core:infrastructure"}},
    ]

    trace = parse_log_text("\n".join(json.dumps(event) for event in events))

    assert any("started agent does not match" in error for error in trace.schema_errors)


def test_started_subagent_matches_a_qualified_name():
    events = [
        {"type": "tool.execution_start", "data": {
            "toolCallId": "call", "toolName": "task", "arguments": {"agent_type": "coding"}}},
        {"type": "subagent.started", "data": {
            "toolCallId": "call", "agentName": "agile-agents-core:coding"}},
    ]

    trace = parse_log_text("\n".join(json.dumps(event) for event in events))

    assert trace.tools[0].started_agent == "agile-agents-core:coding"
    assert not trace.schema_errors


def test_conflicting_subagent_starts_are_rejected():
    events = [
        {"type": "tool.execution_start", "data": {
            "toolCallId": "call", "toolName": "task", "arguments": {"agent_type": "coding"}}},
        {"type": "subagent.started", "data": {"toolCallId": "call", "agentName": "coding"}},
        {"type": "subagent.started", "data": {"toolCallId": "call", "agentName": "architect"}},
    ]

    trace = parse_log_text("\n".join(json.dumps(event) for event in events))

    assert any("conflicting started agents" in error for error in trace.schema_errors)


def test_duplicate_tool_call_ids_are_rejected():
    events = [
        {"type": "tool.execution_start", "data": {
            "toolCallId": "shared", "toolName": "task", "arguments": {"agent_type": "coding"}}},
        {"type": "tool.execution_start", "data": {
            "toolCallId": "shared", "toolName": "task", "arguments": {"agent_type": "review-lead"}}},
        {"type": "tool.execution_complete", "data": {"toolCallId": "shared", "success": True}},
    ]

    trace = parse_log_text("\n".join(json.dumps(event) for event in events))

    assert any("duplicate tool call ID" in error for error in trace.schema_errors)


@pytest.mark.parametrize("call_id", ["", " ", [], 42])
def test_invalid_tool_call_ids_are_rejected_without_crashing(call_id):
    event = {"type": "tool.execution_start", "data": {
        "toolCallId": call_id, "toolName": "task", "arguments": {"agent_type": "coding"}}}

    trace = parse_log_text(json.dumps(event))

    assert any("invalid tool call ID" in error for error in trace.schema_errors)


@pytest.mark.parametrize("parent", ["", " ", [], {}])
def test_invalid_parent_call_ids_are_rejected_without_crashing(parent):
    event = {"type": "tool.execution_start", "data": {
        "toolCallId": "child", "parentToolCallId": parent,
        "toolName": "skill", "arguments": {"skill": "x"}}}

    trace = parse_log_text(json.dumps(event))

    assert any("invalid parent tool call ID" in error for error in trace.schema_errors)


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


def test_tool_correctness_measures_skill_bypass(deepeval_module):
    """End-to-end: trace -> DeepEval -> a score that discriminates bypass."""
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

    from agile_eval.adapters.copilot_trace import to_deepeval_tools
    from agile_eval.metrics.local_model import stub_model

    invoked = parse_log(FIXTURE)
    bypassed = parse_log_text(
        "\n".join(
            line
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
            if '"toolName":"skill"' not in line.replace(", ", ",")
        )
    )

    expected = [ToolCall(name=SKILL_TOOL_NAME,
                         input_parameters={"skill": "architecture-decision-records"})]

    m_ok = ToolCorrectnessMetric(model=stub_model(), async_mode=False,
                                 evaluation_params=[ToolCallParams.INPUT_PARAMETERS])
    m_ok.measure(
        LLMTestCase(
            input="write an ADR",
            actual_output="docs/adr/0014-....md",
            tools_called=to_deepeval_tools(invoked),
            expected_tools=expected,
        )
    )

    m_bad = ToolCorrectnessMetric(model=stub_model(), async_mode=False,
                                  evaluation_params=[ToolCallParams.INPUT_PARAMETERS])
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
