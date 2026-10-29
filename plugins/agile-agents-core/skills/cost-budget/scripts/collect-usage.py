#!/usr/bin/env python3
"""Collect real token/AIU usage for the current run from the CLI's own usage store.

Agents cannot observe their own token consumption -- there is no tool, env var, or
transcript field that exposes it. Any self-reported figure is invented. The runtime,
however, already meters every model call, so this script reads that record instead of
asking an agent to guess.

Attribution is by time window: `dev-lead` emits `phase_start` / `phase_complete` events
with timestamps, and each usage row is assigned to whichever phase window contains it.
That is why worker agents do not need to emit anything -- the orchestrator is the only
agent that knows the phase structure, and it is the only one that has to instrument.

Output (stdout, JSON):

    {
      "session_id": "...",
      "totals":   { "calls", "tokens_in", "tokens_out", "tokens_reasoning",
                    "tokens_cache_read", "tokens_total", "aiu", "duration_ms" },
      "by_phase": { "<phase>": { ...same shape..., "models": [...] } },
      "by_agent": { "<agent>": { ...same shape..., "models": [...] } },
      "usd":       null | <float>,
      "usd_basis": "not-metered" | "rate:<n> USD per AIU",
      "unattributed": <same shape - usage outside every phase window>
    }

`aiu` is the runtime's own metered cost unit and is the number to gate on. Do not derive
cost from a flat per-token rate: `token_details_json` shows cache reads billing at a tenth
of fresh input, so a flat rate overstates a long run by an order of magnitude. `usd` stays
null unless --usd-per-aiu supplies the org's rate; reporting a fabricated 0.00 is what made
the old cost gate pass silently.

Exit codes: 0 ok (warnings at 80%), 2 usage reached 110% of a cap, 3 usage
unavailable or invalid metering configuration. Run caps apply to --since-bounded
totals; --phase and --max-phase-aiu apply only to that named phase bucket.
"""

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

DEFAULT_STORE = os.path.join(os.path.expanduser("~"), ".copilot", "session-store.db")

METRICS = ("calls", "tokens_in", "tokens_out", "tokens_reasoning",
           "tokens_cache_read", "tokens_total", "aiu", "duration_ms")


