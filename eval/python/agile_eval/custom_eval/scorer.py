"""Score custom-eval runs: trajectory with DeepEval, acceptance with a pluggable judge.

    python eval/pipeline/score_custom_eval.py <run-dir> [<run-dir> ...] \
        --judge none|azure-openai --output summary.json

Each run directory is one produced by run_custom_eval.py. The trajectory -- did dev-lead
stop at the plan gate, delegate to the expected agents, and did each agent invoke the
skills it is expected to -- is scored deterministically. Acceptance evidence is what the
runner recorded in the agent's trust zone: the diff against the staged baseline, and
`checks.json`, the exit codes of the task's declared build / test / render commands.
Failing commands fail their criterion outright; the judge grades what no command covers.
The scorer runs no git and no workspace code, so it is safe in a job that holds judge
credentials.

Exit codes follow acceptance-grading: 0 resolved / 1 failed / 2 partial /
3 unverified (or approval still pending) / 4 setup or judge environment error.
A trajectory failure or a skipped plan gate counts as failed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agile_eval._console import use_utf8_stdio
from agile_eval.adapters.copilot_trace import parse_log_text, verify_schema
from agile_eval.custom_eval.checks import CHECKS_FILE, apply_checks, evidence, load_results
from agile_eval.custom_eval.expectations import ExpectationsError, load
from agile_eval.custom_eval.judges import JUDGES, JudgeError, judge
from agile_eval.custom_eval.metrics import delegation_metric, plan_gate_metric, skill_metrics
from agile_eval.custom_eval.runner import STATE_FILE, Paths, default_tasks_root, resolve_task

EXIT = {"resolved": 0, "failed": 1, "partial": 2, "unverified": 3, "setup_error": 4}


def produced_diff(paths: Paths) -> str:
    """The diff the runner captured. Never runs git in the agent-written workspace."""
    try:
        text = paths.diff.read_text(encoding="utf-8")
    except OSError:
        raise JudgeError(f"no captured {paths.diff.name}; the run did not finish phase 1") from None
    return text or "(no changes were produced)"


def outcome(state_status: str, gate_ok: bool | None, trajectory_ok: bool, verdict: str) -> str:
    if state_status == "setup_error":
        return "setup_error"
    if state_status == "blocked_approval" or state_status == "awaiting_approval":
        return "unverified"
    if gate_ok is False or not trajectory_ok or verdict == "FAILED":
        return "failed"
    return {"RESOLVED": "resolved", "PARTIAL": "partial"}.get(verdict, "unverified")


def score_run(run: Path, judge_name: str, tasks_root: Path) -> dict:
    paths = Paths(run)
    row: dict = {"run": run.name, "status": "setup_error", "errors": []}
    try:
        state = json.loads(paths.state.read_text(encoding="utf-8"))
        row.update(task=state["task"], run_status=state["status"])
        exp = load(resolve_task(tasks_root, state["task"]))
    except (OSError, ValueError, KeyError):
        row["errors"].append(f"unreadable {STATE_FILE}")
        return row
    except ExpectationsError as exc:
        row["errors"].append(f"task definition: {exc}")
        return row
    except RuntimeError as exc:
        row["errors"].append(str(exc))
        return row
    if state["status"] in ("dry_run", "staged", "setup_error"):
        row["errors"].append(f"run status {state['status']} cannot be scored")
        return row

    phase1_text = paths.log(1).read_text(encoding="utf-8") if paths.log(1).exists() else ""
    phase2_text = paths.log(2).read_text(encoding="utf-8") if paths.log(2).exists() else ""
    phase1 = parse_log_text(phase1_text)
    combined = parse_log_text(phase1_text + "\n" + phase2_text)
    problems = verify_schema(combined, require_skills_offered=False)
    if problems:
        row["errors"] += problems
        return row

    try:
        gate, _ = plan_gate_metric(phase1, exp)
        trajectory = [delegation_metric(combined, exp), *skill_metrics(combined, exp)]
    except Exception:
        row["errors"].append("DeepEval trajectory measurement failed; check the pinned environment")
        return row
    results = load_results(run, exp)
    try:
        judgement = judge(
            judge_name, (resolve_task(tasks_root, state["task"]) / "prompt.md").read_text(
                encoding="utf-8"),
            exp.criteria, exp.unverifiable,
            produced_diff(paths), command_evidence=evidence(results),
        )
    except JudgeError as exc:
        row["errors"].append(str(exc))
        return row
    if judgement.contract_errors:
        row["errors"] += [f"judge contract: {e}" for e in judgement.contract_errors]
    apply_checks(judgement, exp, results)

    trajectory_ok = all(m.passed for m in trajectory)
    row.update(
        status="setup_error" if judgement.contract_errors else outcome(
            state["status"], gate.passed, trajectory_ok, judgement.verdict),
        plan_gate=gate.to_dict(),
        trajectory=[m.to_dict() for m in trajectory],
        acceptance=judgement.to_dict(),
        checks=None if results is None else [
            {k: v for k, v in r.items() if k != "output_tail"} for r in results],
        usage=combined.result.get("usage") if combined.result else None,
    )
    if exp.checks and results is None and state["status"] in ("complete", "gate_skipped"):
        row["errors"].append(f"no matching {CHECKS_FILE}; run run_custom_eval.py --phase verify "
                             "to execute the acceptance checks")
    return row


def aggregate(rows: list[dict]) -> str:
    statuses = {r["status"] for r in rows}
    for status in ("setup_error", "failed", "partial", "unverified"):
        if status in statuses:
            return status
    return "resolved" if rows else "setup_error"


def main(argv: list[str] | None = None) -> int:
    use_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", type=Path, help="run directories from run_custom_eval")
    ap.add_argument("--judge", choices=JUDGES, default="none")
    ap.add_argument("--output", type=Path, required=True, help="JSON summary path")
    ap.add_argument("--tasks-root", type=Path, default=default_tasks_root())
    args = ap.parse_args(argv)
    if args.output.suffix.lower() != ".json":
        ap.error("--output must end in .json")

    rows = [score_run(run, args.judge, args.tasks_root) for run in args.runs]
    report = {"schema_version": 1, "judge": args.judge, "status": aggregate(rows),
              "total": len(rows),
              "counts": {s: sum(r["status"] == s for r in rows) for s in EXIT},
              "results": rows}
    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError:
        print("SETUP ERROR: cannot write the JSON summary.")
        return 4
    for r in rows:
        line = f"{r.get('task', r['run'])}: {r['status']}"
        failing = [m["name"] for m in r.get("trajectory", []) if not m["passed"]]
        if r.get("plan_gate", {}).get("passed") is False:
            failing.insert(0, "plan_gate")
        if failing:
            line += f"  (trajectory: {', '.join(failing)})"
        if r.get("acceptance"):
            line += f"  acceptance={r['acceptance']['verdict']}"
        if r.get("checks"):
            passed = sum(c["status"] == "passed" for c in r["checks"])
            line += f"  checks={passed}/{len(r['checks'])} passed"
        print(line)
        for e in r["errors"]:
            print(f"  ERROR: {e}")
    print(f"overall: {report['status']} ({len(rows)} task(s))")
    return EXIT[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
