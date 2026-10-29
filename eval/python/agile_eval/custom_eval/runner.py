"""Run one custom-eval task live through dev-lead, in two phases around the plan gate.

    phase 1  the unchanged task prompt, non-interactive. A dev-lead that honours its
             contract stops after presenting the plan for approval.
    gate     the trace is checked for implementation begun before approval. Skipped
             gate -> status gate_skipped, phase 2 never runs.
    approve  a human approves: interactively, or with --approve (CI: an environment
             protection rule is the human gate, this flag only records it).
    phase 2  the same session resumes with the approval message.

Live runs execute an agent with every tool allowed against a staged workspace on this
host. That is not an OS sandbox (#22), so the runner refuses to start without
--unsandboxed. --dry-run stages and prints the commands without running an agent.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from agile_eval._console import use_utf8_stdio
from agile_eval.adapters.copilot_trace import parse_log_text, verify_schema
from agile_eval.custom_eval.expectations import ExpectationsError, load
from agile_eval.custom_eval.trajectory import IMPLEMENTATION_AGENTS, check_plan_gate

ROOT_AGENT = "agile-agents-core:dev-lead"
APPROVAL_MESSAGE = (
    "Plan approved. Proceed with the plan exactly as presented, through implementation "
    "and review. Do not open a pull request."
)
DEFAULT_MAX_AI_CREDITS = 300
MIN_AI_CREDITS = 30
STATE_FILE = "state.json"
DIFF_FILE = "produced.diff"
EVIDENCE_EXCLUDES = (":(exclude,glob)**/bin/**", ":(exclude,glob)**/obj/**",
                     ":(exclude,glob)**/node_modules/**", ":(exclude,glob)**/.venv/**")
# Defence in depth only -- see capture_diff.
_SAFE_GIT = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")


class SetupError(RuntimeError):
    """Staging or environment problem; never an agent result."""


@dataclass(frozen=True)
class Paths:
    run: Path

    @property
    def workspace(self) -> Path:
        return self.run / "workspace"

    @property
    def copilot_home(self) -> Path:
        return self.run / ".copilot-home"

    def log(self, phase: int) -> Path:
        return self.run / f"phase{phase}.jsonl"

    @property
    def state(self) -> Path:
        return self.run / STATE_FILE

    @property
    def diff(self) -> Path:
        return self.run / DIFF_FILE


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_tasks_root() -> Path:
    return repo_root() / "eval" / "pipeline" / "custom-eval" / "tasks"


def resolve_task(tasks_root: Path, name: str) -> Path:
    matches = sorted(p for p in tasks_root.iterdir() if p.is_dir()
                     and (p.name == name or p.name.startswith(f"{name}-")))
    if len(matches) != 1:
        raise SetupError(f"task {name!r} matches {len(matches)} task folders")
    return matches[0]


def plugin_dirs(root: Path) -> list[Path]:
    dirs = sorted(p for p in (root / "plugins").glob("agile-agents-*")
                  if (p / ".github" / "plugin" / "plugin.json").is_file())
    if not dirs:
        raise SetupError("no plugins found under plugins/")
    return dirs


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SetupError(f"git {args[0]} failed in staged workspace")
    return proc.stdout.strip()


def stage(task_dir: Path, paths: Paths) -> str:
    """Copy declared inputs and the task profile into a fresh git repo; return baseline."""
    if paths.run.exists() and any(paths.run.iterdir()):
        raise SetupError("run directory is not empty; choose a fresh --out")
    manifest = json.loads((task_dir / "inputs.json").read_text(encoding="utf-8"))
    ws = paths.workspace
    ws.mkdir(parents=True)
    task_root = task_dir.resolve()
    for item in manifest.get("inputs", []):
        src = (task_dir / item["source"]).resolve()
        dest = (ws / item["destination"]).resolve()
        if task_root not in src.parents or ws.resolve() not in dest.parents:
            raise SetupError("inputs.json path escapes the task or workspace")
        if not src.exists():
            if item.get("required", True):
                raise SetupError(f"required input missing: {item['source']}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dest)
        else:
            shutil.copy2(src, dest)
    profile = ws / ".github" / "solution-profile.yaml"
    profile.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(task_dir / "solution-profile.yaml", profile)
    _git(ws, "init", "-q", "-b", "main")
    _git(ws, "config", "user.name", "custom-eval")
    _git(ws, "config", "user.email", "custom-eval@invalid")
    _git(ws, "config", "commit.gpgsign", "false")
    _git(ws, "add", "-A")
    _git(ws, "commit", "-q", "-m", "baseline")
    return _git(ws, "rev-parse", "HEAD")


def capture_diff(paths: Paths, baseline: str) -> None:
    """Write everything the run changed since the baseline, untracked files included.

    The agent controls workspace/.git/config and .gitattributes, so git here can run
    agent-chosen programs (filters, fsmonitor). That is acceptable only because this
    runs in the agent's own trust zone, right after the agent ran unsandboxed. The
    scorer reads the captured file and never runs git in the workspace.
    """
    ws = paths.workspace
    subprocess.run(["git", *_SAFE_GIT, "add", "-A", "-N"], cwd=ws, capture_output=True,
                   check=False)
    proc = subprocess.run(
        ["git", *_SAFE_GIT, "diff", "--no-color", "--no-ext-diff", "--no-textconv", baseline,
         "--", ".", *EVIDENCE_EXCLUDES],
        cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise SetupError("cannot diff the produced workspace against its baseline")
    paths.diff.write_text(proc.stdout, encoding="utf-8", newline="\n")


def copilot_command(copilot: str, prompt: str, session_id: str, max_credits: int,
                    plugins: list[Path]) -> list[str]:
    cmd = [copilot, "--agent", ROOT_AGENT]
    for p in plugins:
        cmd += ["--plugin-dir", str(p)]
    return cmd + [
        "-p", prompt, "--output-format", "json", "--allow-all-tools",
        "--session-id", session_id, "--no-ask-user",
        "--max-ai-credits", str(max_credits), "--no-auto-update",
    ]


def run_phase(cmd: list[str], paths: Paths, phase: int, timeout: int) -> int:
    token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip()
    if not token:
        raise SetupError("COPILOT_GITHUB_TOKEN is not set")
    paths.copilot_home.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, COPILOT_HOME=str(paths.copilot_home), COPILOT_AUTO_UPDATE="false")
    with paths.log(phase).open("w", encoding="utf-8", newline="\n") as out:
        try:
            proc = subprocess.run(cmd, cwd=paths.workspace, env=env, stdout=out,
                                  stderr=subprocess.DEVNULL, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            return -1
    return proc.returncode


def write_state(paths: Paths, state: dict) -> None:
    paths.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError("no readable state.json in the run directory; run phase 1 first") from None


def _approve_interactively(summary: str | None) -> bool:
    if not sys.stdin.isatty():
        return False
    print("\n--- dev-lead's last message (the plan presented for approval) ---")
    print(summary or "(no final message captured)")
    return input("\nApprove this plan and resume? [y/N] ").strip().lower() in {"y", "yes"}


def phase1(args: argparse.Namespace, task_dir: Path, paths: Paths) -> dict:
    exp = load(task_dir)
    baseline = stage(task_dir, paths)
    session_id = str(uuid.uuid4())
    prompt = (task_dir / "prompt.md").read_text(encoding="utf-8")
    cmd = copilot_command(args.copilot, prompt, session_id, args.max_ai_credits,
                          plugin_dirs(repo_root()))
    state = {"schema": 1, "task": task_dir.name, "session_id": session_id,
             "baseline": baseline, "status": "staged", "phases": {}}
    if args.dry_run:
        state["status"] = "dry_run"
        state["command"] = [c if c != prompt else "<prompt.md>" for c in cmd]
        write_state(paths, state)
        return state
    code = run_phase(cmd, paths, 1, args.timeout)
    trace = parse_log_text(paths.log(1).read_text(encoding="utf-8"))
    problems = verify_schema(trace, require_skills_offered=False)
    state["phases"]["1"] = {"exit_code": code, "schema_errors": problems}
    if code == -1 or problems:
        state["status"] = "setup_error"
    elif exp.plan_gate != "required":
        state["status"] = "complete"
    else:
        gate = check_plan_gate(trace, frozenset(exp.implementation_agents or IMPLEMENTATION_AGENTS))
        state["gate"] = {"honoured": gate.honoured, "violations": list(gate.violations)}
        state["status"] = "awaiting_approval" if gate.honoured else "gate_skipped"
    state["plan_message"] = trace.final_message
    _capture(paths, state)
    write_state(paths, state)
    return state


def _capture(paths: Paths, state: dict) -> None:
    try:
        capture_diff(paths, state["baseline"])
    except SetupError as exc:
        state["status"] = "setup_error"
        state.setdefault("errors", []).append(str(exc))


def phase2(args: argparse.Namespace, paths: Paths) -> dict:
    state = read_state(paths)
    if state.get("status") != "awaiting_approval":
        raise SetupError(f"phase 2 needs status awaiting_approval, found {state.get('status')}")
    if not (args.approve or _approve_interactively(state.get("plan_message"))):
        state["status"] = "blocked_approval"
        write_state(paths, state)
        return state
    cmd = copilot_command(args.copilot, APPROVAL_MESSAGE, state["session_id"],
                          args.max_ai_credits, plugin_dirs(repo_root()))
    state["approved"] = True
    code = run_phase(cmd, paths, 2, args.timeout)
    trace = parse_log_text(paths.log(2).read_text(encoding="utf-8"))
    problems = verify_schema(trace, require_skills_offered=False)
    state["phases"]["2"] = {"exit_code": code, "schema_errors": problems}
    state["status"] = "setup_error" if code == -1 or problems else "complete"
    _capture(paths, state)
    write_state(paths, state)
    return state


def main(argv: list[str] | None = None) -> int:
    use_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", help="task folder name or prefix, e.g. task-02")
    ap.add_argument("--out", type=Path, required=True, help="run directory for this task")
    ap.add_argument("--phase", choices=("1", "2", "all"), default="all")
    ap.add_argument("--approve", action="store_true",
                    help="record human plan approval obtained outside this process (CI)")
    ap.add_argument("--unsandboxed", action="store_true",
                    help="acknowledge the agent runs with all tools on this host (#22)")
    ap.add_argument("--dry-run", action="store_true", help="stage and print; run no agent")
    ap.add_argument("--max-ai-credits", type=int, default=DEFAULT_MAX_AI_CREDITS)
    ap.add_argument("--timeout", type=int, default=3600, help="seconds per phase")
    ap.add_argument("--copilot", default=shutil.which("copilot") or "copilot")
    ap.add_argument("--tasks-root", type=Path, default=default_tasks_root())
    args = ap.parse_args(argv)
    if args.max_ai_credits < MIN_AI_CREDITS:
        ap.error(f"--max-ai-credits must be at least {MIN_AI_CREDITS}")
    if not args.dry_run and not args.unsandboxed:
        ap.error("live runs are not OS-sandboxed (#22); pass --unsandboxed to proceed")
    if args.dry_run and args.phase == "2":
        ap.error("--dry-run applies to phase 1 only")
    paths = Paths(args.out)
    try:
        if args.phase in ("1", "all"):
            task_dir = resolve_task(args.tasks_root, args.task)
            state = phase1(args, task_dir, paths)
            print(f"phase 1: {state['status']}")
            if args.phase == "1" or state["status"] != "awaiting_approval":
                return 0 if state["status"] != "setup_error" else 4
        state = phase2(args, paths)
        print(f"phase 2: {state['status']}")
        return 4 if state["status"] == "setup_error" else 0
    except (SetupError, ExpectationsError) as exc:
        print(f"SETUP ERROR: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
