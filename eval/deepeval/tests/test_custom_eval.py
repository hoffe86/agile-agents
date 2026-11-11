"""Offline tests for the DeepEval custom-eval pipeline (agile_eval.custom_eval).

No Copilot CLI, no network, no model: the trajectory metrics run DeepEval's
ToolCorrectnessMetric against a stub model, the judge is exercised with a fake.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agile_eval.adapters.copilot_trace import parse_log, parse_log_text
from agile_eval.custom_eval import checks, judges, plan_approval, runner, scorer
from agile_eval.custom_eval.expectations import (
    Check,
    Criterion,
    ExpectationsError,
    from_mapping,
    load,
    parse_acceptance,
)
from agile_eval.custom_eval.trajectory import (
    IMPLEMENTATION_AGENTS,
    check_plan_gate,
    delegated_agents,
    short_agent,
    skills_by_short_agent,
)

FIXTURE = Path(__file__).parent / "fixtures" / "copilot-subagent-session.jsonl"
TASKS = runner.default_tasks_root()
TASK_DIRS = sorted(p for p in TASKS.iterdir() if p.is_dir())
CRITERIA = (Criterion(1, "one"), Criterion(2, "two"))


def _base(**overrides) -> dict:
    data = {
        "schema": 1, "root_agent": "dev-lead", "plan_gate": "required",
        "agents": ["coding"], "skills": {"coding": ["testing-practices"]},
    }
    data.update(overrides)
    return data


@pytest.fixture(scope="module")
def trace():
    return parse_log(FIXTURE)


# --- expectations -----------------------------------------------------------------------

@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=lambda p: p.name)
def test_every_task_has_loadable_expectations(task_dir):
    exp = load(task_dir)
    assert exp.task == task_dir.name
    assert exp.plan_gate == "required"
    assert [c.id for c in exp.criteria] == list(range(1, len(exp.criteria) + 1))
    assert "reviewer-read-only-rules" in exp.skills["review-lead"]
    assert "code-review-checklist" in exp.forbidden_skills["review-lead"]


def test_parse_acceptance_joins_continuation_lines():
    criteria = parse_acceptance("# Title\n\n1. **A** first\n   continues\n2. second\n")
    assert criteria == (Criterion(1, "**A** first continues"), Criterion(2, "second"))


@pytest.mark.parametrize("text", ["", "# no list\n", "1. a\n3. b\n"])
def test_parse_acceptance_rejects_missing_or_gapped_numbering(text):
    with pytest.raises(ExpectationsError):
        parse_acceptance(text)


@pytest.mark.parametrize("overrides", [
    {"schema": 2},
    {"plan_gate": "sometimes"},
    {"surprise": True},
    {"skills": {}},
    {"skills": {"architect": ["x"]}},
    {"forbidden_skills": {"coding": ["testing-practices"]}},
    {"unverifiable": {9: "no such criterion"}},
])
def test_from_mapping_rejects_invalid_expectations(overrides):
    with pytest.raises(ExpectationsError):
        from_mapping(_base(**overrides), "t", CRITERIA)


def test_from_mapping_accepts_any_agent_and_known_unverifiable():
    exp = from_mapping(_base(skills={"any": ["pr-description"]}, unverifiable={2: "why"}),
                       "t", CRITERIA)
    assert exp.skills["any"] == ("pr-description",)
    assert exp.unverifiable == {2: "why"}


def test_from_mapping_parses_checks_with_defaults():
    exp = from_mapping(_base(checks=[
        {"criterion": 1, "run": ["dotnet", "build"]},
        {"criterion": 1, "run": ["{python}", "-m", "pytest"], "cwd": "src/app", "timeout": 30,
         "requires": [["{python}", "-m", "pytest", "--version"]], "on_pass": "judge",
         "fail_if_output_matches": "Warning"},
    ]), "t", CRITERIA)
    assert exp.checks[0] == Check(1, ("dotnet", "build"))
    assert exp.checks[1].requires == (("{python}", "-m", "pytest", "--version"),)
    assert exp.checks[1].on_pass == "judge" and exp.checks[1].cwd == "src/app"


@pytest.mark.parametrize("check", [
    {"criterion": 9, "run": ["x"]},
    {"criterion": 2, "run": ["x"]},  # also declared unverifiable below
    {"criterion": True, "run": ["x"]},
    {"criterion": 1, "run": []},
    {"criterion": 1, "run": "dotnet build"},
    {"criterion": 1, "run": ["x"], "cwd": "../outside"},
    {"criterion": 1, "run": ["x"], "cwd": "/abs"},
    {"criterion": 1, "run": ["x"], "timeout": 0},
    {"criterion": 1, "run": ["x"], "on_pass": "maybe"},
    {"criterion": 1, "run": ["x"], "fail_if_output_matches": "("},
    {"criterion": 1, "run": ["x"], "requires": [[]]},
    {"criterion": 1, "run": ["x"], "shell": True},
])
def test_from_mapping_rejects_invalid_checks(check):
    with pytest.raises(ExpectationsError):
        from_mapping(_base(checks=[check], unverifiable={2: "why"}), "t", CRITERIA)


# --- trajectory + DeepEval metrics -------------------------------------------------------

def test_short_agent_strips_plugin_prefix_and_maps_top_level_to_root():
    assert short_agent("agile-agents-core:coding", "dev-lead") == "coding"
    assert short_agent(None, "dev-lead") == "dev-lead"


def test_fixture_attribution_and_gate_violation(trace):
    assert delegated_agents(trace, "dev-lead") == ["coding", "review-lead"]
    skills = skills_by_short_agent(trace, "dev-lead")
    assert "dev-lead-templates" in skills["dev-lead"]
    assert not skills.get("coding")
    gate = check_plan_gate(trace, IMPLEMENTATION_AGENTS)
    assert not gate.honoured
    assert "coding" in gate.violations[0]


def _trace_with_events(*events):
    return parse_log_text("\n".join(json.dumps(event) for event in events))


def _plan_events():
    arguments = {
        "question": "Approve the plan to start the autonomous run?",
        "choices": ["Approve and run autonomously", "Adjust plan", "Cancel"],
    }
    return [
        {"type": "assistant.turn_start", "data": {}},
        {"type": "assistant.message", "data": {"content": "The proposed plan."}},
        {"type": "tool.execution_start", "id": "span", "data": {
            "toolName": "ask_user", "toolCallId": "call", "arguments": arguments}},
        {"type": "external_tool.requested", "parentId": "span", "data": {
            "requestId": "request", "sessionId": "session", "toolCallId": "call",
            "toolName": "ask_user", "arguments": dict(arguments)}},
    ]


def test_pending_top_level_plan_request_verifies_the_gate():
    gate = check_plan_gate(_trace_with_events(*_plan_events()), phase1_changes=())
    assert gate.honoured is True
    assert gate.request.request_id == "request"
    assert gate.request.visible_message == "The proposed plan."


def test_transient_external_tool_completion_does_not_close_the_durable_request():
    events = _plan_events()
    events.append({"type": "external_tool.completed", "ephemeral": True,
                   "data": {"requestId": "request"}})
    assert check_plan_gate(_trace_with_events(*events), phase1_changes=()).honoured is True


@pytest.mark.parametrize("change", [
    "unrelated-question", "wrong-choices", "subagent", "mismatched-call",
    "mismatched-span", "different-arguments", "completed", "multiple-requests",
])
def test_only_the_original_pending_top_level_plan_request_verifies_the_gate(change):
    events = _plan_events()
    request = events[-1]
    if change == "unrelated-question":
        request["data"]["arguments"]["question"] = "Which database?"
        events[-2]["data"]["arguments"]["question"] = "Which database?"
    elif change == "wrong-choices":
        request["data"]["arguments"]["choices"] = ["Approve", "Reject"]
        events[-2]["data"]["arguments"]["choices"] = ["Approve", "Reject"]
    elif change == "subagent":
        request["agentId"] = "child"
    elif change == "mismatched-call":
        request["data"]["toolCallId"] = "other"
    elif change == "mismatched-span":
        request["parentId"] = "other"
    elif change == "different-arguments":
        request["data"]["arguments"]["question"] = "Approve a different plan?"
    elif change == "completed":
        events.append({"type": "external_tool.completed", "data": {"requestId": "request"}})
    elif change == "multiple-requests":
        events.append({**request, "data": {**request["data"], "requestId": "other"}})
    assert check_plan_gate(_trace_with_events(*events), phase1_changes=()).honoured is None


def test_implementation_before_a_pending_plan_request_fails_the_gate():
    events = _plan_events()
    events.insert(1, {"type": "tool.execution_start", "data": {
        "toolName": "task", "toolCallId": "delegate", "arguments": {"agent_type": "coding"}}})
    assert check_plan_gate(_trace_with_events(*events)).honoured is False


def test_subagent_message_cannot_replace_the_plan_shown_at_the_gate():
    events = _plan_events()
    events.insert(-2, {"type": "assistant.message", "agentId": "child",
                       "data": {"content": "A different subagent message."}})
    request = check_plan_gate(_trace_with_events(*events), phase1_changes=()).request
    assert request.visible_message == "The proposed plan."


def test_plan_request_without_workspace_evidence_is_unverified():
    gate = check_plan_gate(_trace_with_events(*_plan_events()))
    assert gate.honoured is None
    assert "workspace" in gate.reason


def test_workspace_changes_before_a_plan_request_fail_the_gate():
    gate = check_plan_gate(_trace_with_events(*_plan_events()),
                           phase1_changes=("src/service.py", "tests/test_service.py"))
    assert gate.honoured is False
    assert "src/service.py" in gate.reason


def _skill_trace(skill, outcome, agent="coding"):
    events = [
        {"type": "tool.execution_start", "data": {
            "toolName": "task", "toolCallId": "parent",
            "arguments": {"agent_type": agent}}},
        {"type": "subagent.started", "data": {"toolCallId": "parent", "agentName": agent}},
        {"type": "tool.execution_start", "data": {
            "toolName": "skill", "toolCallId": "skill-1", "parentToolCallId": "parent",
            "arguments": {"skill": skill}}},
    ]
    if outcome is not None:
        events.append({"type": "tool.execution_complete",
                       "data": {"toolCallId": "skill-1", "success": outcome}})
    return _trace_with_events(*events)


def _delegation_events(call_id, completion, started=False, agent="agile-agents-core:coding"):
    events = [
        {"type": "tool.execution_start", "data": {
            "toolName": "task", "toolCallId": call_id,
            "arguments": {"agent_type": agent}}},
    ]
    if started:
        events.append({"type": "subagent.started", "data": {
            "toolCallId": call_id, "agentName": agent}})
    if completion is not None:
        events.append({"type": "tool.execution_complete", "data": {
            "toolCallId": call_id, "success": completion}})
    return events


@pytest.mark.parametrize(("started", "completion", "passed", "score", "reason"), [
    (False, False, False, 0.0, "delegation failed"),
    (False, None, None, None, "delegation outcome unavailable"),
    (False, True, True, 1.0, "all expected agents delegated"),
    (True, False, True, 1.0, "all expected agents delegated"),
    (True, None, True, 1.0, "all expected agents delegated"),
])
def test_delegation_metric_requires_evidence_the_agent_started(
        started, completion, passed, score, reason):
    from agile_eval.custom_eval.metrics import delegation_metric

    exp = from_mapping(_base(), "t", CRITERIA)
    trace = _trace_with_events(*_delegation_events("call", completion, started))

    metric = delegation_metric(trace, exp)

    assert metric.passed is passed
    assert metric.score == score
    assert reason in metric.reason
    assert metric.actual == ["coding"]


def test_successful_retry_confirms_a_previously_failed_delegation():
    from agile_eval.custom_eval.metrics import delegation_metric

    exp = from_mapping(_base(), "t", CRITERIA)
    events = (_delegation_events("first", False)
              + _delegation_events("retry", None, started=True))

    assert delegation_metric(_trace_with_events(*events), exp).passed is True


def test_unknown_retry_leaves_a_previously_failed_delegation_unverified():
    from agile_eval.custom_eval.metrics import delegation_metric

    exp = from_mapping(_base(), "t", CRITERIA)
    events = _delegation_events("first", False) + _delegation_events("retry", None)

    metric = delegation_metric(_trace_with_events(*events), exp)

    assert metric.passed is None
    assert metric.score is None


@pytest.mark.parametrize(("first", "retry", "passed"), [
    (None, False, None),
    (True, False, True),
])
def test_retry_evidence_is_not_overwritten_by_a_later_failure(first, retry, passed):
    from agile_eval.custom_eval.metrics import delegation_metric

    exp = from_mapping(_base(), "t", CRITERIA)
    events = _delegation_events("first", first) + _delegation_events("retry", retry)

    assert delegation_metric(_trace_with_events(*events), exp).passed is passed


def test_failed_delegation_remains_failed_when_another_is_unverified():
    from agile_eval.custom_eval.metrics import delegation_metric

    exp = from_mapping(_base(agents=["coding", "review-lead"]), "t", CRITERIA)
    events = (_delegation_events("coding", False)
              + _delegation_events("review", None, agent="agile-agents-core:review-lead"))

    metric = delegation_metric(_trace_with_events(*events), exp)

    assert metric.passed is False
    assert "delegation failed: coding" in metric.reason
    assert "delegation outcome unavailable: review-lead" in metric.reason


def test_failed_delegation_still_violates_the_pre_approval_gate():
    trace = _trace_with_events(*_delegation_events("call", False), *_plan_events())

    assert check_plan_gate(trace).honoured is False


@pytest.mark.parametrize(("completion", "passed", "score", "reason"), [
    (False, False, 0.0, "delegation failed before the agent started"),
    (None, None, None, "delegation outcome unavailable"),
])
def test_skill_metric_explains_unconfirmed_agent_delegation(completion, passed, score, reason):
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(_base(), "t", CRITERIA)
    trace = _trace_with_events(*_delegation_events("call", completion))

    (metric,) = skill_metrics(trace, exp)

    assert metric.passed is passed
    assert metric.score == score
    assert reason in metric.reason


@pytest.mark.parametrize("tool", ["view", "ask_user"])
def test_no_implementation_does_not_prove_a_plan_approval_request(tool):
    trace = _trace_with_events(
        {"type": "assistant.turn_start", "data": {}},
        {"type": "tool.execution_start", "data": {
            "toolName": tool, "toolCallId": "call", "arguments": {"question": "Approve the plan?"}}},
        {"type": "assistant.message", "data": {"content": "The plan looks ready."}},
    )
    gate = check_plan_gate(trace)
    assert gate.honoured is None and not gate.violations
    assert "could not be verified" in gate.reason


def test_top_level_writes_still_fail_the_plan_gate():
    trace = _trace_with_events(
        {"type": "tool.execution_start", "data": {
            "toolName": "apply_patch", "toolCallId": "write", "arguments": "patch"}},
    )
    gate = check_plan_gate(trace)
    assert gate.honoured is False
    assert "apply_patch" in gate.reason


def test_deepeval_metrics_score_skills_per_agent(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import delegation_metric, plan_gate_metric, skill_metrics

    exp = load(TASKS / "task-02-python-di-refactor")
    by_name = {m.name: m for m in skill_metrics(trace, exp)}
    assert by_name["skills:dev-lead"].passed is None
    assert "completion unavailable" in by_name["skills:dev-lead"].reason
    assert by_name["skills:coding"].score == 0.0
    assert "python-implementation" in by_name["skills:coding"].reason
    assert "never delegated" in by_name["skills:code-reviewer"].reason
    delegation = delegation_metric(trace, exp)
    assert delegation.score == 0.5 and delegation.passed is False
    gate, _ = plan_gate_metric(trace, exp)
    assert gate.passed is False


def test_forbidden_skill_zeroes_the_agent_score(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(
        _base(agents=[], skills={"dev-lead": ["read-repo-context"]},
              forbidden_skills={"dev-lead": ["cost-budget"]}),
        "t", CRITERIA,
    )
    (metric,) = skill_metrics(trace, exp)
    assert metric.score == 0.0
    assert "forbidden skill invoked: cost-budget" in metric.reason


def test_any_agent_skill_is_satisfied_by_whoever_loads_it(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(_base(agents=[], skills={"any": ["test-bar-gate"]}), "t", CRITERIA)
    (metric,) = skill_metrics(_skill_trace("test-bar-gate", True), exp)
    assert metric.passed is True


@pytest.mark.parametrize(("completion", "passed", "reason"), [
    (True, True, "loaded successfully"),
    (False, False, "skill load failed"),
    (None, None, "skill completion unavailable"),
])
def test_skill_metric_requires_successful_completion_for_the_correct_agent(
        completion, passed, reason):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(_base(agents=["coding"], skills={"coding": ["testing-practices"]}),
                       "t", CRITERIA)
    (metric,) = skill_metrics(_skill_trace("testing-practices", completion), exp)
    assert metric.passed is passed
    assert reason in metric.reason
    assert metric.actual == ["testing-practices"]
    if completion is None:
        assert metric.score is None


def test_successful_skill_load_by_another_agent_does_not_satisfy_the_expected_agent():
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(_base(agents=["coding", "architect"],
                             skills={"coding": ["testing-practices"]}), "t", CRITERIA)
    (metric,) = skill_metrics(_skill_trace("testing-practices", True, "architect"), exp)
    assert metric.passed is False
    assert "not invoked: testing-practices" in metric.reason


def test_successful_retry_satisfies_a_previously_failed_skill():
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    events = []
    for call_id, success in [("first", False), ("retry", True)]:
        events.extend([
            {"type": "tool.execution_start", "data": {
                "toolName": "skill", "toolCallId": call_id,
                "arguments": {"skill": "read-repo-context"}}},
            {"type": "tool.execution_complete",
             "data": {"toolCallId": call_id, "success": success}},
        ])
    exp = from_mapping(_base(agents=[], skills={"dev-lead": ["read-repo-context"]}),
                       "t", CRITERIA)
    (metric,) = skill_metrics(_trace_with_events(*events), exp)
    assert metric.passed is True
    assert metric.actual == ["read-repo-context"]


# --- judge ------------------------------------------------------------------------------

@pytest.mark.parametrize("statuses,verdict", [
    (["PASS", "PASS"], "RESOLVED"),
    (["FAIL", "FAIL"], "FAILED"),
    (["FAIL", "UNVERIFIED"], "FAILED"),
    (["PASS", "UNVERIFIED"], "UNVERIFIED"),
    (["PASS", "FAIL"], "PARTIAL"),
])
def test_verdict_rule(statuses, verdict):
    assert judges.verdict_for(statuses) == verdict


def test_parse_contract_recomputes_verdict_and_flags_contract_errors():
    good = judges.parse_contract("1. PASS - ok\n2. FAIL - bad\nVERDICT: RESOLVED", CRITERIA, "x")
    assert good.verdict == "PARTIAL" and good.claimed_verdict == "RESOLVED"
    assert not good.contract_errors
    bad = judges.parse_contract("1. PASS - ok\n1. PASS - again\n7. FAIL - ?", CRITERIA, "x")
    assert len(bad.contract_errors) == 4
    assert bad.criteria[1].status == "UNVERIFIED"


def test_none_judge_marks_every_criterion_unverified():
    result = judges.judge("none", "p", CRITERIA, {2: "known"}, "diff")
    assert result.verdict == "UNVERIFIED"
    assert [r.reason for r in result.criteria] == ["no judge configured", "known"]


def test_model_judge_cannot_credit_a_known_unverifiable_criterion(monkeypatch):
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - fine\n2. PASS - also fine\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    result = judges.judge("azure-openai", "task", CRITERIA, {2: "unresolved"}, "x" * 200_000)
    assert [r.status for r in result.criteria] == ["PASS", "UNVERIFIED"]
    assert result.verdict == "UNVERIFIED"
    assert "[evidence truncated]" in seen["prompt"]


def test_model_judge_hides_sdk_error_text(monkeypatch):
    class Exploding:
        def generate(self, prompt):
            raise RuntimeError("https://secret.example token=abc")

    monkeypatch.setattr(judges, "azure_openai_model", Exploding)
    with pytest.raises(judges.JudgeError) as info:
        judges.judge("azure-openai", "t", CRITERIA, {}, "d")
    assert "secret" not in str(info.value)


@pytest.mark.parametrize("kind", ["acceptance", "plan"])
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 503])
def test_model_judges_report_safe_http_status(monkeypatch, kind, status):
    import httpx2
    import openai

    class Exploding:
        def generate(self, prompt):
            request = httpx2.Request("POST", "https://secret.example")
            response = httpx2.Response(status, request=request)
            raise openai.APIStatusError(
                "token=abc", response=response, body={"token": "abc"}
            )

    module = judges if kind == "acceptance" else plan_approval
    monkeypatch.setattr(module, "azure_openai_model", Exploding)
    with pytest.raises(judges.JudgeError) as info:
        if kind == "acceptance":
            judges.judge("azure-openai", "t", CRITERIA, {}, "d")
        else:
            plan_approval.decide("t", CRITERIA, "plan")
    assert f"HTTP {status}" in str(info.value)
    assert "secret" not in str(info.value)
    assert "token" not in str(info.value)


def test_model_call_error_does_not_echo_untrusted_status_or_type():
    class PrivateError(Exception):
        status_code = "403 token=abc"

    error = judges.model_call_error("judge failed", PrivateError("secret"))
    assert str(error) == "judge failed (unexpected error)"


def test_azure_judge_requires_endpoint_configuration(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    with pytest.raises(judges.JudgeError, match="AZURE_OPENAI_ENDPOINT"):
        judges.azure_openai_model()


@pytest.mark.parametrize("endpoint", [
    "https://example.services.ai.azure.com/openai/v1/responses",
    "https://example.services.ai.azure.com/api/projects/example",
    "https://example.openai.azure.com/openai/v1",
    "https://example.cognitiveservices.azure.com/openai/v1/responses",
    "http://example.openai.azure.com",
    "https://example.openai.azure.com?api-version=2024-10-21",
    "https://user:password@example.openai.azure.com",
    "https://example.openai.azure.com:bad",
    "https://[invalid",
])
def test_azure_judge_rejects_invalid_or_operation_endpoints(monkeypatch, endpoint):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "example")

    with pytest.raises(judges.JudgeError, match="AZURE_OPENAI_ENDPOINT"):
        judges.azure_openai_model()


@pytest.mark.parametrize("endpoint", [
    "https://example.openai.azure.com/",
    "https://example.services.ai.azure.com",
    "https://example.cognitiveservices.azure.com/",
])
def test_azure_judge_uses_resource_endpoint(monkeypatch, endpoint):
    import deepeval.models

    seen = {}

    def provider():
        return "token"

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", endpoint)
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "example")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    monkeypatch.setattr(judges, "_az_token_provider", lambda: provider)
    monkeypatch.setattr(deepeval.models, "AzureOpenAIModel", lambda **kwargs: seen.update(kwargs))

    judges.azure_openai_model()
    assert seen["base_url"] == endpoint
    assert seen["deployment_name"] == "example"
    assert seen["azure_ad_token_provider"] is provider


@pytest.mark.parametrize(("name", "value"), [
    ("AZURE_OPENAI_API_KEY", "test-key"),
    ("AZURE_OPENAI_API_KEY", ""),
    ("AZURE_OPENAI_AD_TOKEN", "test-token"),
    ("AZURE_OPENAI_AD_TOKEN", ""),
])
def test_azure_judge_rejects_ambient_credentials(monkeypatch, name, value):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "example")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(judges, "_az_token_provider", lambda: pytest.fail("token provider used"))

    with pytest.raises(judges.JudgeError, match=f"unset {name}"):
        judges.azure_openai_model()


def test_azure_judge_uses_entra_and_deployment_chat_route(monkeypatch):
    import httpx2
    import openai
    from deepeval.models.llms import azure_model

    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "answer"},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "test-deployment")
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-4.1")
    monkeypatch.setenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    monkeypatch.setattr(judges, "_az_token_provider", lambda: lambda: "test-entra-token")
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http_client:
        monkeypatch.setattr(azure_model, "AzureOpenAI",
                            lambda **kwargs: openai.AzureOpenAI(**kwargs, http_client=http_client))
        output, _ = judges.azure_openai_model().generate("test prompt")

    assert output == "answer"
    assert len(requests) == 1
    assert requests[0].url.path == "/openai/deployments/test-deployment/chat/completions"
    assert requests[0].url.params["api-version"] == "2024-10-21"
    assert requests[0].headers["authorization"] == "Bearer test-entra-token"
    assert "api-key" not in requests[0].headers


@pytest.mark.parametrize("kind", ["acceptance", "plan"])
def test_azure_judges_retry_with_default_temperature_when_zero_is_rejected(monkeypatch, caplog, kind):
    import httpx2
    import openai
    from deepeval.models.llms import azure_model

    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx2.Response(400, json={"error": {
                "code": "unsupported_value", "param": "temperature", "message": "private",
            }})
        return httpx2.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0, "model": "test",
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "1. PASS - covered\nVERDICT: RESOLVED",
            }, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "test-deployment")
    monkeypatch.setenv("AZURE_OPENAI_MODEL", "gpt-4.1")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_AD_TOKEN", raising=False)
    monkeypatch.setattr(judges, "_az_token_provider", lambda: lambda: "test-entra-token")
    criteria = (Criterion(1, "covered"),)
    with httpx2.Client(transport=httpx2.MockTransport(respond)) as http_client:
        monkeypatch.setattr(azure_model, "AzureOpenAI",
                            lambda **kwargs: openai.AzureOpenAI(**kwargs, http_client=http_client))
        if kind == "plan":
            result = plan_approval.decide("requirement", criteria, "plan")
            assert result.approved
        else:
            result = judges.judge("azure-openai", "requirement", criteria, {}, "diff")
            assert result.verdict == "RESOLVED"

    assert len(requests) == 2
    assert requests[0]["temperature"] == 0
    assert "temperature" not in requests[1]
    assert requests[0]["messages"] == requests[1]["messages"]
    assert "default temperature" in caplog.text
    assert "private" not in caplog.text


@pytest.mark.parametrize(("code", "param"), [
    ("unsupported_value", "model"),
    ("unsupported_parameter", "temperature"),
    ("invalid_request_error", "temperature"),
])
def test_azure_judge_does_not_retry_other_bad_requests(monkeypatch, code, param):
    import httpx2
    import openai

    class Exploding:
        temperature = 0
        calls = 0

        def generate(self, prompt):
            self.calls += 1
            request = httpx2.Request("POST", "https://example.invalid")
            response = httpx2.Response(400, request=request)
            raise openai.BadRequestError(
                "private", response=response, body={"code": code, "param": param},
            )

    model = Exploding()
    monkeypatch.setattr(judges, "azure_openai_model", lambda: model)
    with pytest.raises(judges.JudgeError, match="HTTP 400"):
        judges.judge("azure-openai", "t", CRITERIA, {}, "diff")
    assert model.calls == 1


def test_azure_judge_reports_failure_if_default_temperature_also_fails(monkeypatch):
    import httpx2
    import openai

    class Exploding:
        temperature = 0
        calls = 0

        def generate(self, prompt):
            self.calls += 1
            request = httpx2.Request("POST", "https://example.invalid")
            response = httpx2.Response(400, request=request)
            raise openai.BadRequestError(
                "private", response=response,
                body={"code": "unsupported_value", "param": "temperature"},
            )

    model = Exploding()
    monkeypatch.setattr(judges, "azure_openai_model", lambda: model)
    with pytest.raises(judges.JudgeError, match="HTTP 400"):
        judges.judge("azure-openai", "t", CRITERIA, {}, "diff")
    assert model.calls == 2


def test_model_judge_sees_command_results_as_evidence(monkeypatch):
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - ok\n2. PASS - ok\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    judges.judge("azure-openai", "t", CRITERIA, {}, "diff", command_evidence="BUILD-OUTPUT")
    assert "<command-results>\nBUILD-OUTPUT\n</command-results>" in seen["prompt"]


def test_model_judge_sees_the_final_response_as_separate_untrusted_evidence(monkeypatch):
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - ok\n2. PASS - ok\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    judges.judge("azure-openai", "t", CRITERIA, {}, "DIFF",
                 final_response="## What\nThe answer.")
    assert "<final-response>\n## What\nThe answer.\n</final-response>" in seen["prompt"]
    assert "not proof of workspace changes" in seen["prompt"]
    assert "<evidence>\nDIFF\n</evidence>" in seen["prompt"]


def test_oversized_final_response_is_unverified_without_a_model_call(monkeypatch):
    monkeypatch.setattr(judges, "azure_openai_model",
                        lambda: pytest.fail("oversized response reached the model"))
    result = judges.judge("azure-openai", "t", CRITERIA, {}, "diff",
                          final_response="x" * (judges.MAX_EVIDENCE_CHARS + 1))
    assert result.verdict == "UNVERIFIED"
    assert all(r.status == "UNVERIFIED" and "limit" in r.reason for r in result.criteria)


def test_final_response_at_the_evidence_limit_reaches_the_model_intact(monkeypatch):
    final = "x" * judges.MAX_EVIDENCE_CHARS
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - ok\n2. PASS - ok\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    result = judges.judge("azure-openai", "t", CRITERIA, {}, "diff", final_response=final)
    assert result.verdict == "RESOLVED"
    assert f"<final-response>\n{final}\n</final-response>" in seen["prompt"]


# --- command checks ---------------------------------------------------------------------

PY = "{python}"


def _run(tmp_path, check: Check) -> dict:
    (tmp_path / "ws").mkdir(exist_ok=True)
    return checks.run_check(check, 0, tmp_path / "ws", tmp_path, checks.check_env())


@pytest.mark.parametrize("check,status,reason", [
    (Check(1, (PY, "-c", "print('ok')")), "passed", "exit code 0"),
    (Check(1, (PY, "-c", "raise SystemExit(3)")), "failed", "exit code 3"),
    (Check(1, (PY, "-c", "print('x.bicep(1,2) : Warning no-unused: y')"),
           fail_if_output_matches=r"\(\d+,\d+\) : Warning "),
     "failed", "output matched the failure pattern"),
    (Check(1, ("no-such-tool-xyz", "build")), "unavailable", "no-such-tool-xyz is not installed"),
    (Check(1, (PY, "-c", "print(1)"), requires=((PY, "-c", "raise SystemExit(1)"),)),
     "unavailable", "failed"),
    (Check(1, (PY, "-c", "print(1)"), cwd="missing"), "failed", "does not exist"),
    (Check(1, (PY, "-c", "import time; time.sleep(30)"), timeout=1), "timeout", "timed out"),
])
def test_run_check_statuses(tmp_path, check, status, reason):
    result = _run(tmp_path, check)
    assert result["status"] == status
    assert reason in result["reason"]


def test_run_check_never_passes_credentials_to_agent_code(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "tok-secret")
    monkeypatch.setenv("GITHUB_TOKEN", "actions-token")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "az-secret")
    script = "import os; print(sorted(k for k in os.environ if 'SECRET' in k or 'TOKEN' in k))"
    result = _run(tmp_path, Check(1, (PY, "-c", script)))
    assert result["status"] == "passed"
    assert "[]" in result["output_tail"] and "secret" not in result["output_tail"]


def test_run_checks_writes_matching_results(tmp_path):
    exp = from_mapping(_base(checks=[{"criterion": 2, "run": [PY, "-c", "print(2)"]}]),
                       "t", CRITERIA)
    (tmp_path / "ws").mkdir()
    checks.run_checks(exp, tmp_path / "ws", tmp_path)
    results = checks.load_results(tmp_path, exp)
    assert results and results[0]["status"] == "passed"
    assert (tmp_path / "checks" / "check-00.log").is_file()
    other = from_mapping(_base(checks=[{"criterion": 2, "run": [PY, "-c", "print(3)"]}]),
                         "t", CRITERIA)
    assert checks.load_results(tmp_path, other) is None


def _judgement(*statuses: str, reason: str = "judge says") -> judges.Judgement:
    rows = [judges.CriterionResult(i + 1, s, reason) for i, s in enumerate(statuses)]
    return judges.Judgement("j", rows, None, judges.verdict_for(list(statuses)), [])


def _result(index: int, criterion: int, status: str) -> dict:
    return {"index": index, "criterion": criterion, "command": f"cmd{index}", "status": status,
            "reason": "r", "cwd": "."}


@pytest.mark.parametrize("on_pass,statuses,judged,expected", [
    ("pass", ["passed"], "UNVERIFIED", "PASS"),
    ("pass", ["passed", "failed"], "PASS", "FAIL"),
    ("pass", ["passed", "timeout"], "PASS", "FAIL"),
    ("pass", ["passed", "unavailable"], "PASS", "UNVERIFIED"),
    ("judge", ["passed"], "FAIL", "FAIL"),
    ("judge", ["passed"], "PASS", "PASS"),
    ("judge", ["failed"], "PASS", "FAIL"),
])
def test_apply_checks_merge_rule(on_pass, statuses, judged, expected):
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": [f"cmd{i}"], "on_pass": on_pass}
                                     for i in range(len(statuses))]), "t", CRITERIA)
    results = [_result(i, 1, s) for i, s in enumerate(statuses)]
    judgement = _judgement(judged, "PASS")
    checks.apply_checks(judgement, exp, results)
    assert judgement.criteria[0].status == expected
    assert judgement.criteria[1].status == "PASS"
    assert judgement.verdict == judges.verdict_for([expected, "PASS"])


def test_apply_checks_without_results_leaves_checked_criteria_unverified():
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": ["x"]}]), "t", CRITERIA)
    judgement = _judgement("PASS", "PASS")
    checks.apply_checks(judgement, exp, None)
    assert judgement.criteria[0].status == "UNVERIFIED"
    assert "not run" in judgement.criteria[0].reason
    assert judgement.verdict == "UNVERIFIED"


def test_none_judge_gets_real_verdicts_from_commands():
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": ["a"]},
                                     {"criterion": 2, "run": ["b"], "on_pass": "judge"}]),
                       "t", CRITERIA)
    judgement = judges.judge("none", "p", CRITERIA, {}, "diff")
    checks.apply_checks(judgement, exp, [dict(_result(0, 1, "passed"), command="a"),
                                         dict(_result(1, 2, "passed"), command="b")])
    assert [r.status for r in judgement.criteria] == ["PASS", "UNVERIFIED"]
    assert judgement.criteria[1].reason == "commands passed; the remaining clause needs a judge"


# --- runner -----------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
def test_stage_copies_inputs_and_commits_a_baseline(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    assert len(baseline) == 40
    assert (paths.workspace / ".github" / "solution-profile.yaml").is_file()
    assert any(paths.workspace.rglob("*.py"))
    with pytest.raises(runner.SetupError, match="not empty"):
        runner.stage(TASKS / "task-02-python-di-refactor", paths)


@needs_git
def test_dry_run_records_a_redacted_command_and_needs_no_token(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    out = tmp_path / "run"
    assert runner.main(["task-05", "--out", str(out), "--dry-run", "--copilot", "copilot"]) == 0
    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "dry_run"
    cmd = state["command"]
    assert "<prompt.md>" in cmd and cmd[cmd.index("--agent") + 1] == runner.ROOT_AGENT
    assert "--no-ask-user" not in cmd and cmd.count("--plugin-dir") == 1
    assert cmd[cmd.index("--plugin-dir") + 1] == str(runner.repo_root() / "plugins/agile-agents-core")
    assert cmd[cmd.index("--phase") + 1] == "1"


def test_live_run_requires_explicit_unsandboxed_acknowledgement(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["task-05", "--out", str(tmp_path / "run")])


@pytest.mark.parametrize("value", [None, "", "   "])
def test_run_phase_refuses_without_a_token(tmp_path, monkeypatch, value):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    if value is not None:
        monkeypatch.setenv("COPILOT_GITHUB_TOKEN", value)
        monkeypatch.setenv("GITHUB_TOKEN", value)
    with pytest.raises(runner.SetupError, match="COPILOT_GITHUB_TOKEN or GITHUB_TOKEN"):
        runner.run_phase(["copilot"], runner.Paths(tmp_path), 1, 10)


@pytest.mark.parametrize("token_name", ["COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN"])
def test_run_phase_passes_the_configured_token_to_the_cli(tmp_path, monkeypatch, token_name):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv(token_name, "test-token")
    paths = runner.Paths(tmp_path)
    paths.workspace.mkdir()
    real_run = subprocess.run

    def run(command, **kwargs):
        if "--help" in command:
            return subprocess.CompletedProcess(command, 0,
                                               stdout="--sync-session --secret-env-vars")
        return real_run(command, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", run)
    script = ("import os, sys; "
              "print('configured' if os.environ.get(sys.argv[1]) == 'test-token' else 'missing')")
    assert runner.run_phase([sys.executable, "-c", script, token_name], paths, 1, 10) == 0
    assert paths.log(1).read_text(encoding="utf-8").strip() == "configured"


@needs_git
def test_phase1_blocks_when_a_plan_approval_request_cannot_be_verified(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path / "run")
    log = "\n".join(json.dumps(event) for event in [
        {"type": "user.message", "data": {"content": "requirement"}},
        {"type": "assistant.turn_start", "data": {}},
        {"type": "tool.execution_start", "data": {
            "toolName": "view", "toolCallId": "call", "arguments": {}}},
        {"type": "assistant.message", "data": {"content": "Plan ready for approval."}},
    ])

    def run_phase(cmd, paths, phase, timeout):
        paths.log(phase).write_text(log, encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, TASKS / "task-05-pr-description", paths)
    assert state["status"] == "blocked_approval"
    assert state["gate"]["honoured"] is None
    assert "could not be verified" in state["gate"]["reason"]
    assert not (paths.run / plan_approval.APPROVAL_FILE).exists()


@needs_git
def test_phase1_detects_a_shell_written_change_before_a_plan_request(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path / "run")
    monkeypatch.setattr(runner.uuid, "uuid4", lambda: "session")

    def run_phase(cmd, paths, phase, timeout):
        subprocess.run(
            [sys.executable, "-c",
             "from pathlib import Path; Path('bypass.py').write_text('implemented = True\\n')"],
            cwd=paths.workspace, check=True,
        )
        events = _plan_events()
        events.insert(1, {"type": "tool.execution_start", "data": {
            "toolName": "shell", "toolCallId": "shell", "arguments": {}}})
        paths.log(phase).write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, TASKS / "task-05-pr-description", paths)
    assert state["status"] == "gate_skipped"
    assert state["gate"]["honoured"] is False
    assert "bypass.py" in state["gate"]["reason"]
    assert json.loads(paths.phase1_changes.read_text(encoding="utf-8"))["paths"] == ["bypass.py"]
    row = scorer.score_run(paths.run, "none", TASKS)
    assert row["status"] == "failed"
    assert row["plan_gate"]["passed"] is False


@needs_git
def test_phase1_allows_telemetry_and_profile_setup_before_the_plan(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path / "run")
    monkeypatch.setattr(runner.uuid, "uuid4", lambda: "session")

    def run_phase(cmd, paths, phase, timeout):
        event_dir = paths.workspace / ".copilot-runs" / "run"
        event_dir.mkdir(parents=True)
        (event_dir / "events.jsonl").write_text("{}\n", encoding="utf-8")
        profile = paths.workspace / ".github" / "solution-profile.yaml"
        profile.write_text(profile.read_text(encoding="utf-8") + "\n# setup\n", encoding="utf-8")
        paths.log(phase).write_text("\n".join(json.dumps(e) for e in _plan_events()),
                                    encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, TASKS / "task-05-pr-description", paths)
    assert state["status"] == "awaiting_approval"
    assert json.loads(paths.phase1_changes.read_text(encoding="utf-8"))["paths"] == []


@needs_git
def test_phase1_allows_python_caches_before_the_plan(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path / "run")
    monkeypatch.setattr(runner.uuid, "uuid4", lambda: "session")

    def run_phase(cmd, paths, phase, timeout):
        bytecode = paths.workspace / "tests" / "__pycache__" / "test_module.cpython-311.pyc"
        bytecode.parent.mkdir(parents=True)
        bytecode.write_bytes(b"generated bytecode")
        cache = paths.workspace / ".pytest_cache" / "generated"
        cache.parent.mkdir()
        cache.write_text("generated", encoding="utf-8")
        paths.log(phase).write_text("\n".join(json.dumps(e) for e in _plan_events()),
                                    encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, TASKS / "task-05-pr-description", paths)
    assert state["status"] == "awaiting_approval"
    assert state["gate"]["honoured"] is True
    assert json.loads(paths.phase1_changes.read_text(encoding="utf-8"))["paths"] == []


@needs_git
def test_ungated_phase1_does_not_finish_with_a_pending_user_request(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path / "run")
    task_dir = TASKS / "task-05-pr-description"
    exp = replace(load(task_dir), plan_gate="not_applicable")
    monkeypatch.setattr(runner, "load", lambda _: exp)
    monkeypatch.setattr(runner.uuid, "uuid4", lambda: "session")

    def run_phase(cmd, paths, phase, timeout):
        paths.log(phase).write_text("\n".join(json.dumps(e) for e in _plan_events()),
                                    encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, task_dir, paths)
    assert state["status"] == "blocked_approval"
    assert "a user-input request was not approved" in state["errors"]


def test_phase2_without_a_decision_fails_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-05", "status": "awaiting_approval",
                               "session_id": "s", "phases": {}})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed"]) == 4
    assert "run --phase approve first" in capsys.readouterr().out
    assert runner.read_state(paths)["status"] == "awaiting_approval"


def test_phase2_refuses_a_run_that_is_not_awaiting_approval(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {"status": "gate_skipped"})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed"]) == 4


def test_verify_refuses_a_run_without_a_finished_change(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {"task": "task-02", "status": "awaiting_approval"})
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "verify",
                        "--unsandboxed"]) == 4
    assert not (tmp_path / checks.CHECKS_FILE).exists()


def test_verify_runs_agent_code_so_needs_the_unsandboxed_acknowledgement(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["task-02", "--out", str(tmp_path), "--phase", "verify"])


def test_runner_verify_records_check_counts_only_for_finished_runs(tmp_path):
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": [PY, "-c", "print(1)"]},
                                     {"criterion": 2, "run": ["no-such-tool-xyz"]}]),
                       "t", CRITERIA)
    paths = runner.Paths(tmp_path)
    paths.workspace.mkdir()
    pending = {"status": "awaiting_approval"}
    runner._verify(exp, paths, pending)
    assert "checks" not in pending and not (tmp_path / checks.CHECKS_FILE).exists()
    done = {"status": "gate_skipped"}
    runner._verify(exp, paths, done)
    assert done["checks"] == {"passed": 1, "unavailable": 1}


# --- scorer -----------------------------------------------------------------------------

# --- simulated plan approval ------------------------------------------------------------

RUBRIC = TASKS.parent / plan_approval.RUBRIC_FILE


def _approver(monkeypatch, answer: str, seen: dict | None = None):
    class FakeModel:
        def generate(self, prompt):
            if seen is not None:
                seen["prompt"] = prompt
            return answer, 0.0

    monkeypatch.setattr(plan_approval, "azure_openai_model", FakeModel)


def _answer(*statuses: str) -> str:
    lines = [f"{i}. {s} - reason {i}" for i, s in enumerate(statuses, 1)]
    return "\n".join(lines + ["VERDICT: RESOLVED"])


def _plan_decision(*statuses: str) -> plan_approval.PlanDecision:
    criteria = tuple(Criterion(i, f"criterion {i}") for i in range(1, len(statuses) + 1))
    judgement = judges.parse_contract(_answer(*statuses), criteria, plan_approval.SIMULATED)
    return plan_approval.PlanDecision(plan_approval.SIMULATED,
                                      all(status == "PASS" for status in statuses), judgement)


def test_shared_rubric_loads_and_task_criteria_number_on():
    shared = plan_approval.load_rubric(RUBRIC)
    assert len(shared) >= 5
    combined = plan_approval.load_rubric(RUBRIC, ("names the risky migration",))
    assert combined[:-1] == shared
    assert combined[-1] == Criterion(len(shared) + 1, "names the risky migration")


def test_missing_rubric_is_an_expectations_error(tmp_path):
    with pytest.raises(ExpectationsError, match="rubric"):
        plan_approval.load_rubric(tmp_path / "nope.md")


def test_from_mapping_parses_plan_approval_and_requires_the_gate():
    exp = from_mapping(_base(plan_approval=["  lists the\n migration "]), "t", CRITERIA)
    assert exp.plan_approval == ("lists the migration",)
    with pytest.raises(ExpectationsError, match="plan_gate"):
        from_mapping(_base(plan_gate="not_applicable", plan_approval=["x"]), "t", CRITERIA)


def test_simulated_approver_approves_only_when_every_criterion_passes(monkeypatch):
    seen = {}
    _approver(monkeypatch, _answer("PASS", "PASS"), seen)
    decision = plan_approval.decide("REQ", CRITERIA, "PLAN <b>")
    assert decision.approved and decision.approver == plan_approval.SIMULATED
    assert "<requirement>\nREQ\n</requirement>" in seen["prompt"]
    assert "<plan>\nPLAN <b>\n</plan>" in seen["prompt"]
    assert "untrusted" in seen["prompt"]
    assert "Nothing has been built yet" not in seen["prompt"]


def test_oversized_plan_is_rejected_without_truncating_the_judged_evidence(monkeypatch):
    monkeypatch.setattr(plan_approval, "azure_openai_model",
                        lambda: pytest.fail("judge ran with incomplete evidence"))
    decision = plan_approval.decide("requirement", CRITERIA,
                                    "x" * (judges.MAX_EVIDENCE_CHARS + 1))
    assert decision.approved is False
    assert all(row.status == "UNVERIFIED" for row in decision.judgement.criteria)


@pytest.mark.parametrize("plan", [None, "", " \n"])
def test_missing_plan_is_rejected_without_a_model_call(tmp_path, monkeypatch, plan):
    monkeypatch.setattr(plan_approval, "azure_openai_model",
                        lambda: pytest.fail("judge ran without a plan"))
    decision = plan_approval.decide("requirement", CRITERIA, plan)
    assert decision.approved is False
    assert [row.status for row in decision.judgement.criteria] == ["UNVERIFIED", "UNVERIFIED"]
    assert decision.judgement.claimed_verdict is None
    plan_approval.write(tmp_path, decision)
    assert plan_approval.read(tmp_path, CRITERIA)["approved"] is False


def test_simulated_approver_requires_criteria():
    with pytest.raises(judges.JudgeError, match="at least one criterion"):
        plan_approval.decide("requirement", (), "plan")


@pytest.mark.parametrize("statuses", [("PASS", "FAIL"), ("PASS", "UNVERIFIED")])
def test_simulated_approver_rejects_a_failed_or_unverified_criterion(monkeypatch, statuses):
    _approver(monkeypatch, _answer(*statuses))
    assert plan_approval.decide("r", CRITERIA, "plan").approved is False


def test_simulated_approver_contract_break_is_a_judge_error_not_a_rejection(monkeypatch):
    _approver(monkeypatch, "looks good to me, approved")
    with pytest.raises(judges.JudgeError, match="contract"):
        plan_approval.decide("r", CRITERIA, "plan")


def test_simulated_approver_hides_sdk_error_text(monkeypatch):
    class Exploding:
        def generate(self, prompt):
            raise RuntimeError("https://secret.example token=abc")

    monkeypatch.setattr(plan_approval, "azure_openai_model", Exploding)
    with pytest.raises(judges.JudgeError) as info:
        plan_approval.decide("r", CRITERIA, "plan")
    assert "secret" not in str(info.value)


@pytest.mark.parametrize("content", [
    "not json", json.dumps([]), json.dumps({"approver": "human", "approved": True}),
    json.dumps({"approver": plan_approval.SIMULATED, "approved": "yes"}),
    json.dumps({"approver": plan_approval.SIMULATED, "approved": True}),
])
def test_read_ignores_records_that_are_not_a_simulated_decision(tmp_path, content):
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(content, encoding="utf-8")
    assert plan_approval.read(tmp_path) is None


@pytest.mark.parametrize(("statuses", "approved", "valid"), [
    (("PASS", "PASS"), True, True),
    (("PASS", "FAIL"), False, True),
    (("PASS", "UNVERIFIED"), False, True),
    (("PASS", "FAIL"), True, False),
    (("PASS", "PASS"), False, False),
    (("PASS",), True, False),
])
def test_read_requires_a_complete_and_consistent_judgement(tmp_path, statuses, approved, valid):
    record = _plan_decision(*statuses).to_dict()
    record["approved"] = approved
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(json.dumps(record), encoding="utf-8")
    assert (plan_approval.read(tmp_path, CRITERIA) is not None) is valid


def test_read_rejects_duplicate_criterion_ids(tmp_path):
    record = _plan_decision("PASS", "PASS").to_dict()
    record["judgement"]["criteria"][1]["id"] = 1
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(json.dumps(record), encoding="utf-8")
    assert plan_approval.read(tmp_path, CRITERIA) is None


def _awaiting(tmp_path, *, verified=False) -> runner.Paths:
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-02-python-di-refactor",
                               "status": "awaiting_approval", "session_id": "session",
                               "plan_message": "the plan", "phases": {}})
    if verified:
        paths.log(1).write_text("\n".join(json.dumps(event) for event in _plan_events()),
                                encoding="utf-8")
        paths.phase1_changes.write_text(json.dumps({"schema": 1, "paths": []}), encoding="utf-8")
    return paths


def _bound_plan_decision(paths, *statuses):
    exp = load(TASKS / "task-02-python-di-refactor")
    criteria = plan_approval.load_rubric(RUBRIC, exp.plan_approval)
    request = runner._require_verified_gate(paths, exp, "session")
    requirement = (TASKS / "task-02-python-di-refactor" / "prompt.md").read_text(
        encoding="utf-8")
    binding = plan_approval.request_binding(request, requirement, criteria)
    plan_approval.write(paths.run, _plan_decision(*statuses), binding=binding)


def _phase2_log(*, request_id="request", call_id="call", answer="Approve and run autonomously",
                success=True, external=True, completion=True, extra=()):
    events = []
    if external:
        events.append({"type": "external_tool.completed", "data": {"requestId": request_id}})
    if completion:
        events.append({"type": "tool.execution_complete", "data": {
            "toolCallId": call_id, "success": success, "result": {"content": answer}}})
    events.extend(extra)
    return "\n".join(json.dumps(event) for event in events) + "\n" + FIXTURE.read_text(
        encoding="utf-8")


def test_phase_approve_refuses_a_stale_awaiting_state_without_gate_evidence(
        tmp_path, monkeypatch, capsys):
    _awaiting(tmp_path)
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert "needs a readable phase1.jsonl" in capsys.readouterr().out


@pytest.mark.parametrize("snapshot", [
    None, "not json", '{"schema": 1, "paths": "not a list"}',
    '{"schema": true, "paths": []}', '{"schema": 1, "paths": [""]}',
    '{"schema": 1, "paths": ["same", "same"]}',
    '{"schema": 1, "schema": 1, "paths": []}',
    '{"schema": 1, "paths": [], "extra": true}',
])
def test_phase_approve_refuses_missing_or_invalid_workspace_evidence(
        tmp_path, monkeypatch, capsys, snapshot):
    paths = _awaiting(tmp_path, verified=True)
    if snapshot is None:
        paths.phase1_changes.unlink()
    else:
        paths.phase1_changes.write_text(snapshot, encoding="utf-8")
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert "workspace" in capsys.readouterr().out


def test_phase_approve_refuses_persistent_preapproval_changes(tmp_path, monkeypatch, capsys):
    paths = _awaiting(tmp_path, verified=True)
    paths.phase1_changes.write_text(
        json.dumps({"schema": 1, "paths": ["src/service.py"]}), encoding="utf-8")
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert "src/service.py" in capsys.readouterr().out


@pytest.mark.parametrize("with_implementation", [False, True])
def test_phase_approve_refuses_unverified_or_violated_gate(
        tmp_path, monkeypatch, capsys, with_implementation):
    paths = _awaiting(tmp_path)
    tool, arguments = ("task", {"agent_type": "coding"}) if with_implementation else ("view", {})
    paths.log(1).write_text("\n".join(json.dumps(event) for event in [
        {"type": "assistant.turn_start", "data": {}},
        {"type": "tool.execution_start", "data": {
            "toolName": tool, "toolCallId": "call", "arguments": arguments}},
    ]), encoding="utf-8")
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert "gate not verified" in capsys.readouterr().out


def test_phase2_refuses_a_valid_decision_without_gate_evidence(tmp_path, monkeypatch, capsys):
    _awaiting(tmp_path)
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision(*(["PASS"] * count)))
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    assert "needs a readable phase1.jsonl" in capsys.readouterr().out


def test_phase2_refuses_an_approval_if_workspace_evidence_was_removed(
        tmp_path, monkeypatch, capsys):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    paths.phase1_changes.unlink()
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    assert "workspace" in capsys.readouterr().out


@pytest.mark.parametrize("status", ["PASS", "FAIL"])
def test_phase_approve_records_the_decision_and_runs_no_agent(
        tmp_path, monkeypatch, status):
    n = len(plan_approval.load_rubric(RUBRIC))
    seen = {}
    _approver(monkeypatch, _answer(*([status] * n)), seen)
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path, verified=True)
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 0
    state = runner.read_state(paths)
    approved = status == "PASS"
    assert state["status"] == ("awaiting_approval" if approved else "plan_rejected")
    assert state["plan_approval"]["approved"] is approved
    assert plan_approval.read(tmp_path)["approved"] is approved
    assert "The proposed plan." in seen["prompt"]
    assert "Approve the plan to start the autonomous run?" in seen["prompt"]
    assert "Approve and run autonomously" in seen["prompt"]
    assert len(plan_approval.read(tmp_path)["request_sha256"]) == 64


@pytest.mark.parametrize("old_option", [("--approver", "human"), ("--approve",)])
def test_human_approval_options_are_not_available(tmp_path, old_option, capsys):
    with pytest.raises(SystemExit) as exc:
        runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve", *old_option])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_phase_approve_judge_failure_is_a_setup_error(tmp_path, monkeypatch):
    _approver(monkeypatch, "garbage")
    paths = _awaiting(tmp_path, verified=True)
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert runner.read_state(paths)["status"] == "awaiting_approval"
    assert plan_approval.read(tmp_path) is None


def test_phase2_stops_on_a_recorded_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, "FAIL", *(["PASS"] * (count - 1)))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 0
    assert runner.read_state(paths)["status"] == "plan_rejected"


def test_phase2_refuses_an_approval_missing_a_rubric_criterion(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path)
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision(*(["PASS"] * (count - 1))))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    assert runner.read_state(paths)["status"] == "awaiting_approval"


def test_phase2_uses_an_approved_record_without_calling_the_judge(tmp_path, monkeypatch):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    calls = []

    def run_phase(cmd, paths, phase, timeout):
        calls.append((phase, cmd))
        paths.log(phase).write_text(_phase2_log(), encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 0
    state = runner.read_state(paths)
    assert state["status"] == "complete" and state["approved_by"] == plan_approval.SIMULATED
    assert len(calls) == 1 and calls[0][0] == 2
    assert calls[0][1][calls[0][1].index("--request-id") + 1] == "request"
    assert calls[0][1][calls[0][1].index("--tool-call-id") + 1] == "call"


@pytest.mark.parametrize("change", ["message", "question", "request", "call", "session"])
def test_phase2_refuses_an_approval_bound_to_different_evidence(
        tmp_path, monkeypatch, capsys, change):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    events = _plan_events()
    if change == "message":
        events[1]["data"]["content"] = "A revised plan."
    elif change == "question":
        events[2]["data"]["arguments"]["question"] = "Approve the revised plan?"
        events[3]["data"]["arguments"]["question"] = "Approve the revised plan?"
    elif change == "request":
        events[3]["data"]["requestId"] = "another-request"
    elif change == "call":
        events[2]["data"]["toolCallId"] = "another-call"
        events[3]["data"]["toolCallId"] = "another-call"
    elif change == "session":
        events[3]["data"]["sessionId"] = "another-session"
        state = runner.read_state(paths)
        state["session_id"] = "another-session"
        runner.write_state(paths, state)
    paths.log(1).write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))

    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    assert "does not match the pending request" in capsys.readouterr().out


@pytest.mark.parametrize("completion", [
    {"request_id": "another-request"},
    {"call_id": "another-call"},
    {"answer": "Cancel"},
    {"success": False},
    {"external": False},
    {"completion": False},
])
def test_phase2_requires_the_original_approval_call_to_complete(
        tmp_path, monkeypatch, completion):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))

    def run_phase(cmd, paths, phase, timeout):
        paths.log(phase).write_text(_phase2_log(**completion), encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    state = runner.read_state(paths)
    assert state["status"] == "setup_error"
    assert "did not complete with the approved choice" in state["phases"]["2"]["schema_errors"][0]


def test_phase2_blocks_a_later_unapproved_question(tmp_path, monkeypatch):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    followup = {"type": "external_tool.requested", "data": {
        "requestId": "followup", "sessionId": "session", "toolCallId": "another-call",
        "toolName": "ask_user", "arguments": {"question": "Approve a design change?"}}}

    def run_phase(cmd, paths, phase, timeout):
        paths.log(phase).write_text(_phase2_log(extra=(followup,)), encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 0
    assert runner.read_state(paths)["status"] == "blocked_approval"


@pytest.mark.parametrize(("status", "expected_status", "approved_by", "expected_calls"), [
    ("PASS", "complete", plan_approval.SIMULATED, [2]),
    ("FAIL", "plan_rejected", None, []),
    ("UNVERIFIED", "plan_rejected", None, []),
])
def test_all_phases_automatically_use_the_simulated_approver(
        tmp_path, monkeypatch, status, expected_status, approved_by, expected_calls):
    count = len(plan_approval.load_rubric(RUBRIC))
    _approver(monkeypatch, _answer(*([status] * count)))

    def phase1(args, task_dir, paths):
        return runner.read_state(_awaiting(paths.run, verified=True))

    calls = []

    def run_phase(cmd, paths, phase, timeout):
        calls.append(phase)
        paths.log(phase).write_text(_phase2_log(), encoding="utf-8")
        return 0

    monkeypatch.setattr(runner, "phase1", phase1)
    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--unsandboxed"]) == 0
    state = runner.read_state(runner.Paths(tmp_path))
    assert state["status"] == expected_status
    assert state.get("approved_by") == approved_by
    assert calls == expected_calls


@pytest.mark.parametrize("args,expected", [
    (("setup_error", True, True, "RESOLVED"), "setup_error"),
    (("plan_rejected", True, True, "RESOLVED"), "failed"),
    (("blocked_approval", True, True, "RESOLVED"), "unverified"),
    (("complete", False, True, "RESOLVED"), "failed"),
    (("complete", True, False, "RESOLVED"), "failed"),
    (("complete", True, True, "FAILED"), "failed"),
    (("complete", True, True, "PARTIAL"), "partial"),
    (("complete", None, True, "RESOLVED"), "resolved"),
    (("complete", True, None, "RESOLVED"), "unverified"),
])
def test_outcome(args, expected):
    assert scorer.outcome(*args) == expected


def test_complete_required_gate_without_evidence_is_unverified():
    assert scorer.outcome("complete", None, True, "RESOLVED", gate_required=True) == "unverified"


def test_aggregate_takes_the_worst_status():
    assert scorer.aggregate([{"status": "resolved"}, {"status": "partial"}]) == "partial"
    assert scorer.aggregate([{"status": "failed"}, {"status": "setup_error"}]) == "setup_error"
    assert scorer.aggregate([]) == "setup_error"


@needs_git
def test_score_recorded_run_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    run = tmp_path / "run"
    paths = runner.Paths(run)
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    shutil.copyfile(FIXTURE, paths.log(1))
    runner.write_state(paths, {"task": "task-02-python-di-refactor", "status": "gate_skipped",
                               "baseline": baseline, "session_id": "s", "phases": {}})
    (paths.workspace / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    runner.capture_diff(paths, baseline)
    exp = load(TASKS / "task-02-python-di-refactor")
    recorded = [{"index": i, "criterion": c.criterion, "command": checks.display(c.run),
                 "cwd": c.cwd, "status": "passed" if c.criterion == 3 else "failed",
                 "reason": "r", "output_tail": "tail"} for i, c in enumerate(exp.checks)]
    (run / checks.CHECKS_FILE).write_text(json.dumps({"schema": 1, "results": recorded}),
                                          encoding="utf-8")
    output = tmp_path / "summary.json"

    code = scorer.main([str(run), "--judge", "none", "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    (row,) = report["results"]
    assert row["errors"] == []
    assert row["status"] == "failed" and code == scorer.EXIT["failed"]
    assert row["plan_gate"]["passed"] is False
    assert {m["name"] for m in row["trajectory"]} >= {"delegation", "skills:coding"}
    statuses = {r["id"]: r["status"] for r in row["acceptance"]["criteria"]}
    assert statuses == {1: "UNVERIFIED", 2: "UNVERIFIED", 3: "UNVERIFIED", 4: "FAIL",
                        5: "UNVERIFIED"}
    assert row["acceptance"]["verdict"] == "FAILED"
    assert [c["status"] for c in row["checks"]] == ["passed", "failed"]
    assert "output_tail" not in row["checks"][0]
    assert row["usage"] == {"premiumRequests": 1}

    (run / checks.CHECKS_FILE).unlink()
    row = scorer.score_run(run, "none", TASKS)
    assert row["acceptance"]["verdict"] == "UNVERIFIED"
    assert row["checks"] is None and "--phase verify" in row["errors"][0]

    # CI: the approve job's rejection sits beside a state.json still awaiting it.
    runner.write_state(paths, {**runner.read_state(paths), "status": "awaiting_approval"})
    assert scorer.score_run(run, "none", TASKS)["status"] == "failed"
    (run / plan_approval.APPROVAL_FILE).write_text(
        json.dumps({"approver": plan_approval.SIMULATED, "approved": True}), encoding="utf-8")
    row = scorer.score_run(run, "none", TASKS)
    assert row["status"] == "setup_error" and "invalid plan-approval.json" in row["errors"]

    count = len(plan_approval.load_rubric(RUBRIC))
    _awaiting(run, verified=True)
    _bound_plan_decision(paths, "FAIL", *(["PASS"] * (count - 1)))
    real_judge = scorer.judge

    def no_acceptance_model(name, *args, **kwargs):
        assert name == "none"
        return real_judge(name, *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", no_acceptance_model)
    row = scorer.score_run(run, "azure-openai", TASKS)
    assert row["status"] == "failed"
    assert row["plan_approval"]["passed"] is False
    assert row["acceptance"]["judge"] == "none"


def test_scorer_requires_approval_for_a_completed_run_with_a_required_gate(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {
        "task": "task-02-python-di-refactor", "status": "complete",
    })
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "missing plan-approval.json" in row["errors"]


@pytest.mark.parametrize("status", ["blocked_approval", "awaiting_approval"])
def test_unfinished_approval_never_calls_the_acceptance_model(tmp_path, monkeypatch, status):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-02-python-di-refactor", "status": status})
    paths.log(1).write_text("\n".join(json.dumps(event) for event in [
        {"type": "assistant.turn_start", "data": {}},
        {"type": "tool.execution_start", "data": {
            "toolName": "view", "toolCallId": "call", "arguments": {}}},
    ]), encoding="utf-8")
    paths.diff.write_text("", encoding="utf-8")
    real_judge = scorer.judge

    def no_acceptance_model(name, *args, **kwargs):
        assert name == "none"
        return real_judge(name, *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", no_acceptance_model)
    row = scorer.score_run(tmp_path, "azure-openai", TASKS)
    assert row["status"] == "unverified"
    assert row["plan_gate"]["passed"] is None
    assert row["acceptance"]["judge"] == "none"


def test_scorer_rejects_a_completed_run_with_a_rejected_plan(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {
        "task": "task-02-python-di-refactor", "status": "complete",
    })
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision("FAIL", *(["PASS"] * (count - 1))))
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "recorded plan decision conflicts with the run state" in row["errors"]


def test_scorer_accepts_a_completed_run_with_a_valid_simulated_approval(tmp_path):
    pytest.importorskip("deepeval")
    paths = _awaiting(tmp_path, verified=True)
    runner.write_state(paths, {**runner.read_state(paths), "status": "complete",
                               "approved_by": plan_approval.SIMULATED})
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    paths.log(2).write_text(_phase2_log(), encoding="utf-8")
    paths.diff.write_text("synthetic diff\n", encoding="utf-8")
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "failed"
    assert row["plan_approval"]["passed"] is True
    assert row["plan_gate"]["passed"] is True


def test_scorer_passes_only_the_completed_phase_two_response_to_the_judge(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    paths = _awaiting(tmp_path, verified=True)
    runner.write_state(paths, {**runner.read_state(paths), "status": "complete",
                               "approved_by": plan_approval.SIMULATED})
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    final = {"type": "assistant.message", "data": {"content": "The finished answer."}}
    paths.log(2).write_text(_phase2_log() + "\n" + json.dumps(final), encoding="utf-8")
    paths.diff.write_text("", encoding="utf-8")
    seen = {}
    real_judge = scorer.judge

    def capture(name, *args, **kwargs):
        seen["response"] = kwargs.get("final_response")
        return real_judge("none", *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", capture)
    scorer.score_run(tmp_path, "none", TASKS)
    assert seen["response"] == "The finished answer."


@pytest.mark.parametrize(("status", "required", "pending", "expected"), [
    ("complete", False, False, "The finished answer."),
    ("gate_skipped", True, False, "The finished answer."),
    ("gate_skipped", True, True, None),
])
def test_scorer_only_uses_phase_one_as_a_final_response_when_it_finished(
        tmp_path, monkeypatch, status, required, pending, expected):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path)
    task = "task-05-pr-description"
    runner.write_state(paths, {"task": task, "status": status, "session_id": "session"})
    events = _plan_events() if pending else [
        {"type": "assistant.turn_start", "data": {}},
        {"type": "assistant.message", "data": {"content": "The finished answer."}},
        {"type": "tool.execution_start", "data": {
            "toolName": "view", "toolCallId": "view", "arguments": {}}},
    ]
    paths.log(1).write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    paths.phase1_changes.write_text(
        json.dumps({"schema": 1, "paths": ["output.txt"] if required else []}), encoding="utf-8")
    paths.diff.write_text("", encoding="utf-8")
    if not required:
        exp = replace(load(TASKS / task), plan_gate="not_applicable")
        monkeypatch.setattr(scorer, "load", lambda _: exp)
    seen = {}
    real_judge = scorer.judge

    def capture(name, *args, **kwargs):
        seen["response"] = kwargs.get("final_response")
        return real_judge("none", *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", capture)
    scorer.score_run(tmp_path, "none", TASKS)
    assert seen["response"] == expected


def test_scorer_does_not_treat_a_plan_as_a_final_response(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    paths = _awaiting(tmp_path, verified=True)
    paths.diff.write_text("", encoding="utf-8")
    seen = {}
    real_judge = scorer.judge

    def capture(name, *args, **kwargs):
        seen["response"] = kwargs.get("final_response")
        return real_judge("none", *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", capture)
    scorer.score_run(tmp_path, "none", TASKS)
    assert seen["response"] is None


def test_scorer_rejects_an_ungated_run_claimed_complete_with_a_pending_request(
        tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path)
    task = "task-05-pr-description"
    runner.write_state(paths, {"task": task, "status": "complete"})
    paths.log(1).write_text("\n".join(json.dumps(e) for e in _plan_events()), encoding="utf-8")
    exp = replace(load(TASKS / task), plan_gate="not_applicable")
    monkeypatch.setattr(scorer, "load", lambda _: exp)
    monkeypatch.setattr(scorer, "judge", lambda *a, **k: pytest.fail("judge ran"))
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "unapproved user-input request" in row["errors"][0]


def test_scorer_does_not_credit_a_legacy_run_without_workspace_evidence(tmp_path):
    pytest.importorskip("deepeval")
    paths = _awaiting(tmp_path, verified=True)
    paths.phase1_changes.unlink()
    paths.diff.write_text("", encoding="utf-8")
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "unverified"
    assert row["plan_gate"]["passed"] is None
    assert "workspace" in row["plan_gate"]["reason"]


def test_scorer_refuses_a_decision_without_workspace_evidence(tmp_path):
    paths = _awaiting(tmp_path, verified=True)
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    paths.phase1_changes.unlink()
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "no verified matching request" in row["errors"][0]


def test_approval_metric_lists_the_failing_criteria():
    decision = plan_approval.PlanDecision(
        plan_approval.SIMULATED, False, _judgement("PASS", "FAIL", reason="no risks")).to_dict()
    metric = scorer.approval_metric(decision)
    assert metric["name"] == "Plan approval (llm-simulated)"
    assert metric["passed"] is False and metric["score"] == 0.5
    assert metric["reason"] == "rejected: 2. FAIL - no risks"


def test_scoring_an_unreadable_run_is_a_setup_error(tmp_path):
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error" and row["errors"]


@needs_git
def test_capture_diff_includes_untracked_files(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-05-pr-description", paths)
    (paths.workspace / "PR.md").write_text("hello\n", encoding="utf-8")
    runner.capture_diff(paths, baseline)
    assert "+hello" in scorer.produced_diff(paths)


@pytest.mark.parametrize("kind", ["unstaged", "staged", "committed", "staged-restored",
                                  "deleted", "untracked"])
@needs_git
def test_phase1_snapshot_captures_persistent_changes(tmp_path, kind):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-05-pr-description", paths)
    filename = "new \u00fc file.txt" if kind == "untracked" else "diff.patch"
    file = paths.workspace / filename
    original = file.read_bytes() if file.exists() else b""
    if kind == "deleted":
        file.unlink()
    else:
        file.write_bytes(original + b"\nchange\n")
    if kind in ("staged", "committed", "staged-restored"):
        runner._git(paths.workspace, "add", filename)
    if kind == "committed":
        runner._git(paths.workspace, "commit", "-q", "-m", "implement before approval")
    if kind == "staged-restored":
        file.write_bytes(original)

    runner.capture_diff(paths, baseline)
    assert runner.capture_phase1_changes(paths, baseline) == (filename,)
    assert runner.read_phase1_changes(paths) == (filename,)


@needs_git
def test_phase1_snapshot_excludes_generated_output(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-05-pr-description", paths)
    for folder in ("bin", Path("src") / "obj", "node_modules", ".venv",
                   ".pytest_cache", Path("src") / ".mypy_cache", ".ruff_cache"):
        output = paths.workspace / folder / "generated"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("generated", encoding="utf-8")
    for filename in ("__pycache__/module.cpython-311.pyc",
                     "tests/__pycache__/test_module.cpython-311-pytest-9.2.0.pyc"):
        output = paths.workspace / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"generated bytecode")
    runner.capture_diff(paths, baseline)
    assert runner.capture_phase1_changes(paths, baseline) == ()
    assert paths.diff.read_text(encoding="utf-8") == ""


@needs_git
def test_python_cache_exclusion_keeps_source_changes(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-05-pr-description", paths)
    for filename in ("src/service.py", "src/__pycache__/still_source.py",
                     "src/__pycache__/not_bytecode.pycx"):
        output = paths.workspace / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("source change\n", encoding="utf-8")
    bytecode = paths.workspace / "src" / "__pycache__" / "service.cpython-311.pyc"
    bytecode.write_bytes(b"generated bytecode")

    runner.capture_diff(paths, baseline)
    assert runner.capture_phase1_changes(paths, baseline) == (
        "src/__pycache__/not_bytecode.pycx", "src/__pycache__/still_source.py",
        "src/service.py",
    )
    diff = scorer.produced_diff(paths)
    assert "src/service.py" in diff
    assert "src/__pycache__/still_source.py" in diff
    assert "src/__pycache__/not_bytecode.pycx" in diff
    assert "src/__pycache__/service.cpython-311.pyc" not in diff


def test_capture_diff_fails_when_untracked_files_cannot_be_recorded(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path)
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1))
    with pytest.raises(runner.SetupError, match="untracked files"):
        runner.capture_diff(paths, "baseline")


@needs_git
def test_phase1_snapshot_failure_stops_the_run_before_approval(tmp_path, monkeypatch):
    paths = runner.Paths(tmp_path / "run")
    monkeypatch.setattr(runner.uuid, "uuid4", lambda: "session")

    def run_phase(cmd, paths, phase, timeout):
        paths.log(phase).write_text("\n".join(json.dumps(e) for e in _plan_events()),
                                    encoding="utf-8")
        return 0

    def failed_capture(paths, baseline):
        raise runner.SetupError("cannot capture pre-approval workspace changes")

    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "capture_phase1_changes", failed_capture)
    args = runner.argparse.Namespace(copilot="copilot", max_ai_credits=30, timeout=30,
                                     dry_run=False)
    state = runner.phase1(args, TASKS / "task-05-pr-description", paths)
    assert state["status"] == "setup_error"
    assert "cannot capture pre-approval workspace changes" in state["errors"]


@needs_git
def test_scorer_without_a_captured_diff_is_a_setup_error(tmp_path):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    _awaiting(paths.run, verified=True)
    runner.write_state(paths, {**runner.read_state(paths), "status": "complete",
                               "baseline": baseline})
    count = len(plan_approval.load_rubric(RUBRIC))
    _bound_plan_decision(paths, *(["PASS"] * count))
    paths.log(2).write_text(_phase2_log(), encoding="utf-8")
    row = scorer.score_run(paths.run, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "produced.diff" in row["errors"][0]
