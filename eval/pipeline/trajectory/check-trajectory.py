#!/usr/bin/env python3
"""Validate event-log schema and ordered RPI trajectory without model calls."""

import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path


SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "agile-agents-core"
    / "skills"
    / "run-event-log"
    / "references"
    / "event-schema.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
V2_CUTOFF_UTC = datetime(2026, 10, 5, 21, 12, 21)
IMPLEMENTATION_ROLES = {"implement", "coding", "infrastructure", "data-scientist"}
RESEARCH_ROLES = {"research", "architect"}
REVIEW_ROLES = {"review", "review-lead"}
SENSITIVE_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|"
        r"refresh[_-]?token|client[_-]?secret|authorization|accountkey|"
        r"sharedaccesssignature|connection[_-]?string)\b\s*[:=]\s*\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\bbearer\s+[A-Z0-9._~+/=-]{8,}", re.IGNORECASE),
    re.compile(
        r"\b(?:gh[pousr]_[A-Z0-9]{20,}|github_pat_[A-Z0-9_]{20,}|"
        r"sk-[A-Z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[A-Z0-9_-]{30,}|"
        r"xox[baprs]-[A-Z0-9-]{10,})\b",
        re.IGNORECASE,
    ),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:sig|signature)\s*=\s*[^&;\s]+", re.IGNORECASE),
    re.compile(r"\b(?:https?|ftp)://[^/\s:@]+:[^/@\s]+@", re.IGNORECASE),
    re.compile(r"(?<!\w)\+?\d[\d .()-]{8,}\d(?!\w)"),
)


def _resolve_ref(reference):
    if not reference.startswith("#/"):
        raise ValueError("only local schema references are supported: " + reference)
    value = SCHEMA
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


def _json_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    return "unknown"


def _finite_number(value):
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _matches_type(value, expected):
    actual = _json_type(value)
    if expected == "number":
        return actual in ("integer", "number") and _finite_number(value)
    if expected == "integer":
        return actual == "integer"
    return actual == expected


