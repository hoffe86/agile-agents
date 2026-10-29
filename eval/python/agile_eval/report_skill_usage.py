"""Report or score recorded skill invocation in existing Copilot JSONL logs.

Answers the question ADR 0015 was written to make measurable: when a task required a
skill, did the agent actually invoke it, or did it work from priors?

    python eval/deepeval/report_skill_usage.py eval/pipeline/runs

Add --score --expect-skill NAME --output summary.json for pinned DeepEval measurement.
No agents, models or generated artifacts are executed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agile_eval._console import use_utf8_stdio
from agile_eval.adapters.copilot_trace import SKILL_TOOL_NAME, Trace, parse_log, verify_schema


def discover_logs(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    if not root.is_dir():
        return []
    # CLI process logs in isolated config directories are not session transcripts.
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in {".log", ".jsonl"}
        and ".copilot-home" not in p.parts and ".copilot" not in p.parts
    )


def measure_skills(trace: Trace, expected: list[str]) -> float:
    """Measure unique expected identities, not arbitrary skill-tool presence.

    Only the identity reaches DeepEval: no prompts, outputs, other arguments or paths.
    In 4.1.8 non-exact input matching divides matching keys by all keys. Projecting
    both sides to one key makes each identity binary while preserving partial coverage
    across expectations. Extra/repeated calls and ordering do not affect coverage.
    """
    if not expected or any(not skill.strip() for skill in expected):
        raise ValueError("at least one nonempty expected skill is required")
    if verify_schema(trace):
        raise ValueError("cannot measure a trace with schema errors")
    from agile_eval.metrics.local_model import configure_offline, stub_model

    configure_offline()
    from importlib.metadata import version

    if version("deepeval") != "4.1.8":
        raise RuntimeError("ADR 0015 requires deepeval==4.1.8")
    from deepeval.metrics import ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams

    metric = ToolCorrectnessMetric(
        model=stub_model(), async_mode=False, threshold=1.0,
        evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
    )
    return metric.measure(
        LLMTestCase(
            input="Recorded skill invocation coverage",
            actual_output="Existing log; task quality not evaluated",
            tools_called=[
                ToolCall(name=SKILL_TOOL_NAME, input_parameters={"skill": skill})
                for skill in trace.skills_invoked
            ],
            expected_tools=[
                ToolCall(name=SKILL_TOOL_NAME, input_parameters={"skill": skill})
                for skill in dict.fromkeys(expected)
            ],
        ),
        _show_indicator=False,
    )


def score_logs(logs: list[Path], expected: list[str]) -> dict:
    """Return sanitized local results; errors never become measured failures."""
    report = {
        "schema_version": 1, "metric": "ToolCorrectnessMetric", "deepeval_version": "4.1.8",
        "scope": "recorded_skill_invocation", "expected_skills": list(dict.fromkeys(expected)),
        "threshold": 1.0, "status": "setup_error", "passed": None,
        "total": len(logs), "measured": 0, "results": [], "errors": [],
    }
    if not logs:
        report["errors"].append("no input logs found")
        return report
    for index, log in enumerate(logs, start=1):
        # Stable ordinal in sorted input order; filenames themselves can contain secrets.
        row = {"input_index": index, "status": "setup_error", "score": None, "passed": None,
               "errors": []}
        report["results"].append(row)
        try:
            trace = parse_log(log)
        except UnicodeError:
            row.update(status="schema_error", errors=["input is not valid UTF-8"])
            continue
        except OSError:
            row["errors"] = ["cannot read input log"]
            continue
        problems = verify_schema(trace)
        if problems:
            row.update(status="schema_error", errors=problems)
            continue
        try:
            score = measure_skills(trace, expected)
        except Exception:
            # Terminal dependency/metric boundary: don't leak exception text, model
            # configuration, file contents or credentials. Never substitute a score.
            row["errors"] = ["DeepEval setup or measurement failed; verify the pinned offline environment"]
            continue
        row.update(status="passed" if score == 1.0 else "failed", score=score, passed=score == 1.0)
        report["measured"] += 1
    statuses = {row["status"] for row in report["results"]}
    if "setup_error" in statuses:
        report["status"] = "setup_error"
    elif "schema_error" in statuses:
        report["status"] = "schema_error"
    else:
        report["passed"] = statuses == {"passed"}
        report["status"] = "passed" if report["passed"] else "failed"
    return report


def main(argv: list[str] | None = None) -> int:
    use_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", nargs="?", default="eval/pipeline/runs",
                    help="directory of run logs, or a single .log/.jsonl file")
    ap.add_argument("--expect-skill", action="append", default=[],
                    help="skill that should have been invoked; repeatable")
    ap.add_argument("--score", action="store_true",
                    help="measure recorded expected skill identities with pinned DeepEval")
    ap.add_argument("--output", type=Path, help="local JSON summary (required with --score)")
    args = ap.parse_args(argv)
    if args.score and (not args.expect_skill or any(not s.strip() for s in args.expect_skill)):
        ap.error("--score requires at least one nonempty --expect-skill")
    if args.score and (args.output is None or args.output.suffix.lower() != ".json"):
        ap.error("--score requires --output ending in .json")
    if args.output is not None and not args.score:
        ap.error("--output requires --score")

    root = Path(args.path)
    try:
        logs = discover_logs(root)
    except OSError:
        logs = []
    if args.score:
        try:
            try:
                args.output.stat()
            except FileNotFoundError:
                output_exists = False
            else:
                output_exists = True
            overwrites_input = any(
                args.output.resolve() == log.resolve()
                or (output_exists and args.output.samefile(log))
                for log in logs
            )
        except OSError:
            print("SETUP ERROR: cannot verify local JSON summary file identity.")
            return 2
        if overwrites_input:
            ap.error("--output must not overwrite an input log")
        report = score_logs(logs, args.expect_skill)
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError:
            print("SETUP ERROR: cannot write local JSON summary.")
            return 2
        print(f"Recorded skill invocation: {report['status']} "
              f"({report['measured']}/{report['total']} inputs measured).")
        return {"passed": 0, "failed": 1}.get(report["status"], 2)
    if not logs:
        print(f"no logs found under {root}")
        return 1

    drifted = False
    bypassed = False

    for log in logs:
        try:
            trace = parse_log(log)
        except (OSError, UnicodeError):
            print("SCHEMA/INPUT ERROR: cannot read a UTF-8 session log.")
            drifted = True
            continue
        problems = verify_schema(trace)

        print(f"\n{log.parent.name}/{log.name}")
        print(f"  events={trace.events_parsed}  turns={trace.turns}  tools={len(trace.tools)}")
        print(f"  skills offered: {len(trace.skills_offered)}")
        print(f"  skills invoked: {', '.join(trace.skills_invoked) or '(none)'}")

        if problems:
            drifted = True
            for p in problems:
                print(f"  SCHEMA: {p}")

        for expected in args.expect_skill:
            hit = expected in trace.skills_invoked
            print(f"  expected '{expected}': {'INVOKED' if hit else 'BYPASSED'}")
            if not hit:
                bypassed = True

    # A schema problem is a harness fault and must not read as an agent result.
    if drifted:
        print("\nSCHEMA DRIFT DETECTED - results above understate tool use; fix the adapter first.")
        return 2
    if bypassed:
        print("\nAt least one expected skill was bypassed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