def die_unavailable(reason):
    json.dump({"error": "usage-unavailable", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    sys.exit(3)


def parse_ts(value):
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or None."""
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def load_phase_windows(event_log):
    """Build [(phase, start, end)] from a run-event-log JSONL file.

    An unclosed phase (the run died mid-stage, or we are checkpointing the phase that
    just finished before its complete event lands) stays open rather than being dropped,
    so its usage is still attributed instead of silently vanishing into `unattributed`.
    """
    if not event_log:
        return []
    if not os.path.isfile(event_log):
        die_unavailable("event log not found at %s" % event_log)
    open_phases, windows = {}, []
    try:
        with open(event_log, "r", encoding="utf-8-sig") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError as exc:
                    die_unavailable("invalid event JSON at line %s: %s" % (number, exc))
                if not isinstance(event, dict):
                    die_unavailable("event at line %s is not an object" % number)
                kind = event.get("event_type")
                if kind not in ("phase_start", "phase_complete"):
                    continue
                phase = event.get("phase")
                when = parse_ts(event.get("timestamp"))
                if not isinstance(phase, str) or not phase or when is None:
                    die_unavailable("invalid phase boundary at line %s" % number)
                if kind == "phase_start":
                    if open_phases:
                        die_unavailable("overlapping phase windows at line %s" % number)
                    open_phases[phase] = when
                elif phase not in open_phases:
                    die_unavailable("phase completion without start at line %s" % number)
                else:
                    start = open_phases.pop(phase)
                    if when < start:
                        die_unavailable("phase completes before its start at line %s" % number)
                    windows.append((phase, start, when))
    except (OSError, UnicodeError) as exc:
        die_unavailable("event log unreadable: %s" % exc)
    for phase, start in open_phases.items():
        windows.append((phase, start, None))
    windows.sort(key=lambda window: window[1])
    for previous, current in zip(windows, windows[1:]):
        if previous[2] is None or previous[2] > current[1]:
            die_unavailable("overlapping phase windows")
    return windows


def phase_for(when, windows):
    for phase, start, end in windows:
        if when >= start and (end is None or when < end):
            return phase
    return None


def blank():
    bucket = {metric: 0 for metric in METRICS}
    bucket["models"] = set()
    return bucket


def add(bucket, row):
    bucket["calls"] += 1
    bucket["tokens_in"] += row["input_tokens"] or 0
    bucket["tokens_out"] += row["output_tokens"] or 0
    bucket["tokens_reasoning"] += row["reasoning_tokens"] or 0
    bucket["tokens_cache_read"] += row["cache_read_tokens"] or 0
    bucket["aiu"] += row["total_nano_aiu"] or 0
    bucket["duration_ms"] += row["duration_ms"] or 0
    bucket["tokens_total"] = bucket["tokens_in"] + bucket["tokens_out"]
    if row["model"]:
        bucket["models"].add(row["model"])


def finish(bucket, usd_per_aiu):
    out = {metric: bucket[metric] for metric in METRICS}
    out["aiu"] = round(bucket["aiu"] / 1e9, 4)
    out["models"] = sorted(bucket["models"])
    out["usd"] = (round(float(Decimal(bucket["aiu"]) / Decimal(10**9) * usd_per_aiu), 4)
                  if usd_per_aiu is not None else None)
    return out


def cap_value(value, name):
    if value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        die_unavailable("%s must be a finite non-negative number" % name)
    if not parsed.is_finite() or parsed < 0 or not math.isfinite(float(parsed)):
        die_unavailable("%s must be a finite non-negative number" % name)
    return parsed


def check_cap(actual, limit, scope, metric, warnings, breaches, phase=None):
    if limit is None:
        return
    actual = Decimal(actual)
    detail = {"scope": scope, "metric": metric, "actual": float(actual),
              "limit": float(limit)}
    if phase is not None:
        detail["phase"] = phase
    # A zero cap permits zero usage, but any positive usage breaches it.
    if actual > limit and actual >= limit * Decimal("1.1"):
        breaches.append(detail)
    elif actual > 0 and actual >= limit * Decimal("0.8"):
        warnings.append(detail)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-id", default=os.environ.get("COPILOT_AGENT_SESSION_ID"),
                    help="defaults to $COPILOT_AGENT_SESSION_ID")
    ap.add_argument("--store", default=os.environ.get("COPILOT_SESSION_STORE", DEFAULT_STORE))
    ap.add_argument("--event-log", help="run-event-log JSONL, for per-phase attribution")
    ap.add_argument("--since", help="ignore usage before this ISO-8601 timestamp")
    ap.add_argument("--usd-per-aiu",
                    help="rate card, USD per AI unit; without it `usd` stays null")
    ap.add_argument("--max-tokens", help="run token cap; breach at 110%")
    ap.add_argument("--max-aiu", help="run AIU cap; breach at 110%")
    ap.add_argument("--max-usd", help="run USD cap; needs --usd-per-aiu")
    ap.add_argument("--phase", help="exact phase label to gate, requires --max-phase-aiu")
    ap.add_argument("--max-phase-aiu", help="AIU cap for --phase, not the run total")
    args = ap.parse_args()

    since = parse_ts(args.since)
    if args.since is not None and since is None:
        die_unavailable("invalid --since ISO-8601 timestamp")
    max_tokens = cap_value(args.max_tokens, "--max-tokens")
    if max_tokens is not None and max_tokens != max_tokens.to_integral_value():
        die_unavailable("--max-tokens must be an integer")
    max_aiu = cap_value(args.max_aiu, "--max-aiu")
    max_usd = cap_value(args.max_usd, "--max-usd")
    max_phase_aiu = cap_value(args.max_phase_aiu, "--max-phase-aiu")
    rate = cap_value(args.usd_per_aiu, "--usd-per-aiu")
    if max_usd is not None and rate is None:
        die_unavailable("--max-usd requires --usd-per-aiu")
    if since is None and any(cap is not None for cap in
                             (max_tokens, max_aiu, max_usd, max_phase_aiu)):
        die_unavailable("gating requires --since with the persisted run-start timestamp")
    if (args.phase is None) != (max_phase_aiu is None) or args.phase == "":
        die_unavailable("--phase and --max-phase-aiu must be supplied together")
    if args.phase is not None and not args.event_log:
        die_unavailable("--phase requires --event-log")
    args.usd_per_aiu = rate

    if not args.session_id:
        die_unavailable("no session id (pass --session-id or set COPILOT_AGENT_SESSION_ID)")
    if not os.path.isfile(args.store):
        die_unavailable("usage store not found at %s" % args.store)

    # Read-only: the CLI holds this database open for the duration of the run.
    uri = "file:%s?mode=ro" % args.store.replace("\\", "/")
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "select agent_id, model, initiator, input_tokens, output_tokens, "
                "reasoning_tokens, cache_read_tokens, total_nano_aiu, duration_ms, created_at "
                "from assistant_usage_events where session_id = ? order by created_at",
                (args.session_id,)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        # A schema change in the CLI lands here. Report it, don't guess at numbers.
        die_unavailable("usage store unreadable: %s" % exc)

    windows = load_phase_windows(args.event_log)

    totals, by_phase, by_agent, unattributed = blank(), {}, {}, blank()
    for row in rows:
        when = parse_ts(row["created_at"])
        if when is None and (since is not None or args.event_log):
            die_unavailable("usage row has an invalid timestamp")
        if since and when < since:
            continue
        add(totals, row)
        phase = phase_for(when, windows) if when else None
        if phase:
            by_phase.setdefault(phase, blank())
            add(by_phase[phase], row)
        else:
            add(unattributed, row)
        # NULL agent_id is the orchestrator's own thread; anything else is one delegation.
        agent = row["agent_id"] or "dev-lead"
        by_agent.setdefault(agent, blank())
        add(by_agent[agent], row)

    if args.phase is not None:
        if not any(window[0] == args.phase for window in windows):
            die_unavailable("no attribution window for phase %s" % args.phase)
        # A valid empty phase window means measured zero usage, not absent evidence.
        by_phase.setdefault(args.phase, blank())
    warnings, breaches = [], []
    run_aiu = Decimal(totals["aiu"]) / Decimal(10**9)
    check_cap(totals["tokens_total"], max_tokens, "per_run", "tokens", warnings, breaches)
    check_cap(run_aiu, max_aiu, "per_run", "aiu", warnings, breaches)
    if rate is not None:
        check_cap(run_aiu * rate, max_usd, "per_run", "usd", warnings, breaches)
    if args.phase is not None:
        phase_aiu = Decimal(by_phase[args.phase]["aiu"]) / Decimal(10**9)
        check_cap(phase_aiu, max_phase_aiu, "per_phase", "aiu", warnings, breaches, args.phase)

    result = {
        "session_id": args.session_id,
        "totals": finish(totals, args.usd_per_aiu),
        "by_phase": {k: finish(v, args.usd_per_aiu) for k, v in by_phase.items()},
        "by_agent": {k: finish(v, args.usd_per_aiu) for k, v in by_agent.items()},
        "usd": finish(totals, args.usd_per_aiu)["usd"],
        "usd_basis": ("rate:%s USD per AIU" % args.usd_per_aiu
                      if args.usd_per_aiu is not None else "not-metered"),
        # Usage outside every phase window. A large figure here means the phase
        # events are wrong, not that the work was free - the by_phase table is
        # under-reporting by exactly this much.
        "unattributed": finish(unattributed, args.usd_per_aiu),
        "warnings": warnings,
        "breaches": breaches,
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    if warnings:
        sys.stderr.write("cost envelope warning (>=80%%): %s\n" % json.dumps(warnings))
    if breaches:
        sys.stderr.write("cost envelope breached (>=110%%): %s\n" % json.dumps(breaches))
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
