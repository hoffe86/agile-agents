"""Per-task expectations: what a correct trajectory looks like, and the criteria verbatim.

`expectations.yaml` sits beside each task's `acceptance.md`. It declares the trajectory
(which agents dev-lead should delegate to, which skills each agent should invoke, which
it must not) and whether the mandatory plan-approval gate applies. Criteria are never
restated there: they are parsed verbatim from `acceptance.md`, because a restated
criterion is a fork and forks drift.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
PLAN_GATE_VALUES = ("required", "not_applicable")
# Pseudo-agent for a skill the deliverable needs regardless of which agent produces it
# (e.g. architecture-decision-records: architect advises but never writes ADR files).
ANY_AGENT = "any"

_CRITERION = re.compile(r"^(\d+)\.\s+(.*\S)\s*$")


class ExpectationsError(ValueError):
    """The task definition is malformed; a harness defect, never an agent failure."""


@dataclass(frozen=True)
class Criterion:
    id: int
    text: str


@dataclass(frozen=True)
class Expectations:
    task: str
    root_agent: str
    plan_gate: str
    agents: tuple[str, ...]
    skills: dict[str, tuple[str, ...]]
    forbidden_skills: dict[str, tuple[str, ...]] = field(default_factory=dict)
    implementation_agents: tuple[str, ...] | None = None
    criteria: tuple[Criterion, ...] = ()
    unverifiable: dict[int, str] = field(default_factory=dict)


def parse_acceptance(text: str) -> tuple[Criterion, ...]:
    """Numbered top-level items, with indented continuation lines folded in."""
    criteria: list[Criterion] = []
    current: list[str] | None = None
    number = 0
    for line in text.splitlines():
        match = _CRITERION.match(line)
        if match:
            if current is not None:
                criteria.append(Criterion(number, " ".join(current)))
            number = int(match.group(1))
            current = [match.group(2)]
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            current.append(line.strip())
        elif current is not None and not line.strip():
            criteria.append(Criterion(number, " ".join(current)))
            current = None
    if current is not None:
        criteria.append(Criterion(number, " ".join(current)))
    ids = [c.id for c in criteria]
    if not ids or ids != list(range(1, len(ids) + 1)):
        raise ExpectationsError(f"acceptance criteria must be numbered 1..N, found {ids}")
    return tuple(criteria)


def _names(value: object, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ExpectationsError(f"{where} must be a list of nonempty strings")
    if len(set(value)) != len(value):
        raise ExpectationsError(f"{where} contains duplicates")
    return tuple(value)


def _by_agent(value: object, where: str) -> dict[str, tuple[str, ...]]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExpectationsError(f"{where} must map agent names to skill lists")
    return {str(agent): _names(skills, f"{where}.{agent}") for agent, skills in value.items()}


def from_mapping(data: object, task: str, criteria: tuple[Criterion, ...]) -> Expectations:
    if not isinstance(data, dict):
        raise ExpectationsError("expectations must be a mapping")
    known = {"schema", "root_agent", "plan_gate", "agents", "skills", "forbidden_skills",
             "implementation_agents", "unverifiable"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise ExpectationsError(f"unknown keys: {unknown}")
    if data.get("schema") != SCHEMA_VERSION:
        raise ExpectationsError(f"schema must be {SCHEMA_VERSION}")
    root = data.get("root_agent")
    if not isinstance(root, str) or not root.strip():
        raise ExpectationsError("root_agent is required")
    gate = data.get("plan_gate")
    if gate not in PLAN_GATE_VALUES:
        raise ExpectationsError(f"plan_gate must be one of {PLAN_GATE_VALUES}")
    skills = _by_agent(data.get("skills"), "skills")
    if not any(skills.values()):
        raise ExpectationsError("at least one expected skill is required")
    forbidden = _by_agent(data.get("forbidden_skills"), "forbidden_skills")
    for agent, names in forbidden.items():
        clash = set(names) & set(skills.get(agent, ()))
        if clash:
            raise ExpectationsError(f"{agent} both expects and forbids {sorted(clash)}")
    agents = _names(data.get("agents"), "agents")
    stray = sorted(set(skills) - set(agents) - {root, ANY_AGENT})
    if stray:
        raise ExpectationsError(f"skills declared for agents never delegated to: {stray}")
    impl = data.get("implementation_agents")
    unverifiable_raw = data.get("unverifiable") or {}
    if not isinstance(unverifiable_raw, dict):
        raise ExpectationsError("unverifiable must map criterion ids to reasons")
    ids = {c.id for c in criteria}
    unverifiable: dict[int, str] = {}
    for key, reason in unverifiable_raw.items():
        if not isinstance(key, int) or key not in ids:
            raise ExpectationsError(f"unverifiable names unknown criterion {key!r}")
        if not isinstance(reason, str) or not reason.strip():
            raise ExpectationsError(f"unverifiable criterion {key} needs a reason")
        unverifiable[key] = reason.strip()
    return Expectations(
        task=task, root_agent=root, plan_gate=gate, agents=agents, skills=skills,
        forbidden_skills=forbidden,
        implementation_agents=None if impl is None else _names(impl, "implementation_agents"),
        criteria=criteria, unverifiable=unverifiable,
    )


def load(task_dir: str | Path) -> Expectations:
    task_dir = Path(task_dir)
    import yaml

    try:
        data = yaml.safe_load((task_dir / "expectations.yaml").read_text(encoding="utf-8"))
        criteria = parse_acceptance((task_dir / "acceptance.md").read_text(encoding="utf-8"))
    except OSError as exc:
        raise ExpectationsError(f"cannot read task definition: {exc.filename}") from None
    except yaml.YAMLError:
        raise ExpectationsError("expectations.yaml is not valid YAML") from None
    return from_mapping(data, task_dir.name, criteria)
