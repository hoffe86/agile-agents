"""Pure trajectory facts derived from a parsed trace: who delegated, who invoked what.

No DeepEval import here -- the runner needs the plan-gate check between phases, and
the metrics need the same facts, so both read them from one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from agile_eval.adapters.copilot_trace import ExternalToolRequest, Trace

# Agents whose delegation means implementation has started. dev-lead's contract puts
# the mandatory Stage 4 plan-approval gate before any of them is dispatched.
IMPLEMENTATION_AGENTS = frozenset({"coding", "infrastructure", "data-scientist"})

# Tools that write to the workspace. The top-level agent using one before approval is
# implementation work done without the gate, even when nothing was delegated.
WRITE_TOOLS = frozenset({"edit", "create", "apply_patch", "write"})
PLAN_APPROVAL_CHOICES = ("Approve and run autonomously", "Adjust plan", "Cancel")


def short_agent(name: str | None, root: str) -> str:
    """`agile-agents-core:coding` -> `coding`; the top level (None) -> `root`."""
    if name is None:
        return root
    return name.rsplit(":", 1)[-1]


@dataclass(frozen=True)
class GateCheck:
    honoured: bool | None
    violations: tuple[str, ...]
    reason: str
    request: ExternalToolRequest | None = None


def check_plan_gate(
    phase1: Trace, implementation_agents: frozenset[str] = IMPLEMENTATION_AGENTS
) -> GateCheck:
    """Verify a pending top-level Stage 4 request and check for prior implementation.

    Writes made via a shell command are not detectable from the trace.
    """
    violations: list[str] = []
    for _, delegated in phase1.delegations:
        agent = short_agent(delegated, "?")
        if agent in implementation_agents:
            violations.append(f"delegated to {agent} before plan approval")
    for tool in phase1.tools_for(None):
        if tool.name in WRITE_TOOLS:
            violations.append(f"top-level agent used {tool.name} before plan approval")
    violations = list(dict.fromkeys(violations))
    if violations:
        return GateCheck(False, tuple(violations), "; ".join(violations))
    if len(phase1.external_requests) != 1:
        return GateCheck(None, (), "plan approval request could not be verified")
    request = phase1.external_requests[0]
    calls = [tool for tool in phase1.tools if tool.call_id == request.call_id]
    question, choices = request.arguments.get("question"), request.arguments.get("choices")
    if (request.name != "ask_user" or request.agent_id
            or request.request_id in phase1.completed_external_requests
            or len(calls) != 1 or calls[0].name != request.name
            or calls[0].agent is not None or calls[0].agent_id or calls[0].parent_call_id
            or calls[0].success is not None or calls[0].arguments != request.arguments
            or not calls[0].span_id or request.parent_id != calls[0].span_id
            or not isinstance(question, str) or not question.strip()
            or "plan" not in question.casefold()
            or not isinstance(choices, list) or tuple(choices) != PLAN_APPROVAL_CHOICES):
        return GateCheck(None, (), "plan approval request could not be verified")
    return GateCheck(True, (), "top-level Stage 4 approval request is pending", request)


def approval_response_recorded(request: ExternalToolRequest, phase2: Trace,
                               combined: Trace) -> bool:
    """The actual pending call must complete with the exact approval choice."""
    calls = [tool for tool in combined.tools if tool.call_id == request.call_id]
    return (
        request.request_id in phase2.completed_external_requests
        and len(calls) == 1
        and calls[0].success is True
        and isinstance(calls[0].result, dict)
        and calls[0].result.get("content") == PLAN_APPROVAL_CHOICES[0]
    )


def skills_by_short_agent(trace: Trace, root: str) -> dict[str, list[str]]:
    result: dict[str, dict[str, None]] = {}
    for agent, skills in trace.skills_by_agent().items():
        bucket = result.setdefault(short_agent(agent, root), {})
        for skill in skills:
            bucket.setdefault(skill, None)
    return {agent: list(skills) for agent, skills in result.items()}


def delegated_agents(trace: Trace, root: str) -> list[str]:
    return list(dict.fromkeys(short_agent(d, root) for _, d in trace.delegations))


def delegation_outcomes(trace: Trace, root: str) -> dict[str, bool | None]:
    """Distinguish a started agent from a failed or incomplete delegation attempt."""
    outcomes: dict[str, bool | None] = {}
    for tool in trace.tools:
        if tool.delegated_agent is None:
            continue
        agent = short_agent(tool.delegated_agent, root)
        outcome = (short_agent(tool.started_agent, root) == agent
                   if tool.started_agent is not None else tool.success)
        if (agent not in outcomes or outcome is True
                or (outcomes[agent] is False and outcome is None)):
            outcomes[agent] = outcome
    return outcomes
