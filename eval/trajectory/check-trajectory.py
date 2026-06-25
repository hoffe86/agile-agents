#!/usr/bin/env python3
"""check-trajectory.py - L0 trajectory / process-conformance eval.

Reads a run-event-log JSONL stream (.copilot-runs/<run-id>/events.jsonl) and
asserts it conforms to the expected RPI pipeline shape:

  - dev-lead bookends the run (run_start first, run_complete last with outcome)
  - one run_id across the whole stream; required fields + valid enums per event
  - phase_start / phase_complete are balanced
  - Research -> Implement -> Testing happened
  - a test-bar gate_check (emitted by dev-lead) fired BEFORE review
  - at least one reviewer emitted a gate_check
  - cost telemetry is present on run_complete (the cost-budget machinery ran)

This is the cheapest eval layer: deterministic, zero-credit, schema-grounded.
It catches an entire class of silent failures - the pipeline "ran" but its own
machinery (event log / test-bar gate / cost-budget) never fired - without
calling any model. See eval/trajectory/README.md and docs/adr/0008.

Exit code: 0 if every REQUIRED check passes, 1 otherwise.

Usage:
  check-trajectory.py <events.jsonl>
  check-trajectory.py --self-test            # no file needed; verifies the checks
  check-trajectory.py --emit-fixture <path>  # (re)generate the golden fixture
"""
import json
import sys
from collections import Counter

# Mirror skills/run-event-log/references/event-schema.json (keep in sync).
AGENTS = {
    "dev-lead", "architect", "coding", "testing", "infrastructure",
    "review", "security-review", "architecture-review",
    "infrastructure-review", "test-review",
}
EVENT_TYPES = {
    "run_start", "run_complete", "phase_start", "phase_complete",
    "tool_call", "gate_check", "handoff_received", "error",
}
REQUIRED_FIELDS = ("timestamp", "run_id", "agent", "phase", "event_type")
REVIEWERS = {
    "review", "security-review", "architecture-review",
    "infrastructure-review", "test-review",
}
IMPLEMENTERS = {"coding", "infrastructure"}


def _first_index(events, pred):
    for i, e in enumerate(events):
        if pred(e):
            return i
    return None


