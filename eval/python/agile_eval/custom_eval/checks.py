"""Command-based acceptance checks: build, test, type-check and render criteria by exit code.

The runner executes each task's declared checks in the produced workspace right after the
agent finishes -- the agent's own trust zone, the same reasoning as `capture_diff`. The
results go to `checks.json`; the scorer only reads that file, so it still runs no
workspace code and can safely hold judge credentials.

Per criterion, after the judge has graded:
  any check failed or timed out      -> FAIL, whatever the judge said
  else any check unavailable         -> UNVERIFIED (a missing tool is never agent failure)
  else all passed, on_pass: pass     -> PASS
  else all passed, some on_pass: judge -> the judge decides the remaining clause
Declared checks with no `checks.json` leave their criteria UNVERIFIED.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from agile_eval.custom_eval.expectations import Check, Expectations
from agile_eval.custom_eval.judges import CriterionResult, Judgement, verdict_for

CHECKS_FILE = "checks.json"
PYTHON = "{python}"
PROBE_TIMEOUT = 60
OUTPUT_TAIL_CHARS = 4000
# Only what toolchains need to start. Tokens and cloud credentials never reach agent code.
ENV_ALLOWLIST = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "TEMP", "TMP",
    "TMPDIR", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMFILES",
    "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA", "LANG", "LC_ALL", "DOTNET_ROOT",
    "NUGET_PACKAGES",
)
ENV_FIXED = {
    "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
    "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1", "MSBUILDDISABLENODEREUSE": "1",
    "UseSharedCompilation": "false", "PYTHONDONTWRITEBYTECODE": "1",
}
PASSED, FAILED, UNAVAILABLE, TIMEOUT = "passed", "failed", "unavailable", "timeout"


def check_env() -> dict[str, str]:
    upper = {k.upper(): v for k, v in os.environ.items()}
    env = {k: upper[k] for k in ENV_ALLOWLIST if k in upper}
    env.update(ENV_FIXED)
    return env


def _resolve(argv: tuple[str, ...], env: dict[str, str]) -> list[str] | None:
    """Substitute {python} and resolve the executable; None when it is not installed."""
    args = [sys.executable if a == PYTHON else a for a in argv]
    exe = args[0] if argv[0] == PYTHON else shutil.which(args[0], path=env.get("PATH"))
    if exe is None:
        return None
    return [exe, *args[1:]]


def display(argv: tuple[str, ...]) -> str:
    return " ".join(argv)


def _probe(argv: tuple[str, ...], cwd: Path, env: dict[str, str]) -> str | None:
    """Reason the probe failed, or None when the required tool is usable."""
    cmd = _resolve(argv, env)
    if cmd is None:
        return f"{argv[0]} is not installed"
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=PROBE_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return f"probe `{display(argv)}` could not run"
    return None if proc.returncode == 0 else f"probe `{display(argv)}` failed"


def _tail(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= OUTPUT_TAIL_CHARS else "[...]\n" + text[-OUTPUT_TAIL_CHARS:]


def run_check(check: Check, index: int, workspace: Path, log_dir: Path,
              env: dict[str, str]) -> dict:
    result = {"index": index, "criterion": check.criterion, "command": display(check.run),
              "cwd": check.cwd, "on_pass": check.on_pass, "status": UNAVAILABLE,
              "exit_code": None, "duration_s": None, "reason": "", "output_tail": ""}
    root = workspace.resolve()
    cwd = (workspace / check.cwd).resolve()
    if cwd != root and root not in cwd.parents:
        result.update(status=FAILED, reason="cwd resolves outside the workspace")
        return result
    if not cwd.is_dir():
        result.update(status=FAILED, reason=f"cwd {check.cwd} does not exist")
        return result
    for probe in check.requires:
        reason = _probe(probe, root, env)
        if reason:
            result["reason"] = reason
            return result
    cmd = _resolve(check.run, env)
    if cmd is None:
        result["reason"] = f"{check.run[0]} is not installed"
        return result
    # Output goes to a file, not a pipe: a grandchild that outlives a timeout (a build
    # server, a test host) would otherwise hold the pipe open and hang the runner.
    log = log_dir / f"check-{index:02d}.log"
    started = time.monotonic()
    with log.open("w", encoding="utf-8", errors="replace") as out:
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out,
                                  stderr=subprocess.STDOUT, timeout=check.timeout, check=False)
        except subprocess.TimeoutExpired:
            result.update(status=TIMEOUT, reason=f"timed out after {check.timeout}s")
        except OSError:
            result.update(reason=f"{check.run[0]} could not be started")
        else:
            result["exit_code"] = proc.returncode
            output = log.read_text(encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                result.update(status=FAILED, reason=f"exit code {proc.returncode}")
            elif check.fail_if_output_matches and re.search(
                    check.fail_if_output_matches, output, re.MULTILINE):
                result.update(status=FAILED, reason="output matched the failure pattern")
            else:
                result.update(status=PASSED, reason="exit code 0")
    result["duration_s"] = round(time.monotonic() - started, 1)
    result["output_tail"] = _tail(log)
    return result


def run_checks(exp: Expectations, workspace: Path, run_dir: Path) -> dict:
    """Run every declared check and write checks.json; returns the written report."""
    log_dir = run_dir / "checks"
    log_dir.mkdir(parents=True, exist_ok=True)
    env = check_env()
    results = [run_check(c, i, workspace, log_dir, env) for i, c in enumerate(exp.checks)]
    report = {"schema": 1, "task": exp.task, "results": results}
    (run_dir / CHECKS_FILE).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8",
                                       newline="\n")
    return report


def load_results(run_dir: Path, exp: Expectations) -> list[dict] | None:
    """The recorded results, or None when absent or recorded for different checks."""
    try:
        report = json.loads((run_dir / CHECKS_FILE).read_text(encoding="utf-8"))
        results = report["results"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(results, list) or len(results) != len(exp.checks):
        return None
    for i, (r, c) in enumerate(zip(results, exp.checks)):
        if (not isinstance(r, dict) or r.get("index") != i or r.get("criterion") != c.criterion
                or r.get("command") != display(c.run)):
            return None
    return results


def evidence(results: list[dict] | None) -> str:
    """Command results formatted for the judge; output is untrusted agent-produced text."""
    if not results:
        return ""
    blocks = []
    for r in results:
        blocks.append(f"criterion {r['criterion']}: `{r['command']}` (cwd {r['cwd']}) -> "
                      f"{r['status'].upper()} ({r['reason']})\n{r.get('output_tail', '')}")
    return "\n\n".join(blocks)


def apply_checks(judgement: Judgement, exp: Expectations, results: list[dict] | None) -> None:
    """Let recorded command results decide the criteria they cover; recompute the verdict."""
    by_criterion: dict[int, list[dict]] = {}
    declared: dict[int, list[Check]] = {}
    for i, c in enumerate(exp.checks):
        declared.setdefault(c.criterion, []).append(c)
        if results is not None:
            by_criterion.setdefault(c.criterion, []).append(results[i])
    for r in judgement.criteria:
        if r.id not in declared:
            continue
        _merge(r, declared[r.id], by_criterion.get(r.id) if results is not None else None)
    judgement.verdict = verdict_for([r.status for r in judgement.criteria])


def _merge(r: CriterionResult, checks: list[Check], results: list[dict] | None) -> None:
    if results is None:
        r.status, r.reason = "UNVERIFIED", "acceptance checks were not run (no checks.json)"
        return
    bad = [x for x in results if x["status"] in (FAILED, TIMEOUT)]
    if bad:
        r.status = "FAIL"
        r.reason = "; ".join(f"`{x['command']}` {x['reason']}" for x in bad)
        return
    missing = [x for x in results if x["status"] != PASSED]
    if missing:
        r.status = "UNVERIFIED"
        r.reason = "; ".join(f"`{x['command']}`: {x['reason']}" for x in missing)
        return
    if all(c.on_pass == "pass" for c in checks):
        r.status = "PASS"
        r.reason = "; ".join(f"`{x['command']}` passed" for x in results)
        return
    prefix = "commands passed; "
    if r.reason == "no judge configured":
        r.reason = prefix + "the remaining clause needs a judge"
    elif not r.reason.startswith(prefix):
        r.reason = prefix + r.reason
