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

Exit codes: 0 ok, 2 a --max-* threshold was exceeded, 3 usage unavailable
(no store, unreadable, or unknown schema -- a tooling failure, not a budget breach).
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

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
    if not event_log or not os.path.isfile(event_log):
        return []
    open_phases, windows = {}, []
    with open(event_log, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            phase = event.get("phase")
            when = parse_ts(event.get("timestamp"))
            if not phase or when is None:
                continue
            kind = event.get("event_type")
            if kind == "phase_start":
                open_phases[phase] = when
            elif kind == "phase_complete" and phase in open_phases:
                windows.append((phase, open_phases.pop(phase), when))
    for phase, start in open_phases.items():
        windows.append((phase, start, None))
    return windows


def phase_for(when, windows):
    for phase, start, end in windows:
        if when >= start and (end is None or when <= end):
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
    out["usd"] = (round(out["aiu"] * usd_per_aiu, 4)
                  if usd_per_aiu is not None else None)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session-id", default=os.environ.get("COPILOT_AGENT_SESSION_ID"),
                    help="defaults to $COPILOT_AGENT_SESSION_ID")
    ap.add_argument("--store", default=os.environ.get("COPILOT_SESSION_STORE", DEFAULT_STORE))
    ap.add_argument("--event-log", help="run-event-log JSONL, for per-phase attribution")
    ap.add_argument("--since", help="ignore usage before this ISO-8601 timestamp")
    ap.add_argument("--usd-per-aiu", type=float,
                    help="rate card, USD per AI unit; without it `usd` stays null")
    ap.add_argument("--max-tokens", type=int, help="exit 2 if tokens_total exceeds this")
    ap.add_argument("--max-aiu", type=float, help="exit 2 if aiu exceeds this")
    ap.add_argument("--max-usd", type=float,
                    help="exit 2 if usd exceeds this; needs --usd-per-aiu")
    args = ap.parse_args()

    if not args.session_id:
        die_unavailable("no session id (pass --session-id or set COPILOT_AGENT_SESSION_ID)")
    if not os.path.isfile(args.store):
        die_unavailable("usage store not found at %s" % args.store)

    # Read-only: the CLI holds this database open for the duration of the run.
    uri = "file:%s?mode=ro" % args.store.replace("\\", "/")
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "select agent_id, model, initiator, input_tokens, output_tokens, "
            "reasoning_tokens, cache_read_tokens, total_nano_aiu, duration_ms, created_at "
            "from assistant_usage_events where session_id = ? order by created_at",
            (args.session_id,)).fetchall()
    except sqlite3.Error as exc:
        # A schema change in the CLI lands here. Report it, don't guess at numbers.
        die_unavailable("usage store unreadable: %s" % exc)

    windows = load_phase_windows(args.event_log)
    since = parse_ts(args.since)

    totals, by_phase, by_agent, unattributed = blank(), {}, {}, blank()
    for row in rows:
        when = parse_ts(row["created_at"])
        if since and when and when < since:
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
    }
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")

    breaches = []
    if args.max_tokens and result["totals"]["tokens_total"] > args.max_tokens:
        breaches.append("tokens %s exceeds %s" %
                        (result["totals"]["tokens_total"], args.max_tokens))
    if args.max_aiu is not None and result["totals"]["aiu"] > args.max_aiu:
        breaches.append("aiu %s exceeds %s" % (result["totals"]["aiu"], args.max_aiu))
    if args.max_usd is not None and result["usd"] is not None and result["usd"] > args.max_usd:
        breaches.append("usd %s exceeds %s" % (result["usd"], args.max_usd))
    if breaches:
        sys.stderr.write("cost envelope breached: %s\n" % "; ".join(breaches))
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