def run_checks(events):
    """Return list of (check_id, required, ok, detail)."""
    results = []

    def add(cid, required, ok, detail=""):
        results.append((cid, required, bool(ok), detail))

    # --- Structural ---------------------------------------------------------
    missing = [
        i for i, e in enumerate(events)
        if not all(f in e for f in REQUIRED_FIELDS)
    ]
    add("required-fields", True, not missing,
        "" if not missing else f"events missing required fields at indices {missing[:5]}")

    bad_agent = sorted({e.get("agent") for e in events if e.get("agent") not in AGENTS})
    add("valid-agents", True, not bad_agent,
        "" if not bad_agent else f"unknown agents: {bad_agent}")

    bad_type = sorted({e.get("event_type") for e in events if e.get("event_type") not in EVENT_TYPES})
    add("valid-event-types", True, not bad_type,
        "" if not bad_type else f"unknown event_types: {bad_type}")

    run_ids = {e.get("run_id") for e in events}
    add("single-run-id", True, len(run_ids) == 1,
        "" if len(run_ids) == 1 else f"expected 1 run_id, found {len(run_ids)}")

    starts = bool(events) and events[0].get("event_type") == "run_start" and events[0].get("agent") == "dev-lead"
    add("starts-with-run-start", True, starts,
        "" if starts else "first event must be dev-lead run_start")

    last = events[-1] if events else {}
    ends = last.get("event_type") == "run_complete" and last.get("agent") == "dev-lead" and "outcome" in last
    add("ends-with-run-complete", True, ends,
        "" if ends else "last event must be dev-lead run_complete with an outcome")

    # phase_start / phase_complete balance per (agent, phase)
    opens = Counter((e["agent"], e["phase"]) for e in events
                    if e.get("event_type") == "phase_start" and "agent" in e and "phase" in e)
    closes = Counter((e["agent"], e["phase"]) for e in events
                     if e.get("event_type") == "phase_complete" and "agent" in e and "phase" in e)
    unbalanced = [k for k in (set(opens) | set(closes)) if opens[k] != closes[k]]
    add("phases-balanced", True, not unbalanced,
        "" if not unbalanced else f"unbalanced phase_start/complete for {unbalanced[:5]}")

    # --- RPI trajectory -----------------------------------------------------
    research_i = _first_index(events, lambda e: e.get("agent") == "architect"
                              or "research" in str(e.get("phase", "")).lower())
    add("research-phase", True, research_i is not None,
        "" if research_i is not None else "no research phase (architect / 'research') found")

    implement_i = _first_index(events, lambda e: e.get("agent") in IMPLEMENTERS)
    add("implement-phase", True, implement_i is not None,
        "" if implement_i is not None else "no implement phase (coding / infrastructure) found")

    has_testing = any(e.get("agent") == "testing" for e in events)
    add("testing-phase", True, has_testing,
        "" if has_testing else "no testing agent activity found")

    # test-bar gate = a gate_check emitted by dev-lead, before the first review activity.
    testbar_i = _first_index(events, lambda e: e.get("event_type") == "gate_check"
                             and e.get("agent") == "dev-lead")
    first_review_i = _first_index(events, lambda e: e.get("agent") in REVIEWERS)
    if testbar_i is None:
        add("test-bar-gate", True, False, "no dev-lead gate_check (test-bar gate) found")
    elif first_review_i is not None and testbar_i > first_review_i:
        add("test-bar-gate", True, False, "test-bar gate_check fired after review started")
    else:
        add("test-bar-gate", True, True)

    reviewer_gate = any(e.get("event_type") == "gate_check" and e.get("agent") in REVIEWERS for e in events)
    add("reviewer-gate-check", True, reviewer_gate,
        "" if reviewer_gate else "no reviewer emitted a gate_check")

    # review must come after implementation began
    review_after = (first_review_i is not None and implement_i is not None and first_review_i > implement_i)
    add("review-after-implement", True, review_after,
        "" if review_after else "review did not occur after implementation")

    # --- Cost telemetry (cost-budget machinery ran) -------------------------
    rc = last if ends else next((e for e in reversed(events) if e.get("event_type") == "run_complete"), {})
    has_cost = bool(rc) and (rc.get("cost_usd", 0) or rc.get("tokens_in") or rc.get("tokens_out"))
    add("cost-telemetry", True, has_cost,
        "" if has_cost else "run_complete carries no cost_usd / token telemetry")

    return results


