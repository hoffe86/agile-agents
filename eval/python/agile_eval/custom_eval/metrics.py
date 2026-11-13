"""DeepEval measurement of the recorded trajectory against a task's expectations.

Delegation coverage uses DeepEval's ToolCorrectnessMetric. Forbidden skill
attempts are checked separately so a reviewer performing another role's workflow
cannot pass merely because delegation succeeded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from agile_eval.adapters.copilot_trace import TASK_TOOL_NAME, Trace
from agile_eval.custom_eval.expectations import ANY_AGENT, Expectations
from agile_eval.custom_eval.trajectory import (
    IMPLEMENTATION_AGENTS,
    GateCheck,
    check_plan_gate,
    delegation_outcomes,
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
    results: list[MetricResult] = []
    for agent, names in exp.forbidden_skills.items():
        actual = by_agent.get(agent, [])
        forbidden = [s for s in names if s in actual]
        results.append(MetricResult(
            name=f"skills:{agent}", score=0.0 if forbidden else 1.0,
            passed=not forbidden,
            reason=(f"forbidden skill invoked: {', '.join(forbidden)}" if forbidden
                    else "no forbidden skill attempts recorded"),
            expected=[], actual=actual,
        ))
    return results


def delegation_metric(trace: Trace, exp: Expectations) -> MetricResult:
    outcomes = delegation_outcomes(trace, exp.root_agent)
    actual = list(outcomes)
    if not exp.agents:
        return MetricResult("delegation", 1.0, True, "no delegation expected", [], actual)
    confirmed = [agent for agent, outcome in outcomes.items() if outcome is True]
    score = _coverage(TASK_TOOL_NAME, "agent_type", confirmed, list(exp.agents))
    missing = [a for a in exp.agents if a not in outcomes]
    failed = [a for a in exp.agents if a in outcomes and outcomes[a] is False]
    unknown = [a for a in exp.agents if a in outcomes and outcomes[a] is None]
    passed: bool | None = score == 1.0
    if unknown and not missing and not failed:
        score, passed = None, None
    reasons = []
    if missing:
        reasons.append(f"not delegated to: {', '.join(missing)}")
    if failed:
        reasons.append(f"delegation failed: {', '.join(failed)}")
    if unknown:
        reasons.append(f"delegation outcome unavailable: {', '.join(unknown)}")
    return MetricResult(
        "delegation", score, passed, "; ".join(reasons) or "all expected agents delegated",
        list(exp.agents), actual,
    )


def plan_gate_metric(
    phase1: Trace, exp: Expectations, *, phase1_changes: tuple[str, ...] | None = None,
) -> tuple[MetricResult, GateCheck | None]:
    if exp.plan_gate != "required":
        return MetricResult("plan_gate", None, None, "not applicable to this task", [], []), None
    impl = frozenset(exp.implementation_agents or IMPLEMENTATION_AGENTS)
    gate = check_plan_gate(phase1, impl, phase1_changes=phase1_changes)
    return MetricResult(
        "plan_gate", None if gate.honoured is None else float(gate.honoured), gate.honoured,
        gate.reason, ["verified plan approval request before implementation"],
        list(gate.violations),
    ), gate
