"""Copilot CLI session log -> DeepEval trace.

`copilot -p ... --output-format json` emits newline-delimited JSON events carrying `id` / `parentId` /
`timestamp`, which is already a span tree. This adapter turns that into the shape
DeepEval's agentic metrics consume: the ordered tool calls a run actually made.

DeepEval ships integrations for LangChain, OpenAI, Anthropic, CrewAI and friends, but
none for the Copilot CLI. This module is that missing piece, and it is deliberately the
only place that knows the CLI's log format -- see `SCHEMA_EVENTS` for the coupling this
creates, and `verify_schema()` for the drift check that guards it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# The event types this adapter depends on. The CLI's log format is undocumented, so a
# silent upstream rename would otherwise turn every trajectory metric into a false
# negative -- an empty trace scores identically to an agent that invoked nothing.
SCHEMA_EVENTS: dict[str, str] = {
    "tool.execution_start": "a tool invocation begins; carries toolName + arguments",
    "tool.execution_complete": "a tool invocation ends",
    "assistant.turn_start": "an assistant turn begins",
    "assistant.turn_end": "an assistant turn ends",
    "session.skills_loaded": "the skills offered to the session",
    "user.message": "the prompt given to the agent",
}

# Skills are not a distinct event type -- invoking one is a tool call named `skill`
# whose `arguments.skill` names it. This is what makes skill bypass measurable.
SKILL_TOOL_NAME = "skill"


@dataclass
class ToolInvocation:
    """One tool call the agent made."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str | None = None
    span_id: str | None = None
    parent_id: str | None = None
    timestamp: str | None = None

    @property
    def skill_name(self) -> str | None:
        """The skill this call invoked, when it is a skill invocation."""
        if self.name != SKILL_TOOL_NAME:
            return None
        value = self.arguments.get("skill")
        return value if isinstance(value, str) else None


@dataclass
class Trace:
    """A whole `dev-lead` run, reconstructed from its log."""

    prompt: str | None
    tools: list[ToolInvocation]
    skills_offered: list[str]
    turns: int
    events_parsed: int
    events_unparsable: int
    schema_errors: list[str] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    @property
    def skills_invoked(self) -> list[str]:
        """Skills actually invoked, in order, de-duplicated."""
        seen: dict[str, None] = {}
        for t in self.tools:
            name = t.skill_name
            if name is not None:
                seen.setdefault(name, None)
        return list(seen)


def _event_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate event field")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("nonfinite JSON value")


def _iter_events(lines: Iterable[str]) -> Iterator[tuple[dict[str, Any] | None, str | None]]:
    for number, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue
        if line.startswith(("[DRY RUN]", "[setup_error]")):
            yield None, f"line {number}: staging placeholder is not a recorded session"
            continue
        try:
            parsed = json.loads(line, object_pairs_hook=_event_object, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            # Logs interleave harness output (banners, judge transcripts) with the CLI's
            # JSON. Tolerate banners, but never silently discard a broken JSON event.
            yield None, f"line {number}: malformed JSON event" if line.startswith(
                ("{", "[", "NaN", "Infinity", "-Infinity")
            ) else None
            continue
        if not isinstance(parsed, dict):
            yield None, f"line {number}: event must be a JSON object"
        else:
            yield parsed, None


def parse_log(path: str | Path) -> Trace:
    """Reconstruct a Trace from a Copilot CLI session log."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_log_text(text)


def parse_log_text(text: str) -> Trace:
    tools: list[ToolInvocation] = []
    skills_offered: list[str] = []
    prompt: str | None = None
    turns = 0
    parsed_count = 0
    unparsable = 0
    errors: list[str] = []

    for event, error in _iter_events(text.splitlines()):
        if error:
            errors.append(error)
        if event is None:
            unparsable += 1
            continue
        parsed_count += 1
        etype = event.get("type")
        data = event.get("data")
        if not isinstance(etype, str) or not etype.strip() or not isinstance(data, dict):
            errors.append(f"event {parsed_count}: type must be a nonempty string and data an object")
            continue

        if etype == "tool.execution_start":
            args = data.get("arguments")
            name = data.get("toolName")
            if not isinstance(name, str) or not name.strip() or not isinstance(args, dict):
                errors.append(f"event {parsed_count}: toolName must be a nonempty string and arguments an object")
                continue
            if name == SKILL_TOOL_NAME and (
                not isinstance(args.get("skill"), str) or not args["skill"].strip()
            ):
                errors.append(f"event {parsed_count}: skill invocation requires a nonempty skill identity")
                continue
            tools.append(
                ToolInvocation(
                    name=name,
                    arguments=args,
                    call_id=data.get("toolCallId"),
                    span_id=event.get("id"),
                    parent_id=event.get("parentId"),
                    timestamp=event.get("timestamp"),
                )
            )
        elif etype == "assistant.turn_start":
            turns += 1
        elif etype == "session.skills_loaded":
            skills = data.get("skills")
            if not isinstance(skills, list) or any(
                not isinstance(skill, dict) or not isinstance(skill.get("name"), str)
                or not skill["name"].strip() for skill in skills
            ):
                errors.append(f"event {parsed_count}: skills must be a list of named objects")
                continue
            skills_offered.extend(skill["name"] for skill in skills)
        elif etype.startswith("tool.") and etype not in SCHEMA_EVENTS:
            errors.append(f"event {parsed_count}: unrecognized tool event; check adapter schema")
        elif etype == "user.message" and prompt is None:
            content = data.get("content") or data.get("message")
            if isinstance(content, str):
                prompt = content

    return Trace(
        prompt=prompt,
        tools=tools,
        skills_offered=skills_offered,
        turns=turns,
        events_parsed=parsed_count,
        events_unparsable=unparsable,
        schema_errors=errors,
    )


def verify_schema(trace: Trace) -> list[str]:
    """Report signs that the CLI log format has moved out from under this adapter.

    An adapter coupled to an undocumented format fails silently by default: a renamed
    event yields an empty trace, and an empty trace looks exactly like an agent that did
    nothing. These checks turn that into a visible complaint.
    """
    problems = list(trace.schema_errors)
    if trace.events_parsed == 0:
        problems.append("no JSON events parsed - log is not CLI session output, or the format changed")
        return problems
    if not trace.tools:
        problems.append(
            "no tool.execution_start events - either the run invoked no tools, or that event was renamed"
        )
    if trace.turns == 0:
        problems.append("no assistant.turn_start events - turn boundaries unavailable")
    if not trace.skills_offered:
        problems.append("no session.skills_loaded event - cannot tell which skills were available")
    return problems


def to_deepeval_tools(trace: Trace):
    """Convert to DeepEval `ToolCall`s.

    Imported lazily so the adapter stays usable (and unit-testable) without DeepEval
    installed -- the parsing half is what carries the schema risk and deserves to be
    exercisable on its own.
    """
    from deepeval.test_case import ToolCall

    return [ToolCall(name=t.name, input_parameters=t.arguments or None) for t in trace.tools]