def check_file(path):
    with open(path, encoding="utf-8") as fh:
        raw = fh.read().splitlines()
    events, parse_errors = [], []
    for n, line in enumerate(raw, 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as ex:
            parse_errors.append(f"line {n}: {ex}")

    print(f"trajectory check: {path}")
    if parse_errors:
        print("  FAIL  valid-json")
        for pe in parse_errors[:5]:
            print(f"        {pe}")
        return 1
    if not events:
        print("  FAIL  non-empty: no events in stream")
        return 1

    results = run_checks(events)
    failed_required = 0
    for cid, required, ok, detail in results:
        tag = "PASS" if ok else ("FAIL" if required else "warn")
        if not ok and required:
            failed_required += 1
        line = f"  {tag:4}  {cid}"
        if detail and not ok:
            line += f"  - {detail}"
        print(line)

    print(f"  -> {len(results) - failed_required}/{len(results)} checks passed")
    return 0 if failed_required == 0 else 1


# ---------------------------------------------------------------------------
# Golden fixture (single source of truth for the fixture file AND the self-test)
# ---------------------------------------------------------------------------
def build_golden():
    rid = "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f"
    t = [0]

    def ev(agent, phase, etype, **kw):
        t[0] += 1
        e = {
            "timestamp": f"2026-04-15T08:{t[0] // 60:02d}:{t[0] % 60:02d}.000Z",
            "run_id": rid, "agent": agent, "phase": phase, "event_type": etype,
        }
        e.update(kw)
        return e

    return [
        ev("dev-lead", "bootstrap", "run_start",
           payload={"user_request_summary": "Add Bicep storage module", "profile_loaded": True}),
        ev("dev-lead", "research", "phase_start"),
        ev("architect", "research", "phase_start"),
        ev("architect", "research", "tool_call", tool_name="grep", args_summary="scan modules/ for storage patterns"),
        ev("architect", "research", "phase_complete", outcome="success"),
        ev("dev-lead", "research", "phase_complete", outcome="success"),
        ev("dev-lead", "plan", "phase_start"),
        ev("dev-lead", "plan", "phase_complete", outcome="success"),
        ev("dev-lead", "implement", "phase_start"),
        ev("coding", "coding", "handoff_received"),
        ev("coding", "coding", "phase_start"),
        ev("coding", "coding", "tool_call", tool_name="edit",
           args_summary="modules/storage.bicep - add hardened account", tokens_in=4200, tokens_out=610, cost_usd=0.018),
        ev("coding", "coding", "phase_complete", outcome="success"),
        ev("testing", "testing", "phase_start"),
        ev("testing", "testing", "tool_call", tool_name="powershell", args_summary="bicep build modules/storage.bicep"),
        ev("testing", "testing", "phase_complete", outcome="success"),
        ev("dev-lead", "implement", "phase_complete", outcome="success"),
        ev("dev-lead", "test-bar", "gate_check", outcome="success",
           payload={"gate": "lint+typecheck+unit", "retries": 0}),
        ev("dev-lead", "review", "phase_start"),
        ev("review", "review", "phase_start"),
        ev("security-review", "review", "gate_check", outcome="success", payload={"finding_count": 0}),
        ev("architecture-review", "review", "gate_check", outcome="success", payload={"finding_count": 0}),
        ev("test-review", "review", "gate_check", outcome="success", payload={"finding_count": 0}),
        ev("review", "review", "phase_complete", outcome="success"),
        ev("dev-lead", "review", "phase_complete", outcome="success"),
        ev("dev-lead", "wrap-up", "run_complete", outcome="success",
           tokens_in=84210, tokens_out=19880, cost_usd=0.612, duration_ms=524000),
    ]


def self_test():
    import copy
    golden = build_golden()

    def all_required_pass(events):
        return all(ok for _cid, req, ok, _d in run_checks(events) if req)

    def required_fail_ids(events):
        return {cid for cid, req, ok, _d in run_checks(events) if req and not ok}

    def mutate(fn):
        e = copy.deepcopy(golden)
        fn(e)
        return e

    cases = [("golden passes all required", all_required_pass(golden), True)]

    cases.append(("drop run_start trips starts-with-run-start",
                  "starts-with-run-start" in required_fail_ids(mutate(lambda e: e.pop(0))), True))

    def break_runid(e):
        e[5]["run_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    cases.append(("mixed run_id trips single-run-id",
                  "single-run-id" in required_fail_ids(mutate(break_runid)), True))

    def drop_testbar(e):
        del e[17]  # the dev-lead test-bar gate_check
    cases.append(("no test-bar gate trips test-bar-gate",
                  "test-bar-gate" in required_fail_ids(mutate(drop_testbar)), True))

    def drop_reviewer_gates(e):
        e[:] = [x for x in e if not (x["event_type"] == "gate_check" and x["agent"] in REVIEWERS)]
    cases.append(("no reviewer gate trips reviewer-gate-check",
                  "reviewer-gate-check" in required_fail_ids(mutate(drop_reviewer_gates)), True))

    def strip_cost(e):
        for k in ("cost_usd", "tokens_in", "tokens_out"):
            e[-1].pop(k, None)
    cases.append(("no cost on run_complete trips cost-telemetry",
                  "cost-telemetry" in required_fail_ids(mutate(strip_cost)), True))

    def unbalance(e):
        e.insert(2, dict(e[1], event_type="phase_start", agent="dev-lead", phase="research"))
    cases.append(("extra phase_start trips phases-balanced",
                  "phases-balanced" in required_fail_ids(mutate(unbalance)), True))

    ok = True
    for name, got, want in cases:
        if got != want:
            ok = False
        print(f"  {'PASS' if got == want else 'FAIL'}  {name}")
    print("self-test: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--self-test":
        return self_test()
    if argv[0] == "--emit-fixture":
        if len(argv) < 2:
            print("--emit-fixture needs an output path", file=sys.stderr)
            return 2
        with open(argv[1], "w", encoding="utf-8", newline="\n") as f:
            for e in build_golden():
                f.write(json.dumps(e) + "\n")
        print(f"wrote fixture: {argv[1]}")
        return 0
    return check_file(argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
