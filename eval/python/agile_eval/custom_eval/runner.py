"""Run one custom-eval task live through dev-lead, in two phases around the plan gate.

    phase 1  the unchanged task prompt, non-interactive. A dev-lead that honours its
             contract stops after presenting the plan for approval.
    gate     implementation before approval -> gate_skipped. Without a verified
             approval request -> blocked_approval; phase 2 never runs.
    approve  EVAL-ONLY simulated plan approval. An LLM grades the plan against
             custom-eval/plan-approval.md (+ the task's plan_approval criteria) and
             approves only if all pass, else plan_rejected. `--phase approve` runs
             just that decision and no agent, so CI can give it judge credentials
             without the Copilot token. `--phase 2` needs the recorded decision.
    phase 2  the same pending tool request receives the recorded approval.
    checks   once a run is complete (or skipped the gate), the task's declared build /
             test / render commands run in the workspace -> checks.json. `--phase verify`
             re-runs only these against an existing run.

Live runs execute an agent with every tool allowed against a staged workspace on this
host. That is not an OS sandbox (#22), so the runner refuses to start without
--unsandboxed. --dry-run stages and prints the commands without running an agent.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

from agile_eval._console import use_utf8_stdio
from agile_eval.adapters.copilot_trace import ExternalToolRequest, parse_log_text, verify_schema
from agile_eval.custom_eval import plan_approval
from agile_eval.custom_eval.checks import run_checks
from agile_eval.custom_eval.expectations import Expectations, ExpectationsError, load
from agile_eval.custom_eval.judges import JudgeError
from agile_eval.custom_eval.trajectory import (
    IMPLEMENTATION_AGENTS, approval_response_recorded, check_plan_gate,
)

ROOT_AGENT = "agile-agents-core:dev-lead"
DEFAULT_MAX_AI_CREDITS = 300
MIN_AI_CREDITS = 30
STATE_FILE = "state.json"
DIFF_FILE = "produced.diff"
PHASE1_CHANGES_FILE = "phase1-changes.json"
# Run statuses whose workspace holds a finished change the acceptance checks can test.
VERIFIABLE = ("complete", "gate_skipped")
EVIDENCE_EXCLUDES = (":(exclude,glob)**/bin/**", ":(exclude,glob)**/obj/**",
                     ":(exclude,glob)**/node_modules/**", ":(exclude,glob)**/.venv/**",
                     ":(exclude,glob)**/__pycache__/*.pyc",
                     ":(exclude,glob)**/.pytest_cache/**",
                     ":(exclude,glob)**/.mypy_cache/**", ":(exclude,glob)**/.ruff_cache/**")
PHASE1_EXCLUDES = (*EVIDENCE_EXCLUDES, ":(exclude,glob).copilot-runs/**",
                   ":(exclude,top).github/solution-profile.yaml")
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

    @property
    def home(self) -> Path:
        # CI and report readers already exclude this runtime-state tree.
        return self.copilot_home / "home"

    def log(self, phase: int) -> Path:
        return self.run / f"phase{phase}.jsonl"

    @property
    def state(self) -> Path:
        return self.run / STATE_FILE

    @property
    def diff(self) -> Path:
        return self.run / DIFF_FILE

    @property
    def phase1_changes(self) -> Path:
        return self.run / PHASE1_CHANGES_FILE


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
    """Only core is the harness; sibling or installed plugins are never fallback inputs."""
    core = root / "plugins" / "agile-agents-core"
    if not (core / ".github/plugin/plugin.json").is_file():
        raise SetupError("core plugin missing; no plugin fallback")
    return [core]


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SetupError(f"git {args[0]} failed in staged workspace")
    return proc.stdout.strip()


def stage(task_dir: Path, paths: Paths) -> str:
    """Copy declared inputs and the task profile into a fresh git repo; return baseline."""
    if paths.run.exists() and any(paths.run.iterdir()):
        raise SetupError("run directory is not empty; choose a fresh --out")
    try:
        manifest = json.loads((task_dir / "inputs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError("no readable inputs.json") from None
    if (not isinstance(manifest, dict) or type(manifest.get("version")) is not int
            or manifest["version"] != 1 or not isinstance(manifest.get("inputs"), list)
            or set(manifest) - {"version", "provenance", "inputs"}):
        raise SetupError("inputs.json requires version 1 and an inputs list; unknown fields forbidden")
    ws = paths.workspace
    ws.mkdir(parents=True)
    task_root = task_dir.resolve()
    for item in manifest["inputs"]:
        if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) and item[key] for key in ("source", "destination")
        ) or set(item) - {"source", "destination", "required"}:
            raise SetupError("input requires source and destination")
        declared_src = task_dir / item["source"]
        src = declared_src.resolve()
        dest = (ws / item["destination"]).resolve()
        if (Path(item["source"]).is_absolute() or Path(item["destination"]).is_absolute()
                or task_root not in src.parents or ws.resolve() not in dest.parents):
            raise SetupError("inputs.json path escapes the task or workspace")
        if (any(p.is_symlink() for p in (declared_src, *declared_src.parents)
                if p != task_dir and task_dir in p.parents)
                or any(p.is_symlink() for p in src.rglob("*"))):
            raise SetupError("input symlinks are not allowed")
        relative = dest.relative_to(ws.resolve())
        targets = [relative]
        if src.is_dir():
            targets += [relative / p.relative_to(src) for p in src.rglob("*")]
        if any(part in {".git", ".copilot", ".claude", "plugins", "agents"}
               for target in targets for part in target.parts):
            raise SetupError("inputs cannot inject plugins, agents or runtime configuration")
        if Path(".github/solution-profile.yaml") in targets:
            raise SetupError("the task profile is staged separately")
        if not src.exists():
            if item.get("required", True):
                raise SetupError(f"required input missing: {item['source']}")
            continue
        if dest.exists():
            raise SetupError(f"duplicate input destination: {item['destination']}")
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
    added = subprocess.run(["git", *_SAFE_GIT, "add", "-A", "-N"], cwd=ws,
                           capture_output=True, check=False)
    if added.returncode != 0:
        raise SetupError("cannot include untracked files in the workspace evidence")
    proc = subprocess.run(
        ["git", *_SAFE_GIT, "diff", "--no-color", "--no-ext-diff", "--no-textconv", baseline,
         "--", ".", *EVIDENCE_EXCLUDES],
        cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )
    if proc.returncode != 0:
        raise SetupError("cannot diff the produced workspace against its baseline")
    try:
        paths.diff.write_text(proc.stdout, encoding="utf-8", newline="\n")
    except OSError:
        raise SetupError("cannot record the produced workspace diff") from None


def capture_phase1_changes(paths: Paths, baseline: str) -> tuple[str, ...]:
    """Record persistent pre-approval changes apart from telemetry and profile setup."""
    changed: set[str] = set()
    # A staged change can be hidden by restoring the working copy to the baseline.
    for options in ((), ("--cached",)):
        proc = subprocess.run(
            ["git", *_SAFE_GIT, "diff", *options, "--name-only", "-z", "--no-ext-diff",
             "--no-textconv", baseline, "--", ".", *PHASE1_EXCLUDES],
            cwd=paths.workspace, capture_output=True, check=False,
        )
        if proc.returncode != 0 or (proc.stdout and not proc.stdout.endswith(b"\0")):
            raise SetupError("cannot capture pre-approval workspace changes")
        changed.update(proc.stdout.decode("utf-8", errors="surrogateescape").split("\0")[:-1])
    changes = tuple(sorted(changed))
    try:
        paths.phase1_changes.write_text(
            json.dumps({"schema": 1, "paths": changes}, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    except OSError:
        raise SetupError("cannot record pre-approval workspace changes") from None
    return changes


def _snapshot_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate workspace snapshot field")
        result[key] = value
    return result


def read_phase1_changes(paths: Paths) -> tuple[str, ...] | None:
    """Read the recorded snapshot, or leave the gate unverified when it is invalid."""
    try:
        data = json.loads(paths.phase1_changes.read_text(encoding="utf-8"),
                          object_pairs_hook=_snapshot_object)
    except (OSError, ValueError, RecursionError):
        return None
    if (not isinstance(data, dict) or set(data) != {"schema", "paths"}
            or type(data.get("schema")) is not int
            or data["schema"] != 1 or not isinstance(data.get("paths"), list)
            or any(not isinstance(path, str) or not path or "\0" in path for path in data["paths"])
            or len(set(data["paths"])) != len(data["paths"])):
        return None
    return tuple(data["paths"])


def copilot_command(copilot: str, prompt: str, session_id: str, max_credits: int,
                    plugins: list[Path], *, phase: int = 1, timeout: int = 3600,
                    request: ExternalToolRequest | None = None) -> list[str]:
    bridge = repo_root() / "eval" / "pipeline" / "copilot_approval_transport.mjs"
    cmd = [shutil.which("node") or "node", str(bridge), "--phase", str(phase),
           "--copilot", copilot, "--agent", ROOT_AGENT, "--session-id", session_id,
           "--max-ai-credits", str(max_credits), "--timeout", str(timeout)]
    for p in plugins:
        cmd += ["--plugin-dir", str(p)]
    if phase == 1:
        return cmd + ["--prompt", prompt]
    if phase == 2 and request is not None:
        return cmd + ["--request-id", request.request_id, "--tool-call-id", request.call_id,
                      "--request-arguments", json.dumps(request.arguments, ensure_ascii=False)]
    raise SetupError("phase 2 needs the verified pending approval request")


def run_phase(cmd: list[str], paths: Paths, phase: int, timeout: int) -> int:
    if not any(os.environ.get(name, "").strip()
               for name in ("COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN")):
        raise SetupError("COPILOT_GITHUB_TOKEN or GITHUB_TOKEN must be set")
    paths.home.mkdir(parents=True, exist_ok=True)
    allowed = ("PATH", "SystemRoot", "WINDIR", "TMPDIR", "TEMP", "TMP",
               "COPILOT_GITHUB_TOKEN", "GITHUB_TOKEN", "COPILOT_CLI_VERSION",
               "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "SSL_CERT_FILE")
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    home = paths.home.resolve()
    env.update(HOME=str(home), USERPROFILE=str(home),
               COPILOT_HOME=str(paths.copilot_home.resolve()),
               XDG_CONFIG_HOME=str(home / ".config"), XDG_CACHE_HOME=str(home / ".cache"),
               XDG_STATE_HOME=str(home / ".state"), COPILOT_AUTO_UPDATE="false")
    # The command now launches Node; capability checks still target the actual CLI.
    copilot = cmd[cmd.index("--copilot") + 1] if "--copilot" in cmd else cmd[0]
    try:
        help_result = subprocess.run(
            [copilot, "--no-auto-update", "--help"], cwd=paths.workspace, env=env,
            capture_output=True, text=True, timeout=20, check=True)
        flags = set(re.findall(r"--[a-z][a-z-]*", help_result.stdout))
        if not {"--sync-session", "--secret-env-vars"} <= flags:
            raise SetupError("CLI must support --sync-session and --secret-env-vars")
    except (OSError, subprocess.SubprocessError) as exc:
        raise SetupError(f"cannot verify CLI history-sync opt-out: {exc}") from None
    (paths.run / f"phase{phase}-cli-help.txt").write_text(help_result.stdout, encoding="utf-8")
    with paths.log(phase).open("w", encoding="utf-8", newline="\n") as out:
        try:
            proc = subprocess.run(cmd, cwd=paths.workspace, env=env, stdout=out,
                                  stderr=subprocess.DEVNULL, timeout=timeout + 10, check=False)
        except subprocess.TimeoutExpired:
            return -1
        except OSError:
            raise SetupError("cannot start the Copilot transport; check Node.js and the CLI") from None
    return proc.returncode


def write_state(paths: Paths, state: dict) -> None:
    paths.state.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")


def read_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise SetupError("no readable state.json in the run directory; run phase 1 first") from None


def phase1(args: argparse.Namespace, task_dir: Path, paths: Paths) -> dict:
    exp = load(task_dir)
    baseline = stage(task_dir, paths)
    session_id = str(uuid.uuid4())
    prompt = (task_dir / "prompt.md").read_text(encoding="utf-8")
    cmd = copilot_command(args.copilot, prompt, session_id, args.max_ai_credits,
                          plugin_dirs(repo_root()), timeout=args.timeout)
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
    if code != 0 or problems:
        state["status"] = "setup_error"
    _capture(paths, state)
    if state["status"] != "setup_error":
        try:
            changes = capture_phase1_changes(paths, baseline)
        except SetupError as exc:
            state["status"] = "setup_error"
            state.setdefault("errors", []).append(str(exc))
        else:
            if exp.plan_gate != "required":
                if trace.external_requests:
                    state["status"] = "blocked_approval"
                    state.setdefault("errors", []).append("a user-input request was not approved")
                else:
                    state["status"] = "complete"
            else:
                gate = check_plan_gate(
                    trace, frozenset(exp.implementation_agents or IMPLEMENTATION_AGENTS),
                    phase1_changes=changes,
                )
                state["gate"] = {"honoured": gate.honoured, "violations": list(gate.violations),
                                 "reason": gate.reason}
                if gate.honoured is False:
                    state["status"] = "gate_skipped"
                elif gate.request is not None and gate.request.session_id == session_id:
                    state["status"] = "awaiting_approval"
                    state["plan_message"] = plan_approval.visible_plan(gate.request)
                else:
                    state["status"] = "blocked_approval"
                    if gate.request is not None:
                        state["gate"] = {"honoured": None, "violations": [],
                                         "reason": "approval request belongs to a different session"}
    state.setdefault("plan_message", trace.final_message)
    # The agent could reach the run directory: never let it pre-seed an approval.
    (paths.run / plan_approval.APPROVAL_FILE).unlink(missing_ok=True)
    _verify(exp, paths, state)
    write_state(paths, state)
    return state


def _capture(paths: Paths, state: dict) -> None:
    try:
        capture_diff(paths, state["baseline"])
    except SetupError as exc:
        state["status"] = "setup_error"
        state.setdefault("errors", []).append(str(exc))


def _verify(exp: Expectations, paths: Paths, state: dict) -> None:
    """Run the acceptance checks once the agent is done. After the diff capture, so
    build output never reaches the evidence. Failures grade the run, not the harness."""
    if state["status"] not in VERIFIABLE or not exp.checks:
        return
    try:
        report = run_checks(exp, paths.workspace, paths.run)
    except OSError:
        state.setdefault("errors", []).append("acceptance checks could not record results")
        return
    statuses = [r["status"] for r in report["results"]]
    state["checks"] = {s: statuses.count(s) for s in sorted(set(statuses))}


def verify(args: argparse.Namespace, paths: Paths) -> dict:
    """Re-run only the acceptance checks against a finished run (e.g. after installing a tool)."""
    state = read_state(paths)
    if state.get("status") not in VERIFIABLE:
        raise SetupError(f"verify needs status {' or '.join(VERIFIABLE)}, "
                         f"found {state.get('status')}")
    exp = load(resolve_task(args.tasks_root, state["task"]))
    _verify(exp, paths, state)
    write_state(paths, state)
    return state


def _require_verified_gate(paths: Paths, exp: Expectations,
                           session_id: str | None = None) -> ExternalToolRequest:
    try:
        trace = parse_log_text(paths.log(1).read_text(encoding="utf-8"))
    except OSError:
        raise SetupError("plan approval needs a readable phase1.jsonl") from None
    if verify_schema(trace, require_skills_offered=False):
        raise SetupError("phase 1 trace cannot verify the plan approval gate")
    gate = check_plan_gate(
        trace, frozenset(exp.implementation_agents or IMPLEMENTATION_AGENTS),
        phase1_changes=read_phase1_changes(paths),
    )
    if gate.honoured is not True or gate.request is None:
        raise SetupError(f"plan approval gate not verified: {gate.reason}")
    if not isinstance(session_id, str) or not session_id.strip():
        raise SetupError("plan approval needs the original session ID")
    if gate.request.session_id != session_id:
        raise SetupError("plan approval request belongs to a different session")
    return gate.request


def _requirement(task_dir: Path) -> str:
    try:
        return (task_dir / "prompt.md").read_text(encoding="utf-8")
    except OSError:
        raise SetupError(f"cannot read {task_dir.name}/prompt.md") from None


def approve(args: argparse.Namespace, paths: Paths) -> dict:
    """Simulated (LLM) plan approval. Runs no agent; records plan-approval.json."""
    state = read_state(paths)
    if state.get("status") != "awaiting_approval":
        raise SetupError(f"plan approval needs status awaiting_approval, found {state.get('status')}")
    task_dir = resolve_task(args.tasks_root, state["task"])
    exp = load(task_dir)
    request = _require_verified_gate(paths, exp, state.get("session_id"))
    criteria = plan_approval.load_rubric(args.tasks_root.parent / plan_approval.RUBRIC_FILE,
                                         exp.plan_approval)
    requirement = _requirement(task_dir)
    decision = plan_approval.decide(requirement, criteria, plan_approval.visible_plan(request))
    binding = plan_approval.request_binding(request, requirement, criteria)
    plan_approval.write(paths.run, decision, binding=binding)
    state["plan_approval"] = {"approver": decision.approver, "approved": decision.approved}
    if not decision.approved:
        state["status"] = "plan_rejected"
    write_state(paths, state)
    return state


def _rejected(paths: Paths, state: dict) -> dict:
    state["status"] = "plan_rejected"
    state["plan_approval"] = {"approver": plan_approval.SIMULATED, "approved": False}
    write_state(paths, state)
    return state


def phase2(args: argparse.Namespace, paths: Paths) -> dict:
    state = read_state(paths)
    if state.get("status") not in ("awaiting_approval", "plan_rejected"):
        raise SetupError(f"phase 2 needs status awaiting_approval, found {state.get('status')}")
    task_dir = resolve_task(args.tasks_root, state["task"])
    exp = load(task_dir)
    criteria = plan_approval.load_rubric(args.tasks_root.parent / plan_approval.RUBRIC_FILE,
                                         exp.plan_approval)
    recorded = plan_approval.read(paths.run, criteria)
    if recorded is None:
        raise SetupError(f"phase 2 needs a valid {plan_approval.APPROVAL_FILE}; "
                         "run --phase approve first")
    request = _require_verified_gate(paths, exp, state.get("session_id"))
    binding = plan_approval.request_binding(request, _requirement(task_dir), criteria)
    if plan_approval.read(paths.run, criteria, binding=binding) is None:
        raise SetupError("recorded plan decision does not match the pending request")
    if not recorded["approved"]:
        return _rejected(paths, state)
    if state["status"] == "plan_rejected":
        raise SetupError("recorded plan decision conflicts with the run state")
    cmd = copilot_command(args.copilot, "", state["session_id"], args.max_ai_credits,
                          plugin_dirs(repo_root()), phase=2, timeout=args.timeout, request=request)
    state["approved"] = True
    state["approved_by"] = plan_approval.SIMULATED
    code = run_phase(cmd, paths, 2, args.timeout)
    phase2_text = paths.log(2).read_text(encoding="utf-8")
    trace = parse_log_text(phase2_text)
    combined = parse_log_text(paths.log(1).read_text(encoding="utf-8") + "\n" + phase2_text)
    problems = verify_schema(combined, require_skills_offered=False)
    if not approval_response_recorded(request, trace, combined):
        problems.append("the original approval request did not complete with the approved choice")
    state["phases"]["2"] = {"exit_code": code, "schema_errors": problems}
    if code != 0 or problems:
        state["status"] = "setup_error"
    elif trace.external_requests:
        state["status"] = "blocked_approval"
        state.setdefault("errors", []).append("a further user-input request was not approved")
    else:
        state["status"] = "complete"
    _capture(paths, state)
    _verify(exp, paths, state)
    write_state(paths, state)
    return state


def main(argv: list[str] | None = None) -> int:
    use_utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("task", help="task folder name or prefix, e.g. task-02")
    ap.add_argument("--out", type=Path, required=True, help="run directory for this task")
    ap.add_argument("--phase", choices=("1", "approve", "2", "all", "verify"), default="all",
                    help="approve runs only the simulated LLM plan approval; "
                         "verify re-runs only the acceptance checks of a finished run")
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
    if args.timeout < 1:
        ap.error("--timeout must be positive")
    if not args.dry_run and not args.unsandboxed and args.phase != "approve":
        ap.error("live runs are not OS-sandboxed (#22); pass --unsandboxed to proceed")
    if args.dry_run and args.phase in ("approve", "2", "verify"):
        ap.error("--dry-run applies to phase 1 only")
    paths = Paths(args.out)
    try:
        if args.phase == "verify":
            state = verify(args, paths)
            print(f"verify: {state.get('checks', {})}")
            return 0
        if args.phase == "approve":
            state = approve(args, paths)
            print(f"plan approval ({plan_approval.SIMULATED}): {state['status']}")
            return 0
        if args.phase in ("1", "all"):
            task_dir = resolve_task(args.tasks_root, args.task)
            state = phase1(args, task_dir, paths)
            print(f"phase 1: {state['status']}")
            if args.phase == "1" or state["status"] != "awaiting_approval":
                return 0 if state["status"] != "setup_error" else 4
            state = approve(args, paths)
            print(f"plan approval ({plan_approval.SIMULATED}): {state['status']}")
        state = phase2(args, paths)
        print(f"phase 2: {state['status']}")
        return 4 if state["status"] == "setup_error" else 0
    except (SetupError, ExpectationsError, JudgeError) as exc:
        print(f"SETUP ERROR: {exc}")
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
