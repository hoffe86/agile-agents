"""DeepEval measurement of the recorded trajectory against a task's expectations.

Skill invocation per agent and delegation coverage are measured with DeepEval's
ToolCorrectnessMetric, projected onto identities only (the same pattern
`report_skill_usage.measure_skills` uses), so they stay deterministic and credential-
free. A forbidden skill zeroes its agent's score: coverage alone cannot express "loaded
the lens the orchestrator must not perform itself".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from agile_eval.adapters.copilot_trace import SKILL_TOOL_NAME, TASK_TOOL_NAME, Trace
from agile_eval.custom_eval.expectations import ANY_AGENT, Expectations
from agile_eval.custom_eval.trajectory import (
    IMPLEMENTATION_AGENTS,
    GateCheck,
    check_plan_gate,
    delegated_agents,
    skills_by_short_agent,
)

DEEPEVAL_VERSION = "4.1.8"


@dataclass
class MetricResult:
    name: str
    score: float | None
    passed: bool | None
    reason: str
    expected: list[str]
    actual: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _coverage(tool: str, key: str, actual: list[str], expected: list[str]) -> float:
    from agile_eval.metrics.local_model import configure_offline, stub_model

    configure_offline()
    from importlib.metadata import version

    if version("deepeval") != DEEPEVAL_VERSION:
        raise RuntimeError(f"custom-eval requires deepeval=={DEEPEVAL_VERSION}")
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

    metric = ToolCorrectnessMetric(
        model=stub_model(), async_mode=False, threshold=1.0,
        evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
    )
    return metric.measure(
        LLMTestCase(
            input="Recorded trajectory coverage",
            actual_output="Recorded trajectory; task quality judged separately",
            tools_called=[ToolCall(name=tool, input_parameters={key: v}) for v in actual],
            expected_tools=[
                ToolCall(name=tool, input_parameters={key: v}) for v in dict.fromkeys(expected)
            ],
        ),
        _show_indicator=False,
    )


def skill_metrics(trace: Trace, exp: Expectations) -> list[MetricResult]:
    by_agent = skills_by_short_agent(trace, exp.root_agent)
    by_agent[ANY_AGENT] = list(dict.fromkeys(s for v in list(by_agent.values()) for s in v))
    delegated = delegated_agents(trace, exp.root_agent)
    results: list[MetricResult] = []
    for agent in dict.fromkeys([*exp.skills, *exp.forbidden_skills]):
        expected = list(exp.skills.get(agent, ()))
        actual = by_agent.get(agent, [])
        forbidden = [s for s in exp.forbidden_skills.get(agent, ()) if s in actual]
        score = _coverage(SKILL_TOOL_NAME, "skill", actual, expected) if expected else 1.0
        reasons = []
        missing = [s for s in expected if s not in actual]
        if missing:
            reasons.append(f"not invoked: {', '.join(missing)}")
        if forbidden:
            score = 0.0
            reasons.append(f"forbidden skill invoked: {', '.join(forbidden)}")
        if agent not in (exp.root_agent, ANY_AGENT) and agent not in delegated:
            reasons.append("agent was never delegated to")
        results.append(MetricResult(
            name=f"skills:{agent}", score=score, passed=score == 1.0,
            reason="; ".join(reasons) or "all expected skills invoked",
            expected=expected, actual=actual,
        ))
    return results


def delegation_metric(trace: Trace, exp: Expectations) -> MetricResult:
    actual = delegated_agents(trace, exp.root_agent)
    if not exp.agents:
        return MetricResult("delegation", 1.0, True, "no delegation expected", [], actual)
    score = _coverage(TASK_TOOL_NAME, "agent_type", actual, list(exp.agents))
    missing = [a for a in exp.agents if a not in actual]
    return MetricResult(
        "delegation", score, score == 1.0,
        f"not delegated to: {', '.join(missing)}" if missing else "all expected agents delegated",
        list(exp.agents), actual,
    )


def plan_gate_metric(phase1: Trace, exp: Expectations) -> tuple[MetricResult, GateCheck | None]:
    if exp.plan_gate != "required":
        return MetricResult("plan_gate", None, None, "not applicable to this task", [], []), None
    impl = frozenset(exp.implementation_agents or IMPLEMENTATION_AGENTS)
    gate = check_plan_gate(phase1, impl)
    return MetricResult(
        "plan_gate", 1.0 if gate.honoured else 0.0, gate.honoured,
        "stopped for plan approval before implementation" if gate.honoured
        else "; ".join(gate.violations),
        ["no implementation before approval"], list(gate.violations),
    ), gate
