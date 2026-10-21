"""Offline evaluation preparation. Live execution is unconditionally held."""

from __future__ import annotations

import os
import sys

import argparse
from concurrent.futures import CancelledError
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sysconfig
import uuid

ROOT = Path(__file__).resolve().parents[3]
PIPELINE = ROOT / "eval/pipeline"

HOLD = (
    "live evaluation is disabled: no verified OS sandbox for untrusted artifact workers "
    "(no host credentials or external/host/control-plane network). Use --dry-run for "
    "offline staging and preflight, not execution-readiness certification."
)


def dependency_path() -> None:
    """Expose this interpreter's packages without executing .pth/sitecustomize hooks.

    Before Python 3.14, -S does not set the venv prefix. Preserve the executable's
    venv (including symlinked POSIX launchers), rather than selecting base packages.
    """
    prefix = Path(sys.executable).absolute().parent.parent
    if (prefix / "pyvenv.cfg").is_file():
        packages = (prefix / "Lib/site-packages" if os.name == "nt" else
                    prefix / f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages")
        sys.path.append(str(packages))
    else:
        sys.path.extend(dict.fromkeys(sysconfig.get_path(key) for key in ("purelib", "platlib")))


def threshold(value: str) -> int:
    if not re.fullmatch(r"[0-9]{1,3}", value) or int(value) > 100:
        raise argparse.ArgumentTypeError("--pass-threshold must be an integer from 0 through 100")
    return int(value)


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", required=True, choices=("custom-eval", "swe-bench-subset"))
    parser.add_argument("--task-filter", default=".*")
    parser.add_argument("--pass-threshold", type=threshold, default=60)
    parser.add_argument("--output-root", type=Path, default=PIPELINE / "runs")
    parser.add_argument("--agent-model", default=os.environ.get("AGENT_MODEL", "claude-opus-4.8"))
    parser.add_argument("--judge-model", default=os.environ.get("JUDGE_MODEL", "gpt-5.6-sol"))
    parser.add_argument("--scorer", default=os.environ.get("EVAL_SCORER", "deepeval"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-isolation", action="store_true",
                        help="Historical option; never bypasses the live execution hold.")
    args = parser.parse_args(argv)
    if args.scorer != "deepeval":
        parser.error("--scorer shell/both are retired; use --scorer deepeval. "
                     "Historical reproduction: git ref ccafa13e1c782220db001ac081433dca2ae1df54.")
    if args.agent_model == args.judge_model:
        parser.error("agent and judge models must differ; set --judge-model to a different model")
    try:
        args.task_filter = re.compile(args.task_filter)
    except re.error:
        parser.error("--task-filter must be a valid Python regular expression")
    return args


def live_hold() -> int:
    # Diagnostic status is never permission, including exceptions, missing files,
    # and a diagnostic that mistakenly exits zero. No setup precedes this hold.
    try:
        subprocess.run(
            [sys.executable, "-I", "-S", "-B", str(ROOT / "eval/authorization.py"),
             "check-readiness"], check=False, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        print("Readiness diagnostic unavailable.", file=sys.stderr)
    print("ERROR: " + HOLD, file=sys.stderr)
    return 2


def selected_tasks(args: argparse.Namespace) -> list[str]:
    suite = PIPELINE / args.suite
    if args.suite == "custom-eval":
        tasks = sorted(path.name for path in (suite / "tasks").iterdir() if path.is_dir())
    else:
        tasks = [row["instance_id"] for row in json.loads((suite / "tasks.json").read_text("utf-8"))]
    from agile_eval.provenance import identifier

    selected = [identifier(task) for task in tasks if args.task_filter.search(task)]
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("no tasks matched the filter, or task ids are duplicated")
    return selected


def summary(args: argparse.Namespace, run: Path, tasks: list[dict], errors: list) -> dict:
    from agile_eval.provenance import STATUSES

    return {
        "suite": args.suite, "run_id": run.name,
        "run_status": "setup_error" if errors else "skipped",
        "total": len(tasks), "tasks": tasks, "setup_errors": errors,
        **{count: sum(task["status"] == status for task in tasks)
           for status, count in STATUSES.items()},
        "dry_run": True, "scorer": "deepeval", "agent_model": args.agent_model,
        "judge_model": args.judge_model, "isolated": False, "mcp_servers": "not invoked",
        "live_run_status": "blocked_approval: live runs also require the unavailable OS sandbox",
        # No scored work: zero would incorrectly claim a measured failure rate.
        "resolved_pct": None, "partial_pct": None, "failed_pct": None,
    }


def prepare_run(args: argparse.Namespace, ids: list[str]) -> int:
    from agile_eval.file_io import checked_path, write_json
    from agile_eval.provenance import (
        MANIFEST, build_context, failed_start, finalize, manifest,
    )

    run = args.output_root / (
        f"{datetime.now():%Y%m%d-%H%M%S}-{args.suite}-{uuid.uuid4().hex}"
    )
    try:
        checked_path(run)
        run.mkdir(parents=True)
        dependency_path()
        context = build_context(
            ROOT, run.name, ids, suite=args.suite, agent=args.agent_model,
            judge=args.judge_model, scorer="deepeval", native="python",
            native_version=sys.version.split()[0], output_root=args.output_root,
        )
        write_json(run / MANIFEST, manifest(context))
    except CancelledError:
        raise
    except Exception:
        # Terminal startup boundary: retain every selected task, including when
        # dependency initialization fails. BaseException interrupts still propagate.
        try:
            failed_start(run, run.name, ids, args.suite)
        except (OSError, ValueError, KeyError, TypeError):
            print("Failure metadata could not be retained in the output directory.", file=sys.stderr)
        print("SETUP ERROR: cannot capture run provenance; no staging or execution.", file=sys.stderr)
        return 2

    errors = []
    prepared = {}
    try:
        if args.suite != "custom-eval":
            raise ValueError("SWE-bench task-prep not wired: dataset fetch and checkout required")
        try:
            from agile_eval.prepare_inputs import prepare_many
        except ImportError as exc:
            raise ValueError("PyYAML is required; use the interpreter with "
                             "eval/deepeval/requirements-yaml.lock.txt installed") from exc
        preflight = prepare_many(PIPELINE / args.suite, run, ids)
        write_json(run / "preflight.json", preflight)
        prepared = {row["task_id"]: row["status"] for row in preflight["tasks"]}
        if sorted(prepared) != sorted(ids) or preflight["status"] != "prepared":
            errors = preflight.get("errors") or ["fixture preparation did not complete"]
        else:
            # Re-read every prompt after staging. Disappearance/read failure must
            # invalidate the whole selected inventory, not abort a shell loop.
            for task in ids:
                (PIPELINE / args.suite / "tasks" / task / "prompt.md").read_text("utf-8")
    except CancelledError:
        raise
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors = [str(exc)]
    except Exception:
        # Unexpected dependency/parser failures are setup errors, not success or
        # agent failures. Do not persist an arbitrary exception message/traceback.
        errors = ["fixture preparation failed during initialization or preflight; "
                  "no agent or judge was invoked"]

    tasks = [{"id": task, "status": "setup_error" if errors else "skipped",
              "preparation_status": prepared.get(task, "setup_error"),
              "grading": {"deepeval": None}} for task in ids]
    try:
        for task in tasks:
            (run / f"{task['id']}.log").write_text(
                "[setup_error] no agent or judge invoked.\n" if errors else
                "[DRY RUN] fixture prepared; no agent or judge invoked. Live SDK execution held.\n",
                encoding="utf-8",
            )
        write_json(run / "summary.json", summary(args, run, tasks, errors))
        finalize(run, context)
    except (OSError, ValueError, KeyError, TypeError):
        failed_start(run, run.name, ids, args.suite)
        print("SETUP ERROR: provenance retention failed.", file=sys.stderr)
        return 2
    print(f"Summary: {run / 'summary.json'}")
    if errors:
        print(f"SETUP ERROR: {errors}", file=sys.stderr)
        # Historical SWE dry runs are manifest/wiring checks, not implemented
        # task preparation. Keep their exit 0 without awarding any scored credit.
        return 0 if args.suite == "swe-bench-subset" else 2
    print(f"DRY RUN — wiring validated for {len(ids)} task(s); none executed, none scored.")
    print("Live run blocked: OS sandbox unavailable; mandatory plan approval requires a human response.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = arguments(argv)
    if not args.dry_run:
        return live_hold()
    try:
        ids = selected_tasks(args)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: task selection failed: {exc}", file=sys.stderr)
        return 2
    return prepare_run(args, ids)


if __name__ == "__main__":
    raise SystemExit(main())