def _validate_schema(value, schema, path="$"):
    errors = []
    if "$ref" in schema:
        return _validate_schema(value, _resolve_ref(schema["$ref"]), path)

    expected = schema.get("type")
    if expected is not None:
        expected_types = expected if isinstance(expected, list) else [expected]
        if not any(_matches_type(value, item) for item in expected_types):
            return [f"{path}: expected {' or '.join(expected_types)}, got {_json_type(value)}"]

    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the allowed set")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than minLength")
        if len(value) > schema.get("maxLength", math.inf):
            errors.append(f"{path}: longer than maxLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: does not match the required pattern")
        if schema.get("format") == "date-time":
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                errors.append(f"{path}: is not a valid UTC date-time")

    if _json_type(value) in ("integer", "number"):
        if not _finite_number(value):
            errors.append(f"{path}: number must be finite")
        if value < schema.get("minimum", -math.inf):
            errors.append(f"{path}: below minimum")

    if isinstance(value, dict):
        missing = [field for field in schema.get("required", ()) if field not in value]
        if missing:
            errors.append(f"{path}: missing required properties {missing}")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(_validate_schema(item, properties[key], f"{path}.{key}"))
            elif isinstance(schema.get("additionalProperties"), dict):
                errors.extend(_validate_schema(
                    item, schema["additionalProperties"], f"{path}.<value>"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected property")

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            errors.extend(_validate_schema(item, schema["items"], f"{path}[{index}]"))

    for sub_schema in schema.get("allOf", ()):
        errors.extend(_validate_schema(value, sub_schema, path))
    if "if" in schema and not _validate_schema(value, schema["if"], path):
        errors.extend(_validate_schema(value, schema.get("then", {}), path))
    if "oneOf" in schema:
        matches = sum(not _validate_schema(value, option, path)
                      for option in schema["oneOf"])
        if matches != 1:
            errors.append(f"{path}: must match exactly one allowed shape")
    if "not" in schema and not _validate_schema(value, schema["not"], path):
        errors.append(f"{path}: forbidden shape")
    return errors


def _event_schema_errors(events):
    errors = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"event {index}: expected an object")
            continue
        errors.extend(_validate_schema(event, SCHEMA, f"event[{index}]"))
        errors.extend(_sensitive_string_errors(event, f"event[{index}]"))
        if event.get("schema_version") == 2:
            try:
                stamp = datetime.strptime(event.get("timestamp", ""), "%Y-%m-%dT%H:%M:%S.%fZ")
                if stamp < V2_CUTOFF_UTC:
                    errors.append(f"event[{index}]: v2 schema is not valid before its UTC cutoff")
            except (TypeError, ValueError):
                pass
    return errors


def _sensitive_string_errors(value, path):
    errors = []
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SENSITIVE_PATTERNS[:-1]) or (
            (match := SENSITIVE_PATTERNS[-1].search(value))
            and sum(character.isdigit() for character in match.group()) >= 10
        ):
            errors.append(f"{path}: string resembles a credential or personal identifier")
        return errors
    if isinstance(value, dict):
        for key, item in value.items():
            errors.extend(_sensitive_string_errors(key, f"{path}.<key>"))
            errors.extend(_sensitive_string_errors(item, f"{path}.<value>"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_sensitive_string_errors(item, f"{path}[{index}]"))
    return errors


def _historical_or_unsupported_reason(events):
    unsupported = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        if event.get("schema_version") != 2:
            unsupported.append(f"event {index} is unversioned or not schema v2")
            continue
        timestamp = event.get("timestamp")
        try:
            stamp = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
        except (TypeError, ValueError):
            continue
        if stamp < V2_CUTOFF_UTC:
            unsupported.append(f"event {index} predates the v2 cutoff")
    if not unsupported:
        return None
    detail = "; ".join(unsupported[:5])
    return (
        "UNSUPPORTED historical/unsupported classification — "
        f"{detail}; not current v2 compliance evidence. "
        "Timestamps do not authenticate archive provenance."
    )


def _terminal_event(events):
    if not events or not isinstance(events[-1], dict):
        return {}
    return events[-1]


def _windows(events):
    opened = None
    result = []
    errors = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        kind = event.get("event_type")
        phase = event.get("phase")
        if kind == "phase_start":
            if not isinstance(phase, str):
                errors.append(f"event {index}: phase_start has an invalid phase")
                continue
            if opened is not None:
                errors.append(f"event {index}: a phase starts before the open window closes")
            else:
                opened = (phase, index, event.get("timestamp"))
        elif kind == "phase_complete":
            if not isinstance(phase, str):
                errors.append(f"event {index}: phase_complete has an invalid phase")
                continue
            if opened is None:
                errors.append(f"event {index}: a phase closes without an open window")
            elif phase != opened[0]:
                errors.append(f"event {index}: a phase closes a different phase's window")
                opened = None
            else:
                result.append({
                    "phase": phase,
                    "start_index": opened[1],
                    "complete_index": index,
                    "outcome": event.get("outcome"),
                })
                opened = None
    if opened is not None:
        errors.append("an open phase window never closes")
    return result, errors


def _cost_summary_errors(event):
    payload = event.get("payload") if isinstance(event, dict) else None
    summary = payload.get("cost_summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        return ["run_complete is missing payload.cost_summary"]
    status = summary.get("status")
    if status not in ("measured", "unmetered"):
        return []
    usage = summary.get("usage")
    if not isinstance(usage, dict):
        return ["measured cost summary has no usage object"]
    usd = usage.get("usd")
    basis = usage.get("usd_basis")
    if status == "measured":
        if not isinstance(usd, (int, float)) or isinstance(usd, bool) or not _finite_number(usd):
            return ["measured cost summary requires numeric USD from the usage collector"]
        if not isinstance(basis, str) or not basis.startswith("rate:"):
            return ["measured cost summary requires the collector's USD rate basis"]
    elif usd is not None or basis != "not-metered":
        return ["unmetered cost summary must preserve null USD and usd_basis=not-metered"]
    buckets = [usage.get("totals"), usage.get("unattributed")]
    for name in ("by_phase", "by_agent"):
        values = usage.get(name)
        if isinstance(values, dict):
            buckets.extend(values.values())
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        bucket_usd = bucket.get("usd")
        if status == "measured" and (
            not isinstance(bucket_usd, (int, float))
            or isinstance(bucket_usd, bool)
            or not _finite_number(bucket_usd)
        ):
            return ["measured cost summary contains an unrated collector bucket"]
        if status == "unmetered" and bucket_usd is not None:
            return ["unmetered cost summary contains a numeric collector bucket USD"]
    return []


def _skip_reason(event):
    payload = event.get("payload")
    return payload.get("reason") if isinstance(payload, dict) else None


def _is_test_bar_skip(event):
    payload = event.get("payload")
    return (
        event.get("event_type") == "gate_check"
        and isinstance(payload, dict)
        and payload.get("gate") == "test_bar"
        and event.get("outcome") == "partial"
        and payload.get("applicability") == "not_applicable"
        and isinstance(payload.get("reason"), str)
        and bool(payload["reason"].strip())
    )


def _trajectory_errors(events):
    run = _terminal_event(events)
    windows, _window_errors = _windows(events)
    research = [window for window in windows
                if isinstance(window["phase"], str) and window["phase"] in RESEARCH_ROLES]
    implementation = [window for window in windows
                      if isinstance(window["phase"], str)
                      and window["phase"] in IMPLEMENTATION_ROLES]
    reviews = [window for window in windows
               if isinstance(window["phase"], str) and window["phase"] in REVIEW_ROLES]
    errors = {
        "research-before-implementation": [],
        "implementation-before-verification": [],
        "verification-before-review": [],
        "unresolved-gate-failure": [],
    }
    successful_delivery = run.get("outcome") == "success"

    if successful_delivery and (not research or not implementation):
        errors["research-before-implementation"].append(
            "successful delivery requires completed research and implementation windows")
    if research and implementation and (
        any(item["start_index"] > implementation[0]["start_index"] for item in research)
        or not any(
            item["outcome"] == "success"
            and item["complete_index"] < implementation[0]["start_index"]
            for item in research
        )
    ):
        errors["research-before-implementation"].append(
            "research must complete successfully before implementation starts")

    gate_events = [
        (index, event)
        for index, event in enumerate(events)
        if isinstance(event, dict) and event.get("event_type") == "gate_check"
    ]
    test_gates = [
        (index, event) for index, event in gate_events
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("gate") == "test_bar"
    ]
    review_gates = [
        (index, event) for index, event in gate_events
        if isinstance(event.get("payload"), dict)
        and event["payload"].get("gate") == "review"
    ]

    latest_impl_start = max(
        (item["start_index"] for item in implementation), default=-1)
    latest_impl_complete = max(
        (item["complete_index"] for item in implementation), default=-1)
    final_test_gate = test_gates[-1] if test_gates else None
    test_gate_follows_implementation = bool(
        final_test_gate
        and implementation
        and latest_impl_complete < final_test_gate[0]
        and latest_impl_start < final_test_gate[0]
    )
    if final_test_gate and not test_gate_follows_implementation:
        errors["implementation-before-verification"].append(
            "every test_bar gate must follow a completed implementation window")
    if successful_delivery and not implementation:
        errors["implementation-before-verification"].append(
            "successful delivery requires an implementation window")

    verified = bool(
        test_gate_follows_implementation
        and (
            final_test_gate[1].get("outcome") == "success"
            or _is_test_bar_skip(final_test_gate[1])
        )
    )
    if successful_delivery and not verified:
        errors["implementation-before-verification"].append(
            "successful delivery requires a passing test_bar gate or justified not-applicable skip after implementation")

    review_started_after_verification = bool(
        verified
        and final_test_gate
        and reviews
        and final_test_gate[0] < reviews[-1]["start_index"]
    )
    review_gate_ordered = bool(
        review_started_after_verification
        and review_gates
        and review_gates[-1][0] > reviews[-1]["complete_index"]
    )
    if reviews and not review_started_after_verification:
        errors["verification-before-review"].append(
            "review must start after successful current verification")
    if review_gates and not review_gate_ordered:
        errors["verification-before-review"].append(
            "a review gate must follow a completed review window that started after current verification")
    if successful_delivery and (
        not reviews
        or reviews[-1]["outcome"] != "success"
        or not review_gate_ordered
        or review_gates[-1][1].get("outcome") != "success"
    ):
        errors["verification-before-review"].append(
            "successful delivery requires a successful fresh review gate")

    if successful_delivery and any(
        role_windows[-1]["outcome"] != "success"
        for role in IMPLEMENTATION_ROLES
        if (role_windows := [item for item in implementation if item["phase"] == role])
    ):
        errors["implementation-before-verification"].append(
            "the latest implementation window did not succeed")

    latest_gate_outcomes = {}
    for _index, gate in gate_events:
        payload = gate.get("payload")
        name = payload.get("gate") if isinstance(payload, dict) else None
        if isinstance(name, str) and name:
            latest_gate_outcomes[name] = gate
    if successful_delivery and any(
        gate.get("outcome") == "fail" or (
            gate.get("outcome") == "partial" and not _is_test_bar_skip(gate)
        )
        for gate in latest_gate_outcomes.values()
    ):
        errors["unresolved-gate-failure"].append(
            "one or more latest gate outcomes remain unresolved")
    return errors


def run_checks(events):
    """Return required checks as (check_id, required, ok, detail)."""
    if not isinstance(events, list):
        events = []
    schema_errors = _event_schema_errors(events)
    valid_events = [event for event in events if isinstance(event, dict)]
    timestamps = [
        datetime.strptime(event["timestamp"], "%Y-%m-%dT%H:%M:%S.%fZ")
        for event in valid_events
        if isinstance(event.get("timestamp"), str)
        and re.fullmatch(SCHEMA["properties"]["timestamp"]["pattern"],
                         event["timestamp"])
        and not _validate_schema(event["timestamp"], SCHEMA["properties"]["timestamp"])
    ]
    time_order_ok = len(timestamps) == len(valid_events) and all(
        earlier <= later for earlier, later in zip(timestamps, timestamps[1:]))
    run_ids = [event.get("run_id") for event in valid_events]
    single_run = bool(run_ids) and all(
        isinstance(run_id, str) and run_id == run_ids[0] for run_id in run_ids)
    starts = [i for i, event in enumerate(valid_events)
              if event.get("event_type") == "run_start"]
    completes = [i for i, event in enumerate(valid_events)
                 if event.get("event_type") == "run_complete"]
    bookends_ok = (
        len(valid_events) == len(events)
        and bool(valid_events)
        and starts == [0]
        and completes == [len(valid_events) - 1]
    )
    windows, window_errors = _windows(valid_events)
    cost_errors = (
        _cost_summary_errors(valid_events[-1]) if bookends_ok else
        ["run has no terminal event to validate cost_summary"]
    )
    trajectory = _trajectory_errors(valid_events)

    results = []

    def add(check_id, ok, detail=""):
        results.append((check_id, True, bool(ok), detail if not ok else ""))

    add("schema-valid", not schema_errors, "; ".join(schema_errors[:5]))
    add("chronological-timestamps", time_order_ok,
        "timestamps must be valid and non-decreasing in the event stream")
    add("single-run-id", single_run, "every event must carry the same run_id")
    add("run-bookends", bookends_ok,
        "one dev-lead run_start must be first and one run_complete last")
    add("phase-windows", not window_errors,
        "; ".join(window_errors[:5]))
    add("cost-summary", not cost_errors, "; ".join(cost_errors))
    add("research-before-implementation",
        not trajectory["research-before-implementation"],
        "; ".join(trajectory["research-before-implementation"]))
    add("implementation-before-verification",
        not trajectory["implementation-before-verification"],
        "; ".join(trajectory["implementation-before-verification"]))
    add("verification-before-review",
        not trajectory["verification-before-review"],
        "; ".join(trajectory["verification-before-review"]))
    add("unresolved-gate-failure",
        not trajectory["unresolved-gate-failure"],
        "; ".join(trajectory["unresolved-gate-failure"]))
    return results


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON property")
        value[key] = item
    return value


def _reject_non_json_constant(constant):
    raise ValueError(f"invalid JSON number: {constant}")


def check_file(path):
    events, parse_errors = [], []
    try:
        with open(path, encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(
                        line,
                        object_pairs_hook=_reject_duplicate_keys,
                        parse_constant=_reject_non_json_constant,
                    ))
                except (json.JSONDecodeError, ValueError, RecursionError) as error:
                    parse_errors.append(f"line {line_number}: {error}")
    except (OSError, UnicodeError) as error:
        print(f"trajectory check: {path}\n  FAIL  readable-file  - {error}")
        return 1

    print(f"trajectory check: {path}")
    if parse_errors:
        print("  FAIL  valid-json")
        for error in parse_errors[:5]:
            print(f"        {error}")
        return 1
    if not events:
        print("  FAIL  non-empty: no events in stream")
        return 1

    classification = _historical_or_unsupported_reason(events)
    if classification:
        print(f"  UNSUPPORTED  historical/unsupported — {classification}")

    results = run_checks(events)
    failed = 0
    for check_id, required, ok, detail in results:
        tag = "PASS" if ok else ("FAIL" if required else "warn")
        failed += int(not ok and required)
        line = f"  {tag:4}  {check_id}"
        if detail and not ok:
            line += f"  - {detail}"
        print(line)
    print(f"  -> {len(results) - failed}/{len(results)} checks passed")
    return 0 if failed == 0 else 1


def build_golden():
    events = [
        {
            "schema_version": 2,
            "timestamp": f"2026-10-06T08:00:{second:02d}.000Z",
            "run_id": "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f",
            "agent": "dev-lead",
            "phase": phase,
            "event_type": event_type,
            **extra,
        }
        for second, phase, event_type, extra in [
            (0, "intake", "run_start", {"payload": {
                "requirement_summary": "Add a storage module",
                "profile_loaded": True,
            }}),
            (1, "research", "phase_start", {}),
            (2, "research", "phase_complete", {"outcome": "success"}),
            (3, "plan", "phase_start", {}),
            (4, "plan", "phase_complete", {"outcome": "success"}),
            (5, "coding", "phase_start", {}),
            (6, "coding", "phase_complete", {"outcome": "success"}),
            (7, "coding", "handoff_received", {"payload": {
                "from_agent": "coding", "sentinel": "IMPLEMENTATION COMPLETE",
            }}),
            (8, "test-bar", "gate_check", {
                "outcome": "success", "payload": {"gate": "test_bar"},
            }),
            (9, "review-lead", "phase_start", {}),
            (10, "review-lead", "phase_complete", {"outcome": "success"}),
            (11, "review-lead", "handoff_received", {"payload": {
                "from_agent": "review-lead", "sentinel": "REVIEW COMPLETE",
            }}),
            (12, "review-lead", "gate_check", {
                "outcome": "success", "payload": {"gate": "review"},
            }),
            (13, "wrap-up", "run_complete", {
                "outcome": "success",
                "payload": {"cost_summary": {
                    "status": "disabled", "reason": "synthetic golden fixture",
                }},
            }),
        ]
    ]
    return events


def self_test():
    golden = build_golden()

    def fails(check_id, events):
        return check_id in {
            name for name, required, ok, _detail in run_checks(events)
            if required and not ok
        }

    cases = [
        ("canonical golden passes", not any(fails(name, golden) for name, *_ in run_checks(golden))),
        ("worker-owned event rejected", fails("schema-valid", _mutate(golden, lambda e: e[5].update(agent="coding")))),
        ("missing test-bar rejected", fails("implementation-before-verification", [
            event for event in golden if not (
                event["event_type"] == "gate_check"
                and event.get("payload", {}).get("gate") == "test_bar"
            )
        ])),
        ("failed gate cannot deliver success", fails("unresolved-gate-failure", [
            {**event, "outcome": "fail"} if event["event_type"] == "gate_check" else event
            for event in golden
        ])),
    ]
    ok = True
    for name, passed in cases:
        ok = ok and passed
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
    print("self-test: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def _mutate(events, mutation):
    result = json.loads(json.dumps(events))
    mutation(result)
    return result


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--self-test":
        return self_test()
    if argv[0] == "--emit-fixture":
        if len(argv) != 2:
            print("--emit-fixture needs one output path", file=sys.stderr)
            return 2
        with open(argv[1], "w", encoding="utf-8", newline="\n") as handle:
            for event in build_golden():
                handle.write(json.dumps(event) + "\n")
        print(f"wrote fixture: {argv[1]}")
        return 0
    if len(argv) != 1:
        print("provide one event-log path", file=sys.stderr)
        return 2
    return check_file(argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
