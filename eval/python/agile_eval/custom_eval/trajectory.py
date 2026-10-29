"""Pure trajectory facts derived from a parsed trace: who delegated, who invoked what.

No DeepEval import here -- the runner needs the plan-gate check between phases, and
the metrics need the same facts, so both read them from one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from agile_eval.adapters.copilot_trace import Trace

# Agents whose delegation means implementation has started. dev-lead's contract puts
# the mandatory Stage 4 plan-approval gate before any of them is dispatched.
IMPLEMENTATION_AGENTS = frozenset({"coding", "infrastructure", "data-scientist"})

# Tools that write to the workspace. The top-level agent using one before approval is
# implementation work done without the gate, even when nothing was delegated.
WRITE_TOOLS = frozenset({"edit", "create", "apply_patch", "write"})


def short_agent(name: str | None, root: str) -> str:
    """`agile-agents-core:coding` -> `coding`; the top level (None) -> `root`."""
    if name is None:
        return root
    return name.rsplit(":", 1)[-1]


@dataclass(frozen=True)
class GateCheck:
    honoured: bool
    violations: tuple[str, ...]


def check_plan_gate(
    phase1: Trace, implementation_agents: frozenset[str] = IMPLEMENTATION_AGENTS
) -> GateCheck:
    """Did phase 1 stop before implementation began?

    Phase 1 runs the unchanged task prompt non-interactively. A dev-lead that honours
    its contract ends that phase presenting the plan for approval; one that delegates to
    an implementation agent, or writes files itself, skipped the gate. Writes made via a
    shell command are not detectable from the trace.
    """
    violations: list[str] = []
    for _, delegated in phase1.delegations:
        agent = short_agent(delegated, "?")
        if agent in implementation_agents:
            violations.append(f"delegated to {agent} before plan approval")
    for tool in phase1.tools_for(None):
        if tool.name in WRITE_TOOLS:
            violations.append(f"top-level agent used {tool.name} before plan approval")
    return GateCheck(honoured=not violations, violations=tuple(dict.fromkeys(violations)))


def skills_by_short_agent(trace: Trace, root: str) -> dict[str, list[str]]:
    result: dict[str, dict[str, None]] = {}
    for agent, skills in trace.skills_by_agent().items():
        bucket = result.setdefault(short_agent(agent, root), {})
        for skill in skills:
            bucket.setdefault(skill, None)
    return {agent: list(skills) for agent, skills in result.items()}


def delegated_agents(trace: Trace, root: str) -> list[str]:
    return list(dict.fromkeys(short_agent(d, root) for _, d in trace.delegations))
