"""Offline run provenance v1. Integrity against caller-held context, not authentication.

Never discovers credentials, invokes an agent, or executes produced work. References
in manifests are compared with caller-selected paths, never followed.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

VERSION = 1
ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 4 * 1024 * 1024
MAX_FILES = 20000
MAX_JSON_DEPTH = 64
MANIFEST = "run-provenance.json"
HASH = re.compile(r"[0-9a-f]{64}")
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
PRUNED = {
    ".git", "runs", "results", "research", "transcripts", "secrets", "credentials",
    "node_modules", "__pycache__", ".pytest_cache",
    ".venv", "venv", "env", "envs", "bin", "obj", "dist", "build",
}
SUFFIXES = {".py", ".ps1", ".sh", ".md", ".json", ".yaml", ".yml", ".txt"}
ROOT_INPUTS = (
    ".github/solution-profile.yaml", ".github/copilot-instructions.md",
    ".github/plugin/marketplace.json", "AGENTS.md",
)
# Authoritative component trees cannot double as output trees. Dedicated siblings
# (e.g. eval/custom-output or eval/pipeline/runs) remain supported.
SOURCE_COMPONENTS = (
    ".github", "plugins", "scripts", "eval/deepeval", "eval/skills",
    "eval/pipeline/custom-eval", "eval/pipeline/swe-bench-subset",
    "eval/pipeline/trajectory", "eval/pipeline/tests", "eval/pipeline/references",
)
STATUSES = {
    "resolved": "resolved", "partial": "partial", "failed": "failed",
    "unverified": "unverified", "skipped": "skipped",
    "setup_error": "setup_error_count", "blocked_approval": "blocked_approval_count",
}


def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("invalid provenance identifier")
    return value


def checked_path(path: Path) -> Path:
    """Reject symlinks, Windows junctions/reparse points, traversal and special files."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError("provenance path traversal forbidden")
    for part in (path, *path.parents):
        if part.is_symlink() or (
            part.exists() and getattr(part.lstat(), "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("symlink/reparse provenance path forbidden")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise ValueError("special provenance path forbidden")
    return path


def read_bytes(path: Path) -> bytes:
    path = checked_path(path)
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("provenance input exceeds size limit")
    return data


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def identity(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode("utf-8"))


def _check_json_depth(text: str) -> None:
    """Bound container nesting before decoding; leave JSON syntax to json.loads."""
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("provenance JSON exceeds nesting limit")
        elif character in "}]":
            depth -= 1


def read_json(path: Path) -> dict:
    text = read_bytes(path).decode("utf-8-sig")
    _check_json_depth(text)
    try:
        value = json.loads(text)
    except RecursionError as exc:
        raise ValueError("provenance JSON exceeds nesting limit") from exc
    if not isinstance(value, dict):
        raise ValueError("provenance object required")
    return value


def write_json(path: Path, value: dict) -> None:
    checked_path(path)
    data = json.dumps(value, indent=2, ensure_ascii=True) + "\n"
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise ValueError("provenance output exceeds size limit")
    path.write_text(data, encoding="utf-8")


def file_hash(path: Path) -> str | None:
    checked_path(path)
    return digest(read_bytes(path)) if path.is_file() else None


def source_exclusions(
    root: Path, output_root: Path | None, output_files: tuple[Path, ...],
) -> tuple[Path, ...]:
    """Validate caller-selected exclusions without reading their contents."""
    root = checked_path(root).resolve()
    protected = [root / name for name in (*ROOT_INPUTS, *SOURCE_COMPONENTS)]
    # Direct harness modules/docs are authoritative too; JSON output files are
    # allowed here, but never within the component trees above.
    for folder in (root / "eval", root / "eval/pipeline"):
        checked_path(folder)
        if folder.is_dir():
            protected.extend(path for path in folder.iterdir()
                             if path.is_file() and path.suffix.lower() in SUFFIXES
                             and path.suffix.lower() != ".json")
    exclusions = []
    for path in ((output_root,) if output_root is not None else ()) + output_files:
        path = checked_path(path).resolve()
        if any(path == source or path in source.parents or source in path.parents
               for source in protected):
            raise ValueError("output exclusion would conceal authoritative source inputs")
        exclusions.append(path)
    if output_root is not None and exclusions[0].exists() and not exclusions[0].is_dir():
        raise ValueError("output root must be a directory")
    for path in output_files:
        if path.suffix.lower() != ".json" or path.is_dir():
            raise ValueError("result output must be a JSON file")
    return tuple(exclusions)


def source_files(
    root: Path, *, output_root: Path | None = None, output_files: tuple[Path, ...] = (),
) -> dict[str, str]:
    """Explicit source scope, including untracked source; never scan run output/home."""
    root = checked_path(root).resolve()
    exclusions = source_exclusions(root, output_root, output_files)

    def excluded(path: Path) -> bool:
        return any(path == output or output in path.parents for output in exclusions)

    def unreadable(error: OSError) -> None:
        raise error

    files = {}
    for folder in ("eval", "plugins", "scripts"):
        start = checked_path(root / folder)
        if not start.exists():
            continue
        for directory, dirs, names in os.walk(start, followlinks=False, onerror=unreadable):
            dirs[:] = sorted(d for d in dirs if not excluded(Path(directory) / d)
                             and d.lower() not in PRUNED and not d.startswith(".")
                             and not (Path(directory) / d / "pyvenv.cfg").exists())
            # Plugin metadata and repository fixture .github inputs are relevant too.
            if (not excluded(Path(directory) / ".github")
                    and (Path(directory) / ".github").is_dir()):
                dirs.append(".github")
            for child in dirs:
                checked_path(Path(directory) / child)
            for name in sorted(names):
                path = Path(directory) / name
                if excluded(path):
                    continue
                if path.suffix.lower() not in SUFFIXES or name.startswith(".env"):
                    continue
                if path.suffix.lower() == ".txt" and not name.startswith("requirements"):
                    continue
                if "transcript" in name.lower() or "credential" in name.lower():
                    continue
                if name in {"auth.json", "tokens.json", "credentials.json", "config.json",
                            "hosts.yml"}:
                    continue
                files[path.relative_to(root).as_posix()] = digest(read_bytes(path))
                if len(files) > MAX_FILES:
                    raise ValueError("provenance inventory exceeds file limit")
    for name in ROOT_INPUTS:
        value = file_hash(root / name)
        if value is not None:
            files[name] = value
    return dict(sorted(files.items()))


def harness_identity(
    root: Path, *, output_root: Path | None = None, output_files: tuple[Path, ...] = (),
) -> dict:
    files = source_files(root, output_root=output_root, output_files=output_files)
    revision = None
    dirty = None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
            timeout=10, check=False,
        )
        candidate = result.stdout.decode("ascii", errors="replace").strip()
        if result.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", candidate):
            revision = candidate
            # Only allowlisted paths; no user config, raw transcripts or diagnostics.
            result = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all",
                 "--", "eval", "plugins", "scripts", ".github", "AGENTS.md"],
                capture_output=True, timeout=10, check=False,
            )
            if result.returncode == 0 and len(result.stdout) <= MAX_BYTES:
                dirty = bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        pass  # Explicitly unavailable below, never a clean/release claim.
    return {
        "revision": revision, "revision_status": "observed" if revision else "unavailable",
        "dirty": dirty, "source_fingerprint": identity(files),
        "source_scope": "harness-source-v1", "files": files,
    }


def task_identity(root: Path, suite: str, task_id: str) -> dict:
    from grading import _canonical_baseline_files

    identifier(task_id)
    if suite == "swe-bench-subset":
        return {"dataset_manifest_sha256": file_hash(root / "eval/pipeline" / suite / "tasks.json"),
                "canonical_inputs": None, "input_status": "unavailable_task_prep"}
    folder = root / "eval/pipeline/custom-eval/tasks" / task_id
    fields = {name: file_hash(folder / filename) for name, filename in (
        ("prompt_sha256", "prompt.md"), ("acceptance_sha256", "acceptance.md"),
        ("profile_sha256", "solution-profile.yaml"), ("fixture_manifest_sha256", "inputs.json"),
    )}
    try:
        originals, _ = _canonical_baseline_files(task_id, folder.parent)
    except (OSError, ValueError, KeyError, TypeError):
        originals = None
    fields.update(canonical_inputs=originals,
                  input_status="captured" if originals is not None and all(fields.values())
                  else "unavailable_invalid_fixture")
    return fields


def build_context(root: Path, run_id: str, task_ids: list[str], *,
                  suite: str = "custom-eval", agent: str | None = None,
                  judge: str | None = None, scorer: str = "both",
                  native: str = "python", native_version: str | None = None,
                  output_root: Path | None = None,
                  output_files: tuple[Path, ...] = ()) -> dict:
    identifier(run_id)
    if suite not in {"custom-eval", "swe-bench-subset"} or scorer not in {"shell", "deepeval", "both"}:
        raise ValueError("unknown provenance suite/scorer")
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("selected tasks must be nonempty and unique")
    for task_id in task_ids:
        identifier(task_id)
    for model in (agent, judge):
        if model is not None and (not isinstance(model, str) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)):
            raise ValueError("invalid requested model identifier")
    versions = {}
    for name in ("deepeval", "PyYAML", "pytest"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "run_id": run_id, "selected_task_ids": sorted(task_ids), "suite": suite,
        "harness": harness_identity(root, output_root=output_root, output_files=output_files),
        "tasks": {t: task_identity(root, suite, t) for t in sorted(task_ids)},
        "grading_doctrine_sha256": file_hash(
            root / "plugins/agile-agents-core/skills/acceptance-grading/SKILL.md"),
        "dependency_locks": {name: file_hash(root / "eval/deepeval" / name) for name in
                             ("requirements.lock.txt", "requirements-yaml.lock.txt")},
        "toolchain": {"python": platform.python_version(), "packages": versions,
                      "native": native, "native_version": native_version,
                      "copilot_cli": None, "copilot_cli_status": "unavailable_not_invoked"},
        "models": {"requested": {"agent": agent, "judge": judge}, "observed": {},
                   "observed_status": "unavailable_no_model_calls"},
        "scorer": scorer, "scorer_contract_version": 2,
        "execution": {"mode": "dry", "admission": "blocked", "sandbox": "not_verified",
                      "approval_reference": None, "execution_ready": False},
    }


def manifest(context: dict, bindings: list[dict] | None = None) -> dict:
    return {"schema_version": VERSION, "attribution": "captured",
            "context": context, "context_sha256": identity(context),
            "result_bindings": bindings or []}


def validate_manifest(row: dict, expected: dict) -> None:
    """Expected must come from the caller, NOT from this row or its adjacent file."""
    if type(row.get("schema_version")) is not int or row["schema_version"] != VERSION:
        raise ValueError("legacy/unattributed or unknown provenance version")
    expected_hash = identity(expected)
    if row.get("attribution") != "captured" or row.get("context_sha256") != expected_hash:
        raise ValueError("provenance differs from trusted expected context")
    if row.get("context") != expected:
        raise ValueError("provenance context mismatch")


def load_expected(run_dir: Path, expected_hash: str) -> dict:
    """The hash is held by the runner from initialization, not read from the result."""
    if not isinstance(expected_hash, str) or not HASH.fullmatch(expected_hash):
        raise ValueError("trusted context digest required")
    row = read_json(run_dir / MANIFEST)
    context = row.get("context")
    if not isinstance(context, dict) or identity(context) != expected_hash:
        raise ValueError("run context changed")
    validate_manifest(row, context)
    return context


def binding(path: Path, context: dict, task_id: str | None, acceptance: Path | None = None) -> dict:
    return {
        "reference": path.name, "sha256": digest(read_bytes(path)),
        "run_id": context["run_id"], "task_id": task_id,
        "input_identity": identity(context["tasks"][task_id]) if task_id else identity(context["tasks"]),
        "acceptance_sha256": file_hash(acceptance) if acceptance else None,
    }


def result_context(
    path: Path, workspace: Path, scorer: str, judge_model: str | None = None,
) -> dict:
    """Capture before writing a fresh result; never infer exclusions from arbitrary ancestry."""
    from grading import immutable_inputs

    workspace = checked_path(workspace).resolve()
    run_dir = workspace.parent.parent
    task_id = identifier(workspace.name)
    output_files = (path, path.with_name(path.name + ".provenance.json"))
    source_exclusions(ROOT, None, output_files)
    if (run_dir / MANIFEST).exists():
        row = read_json(run_dir / MANIFEST)
        context = row.get("context", {})
        validate_manifest(row, context)
        if context.get("run_id") != run_dir.name or task_id not in context.get("tasks", {}):
            raise ValueError("result run/task differs from runner context")
        if context["tasks"][task_id] != task_identity(ROOT, context["suite"], task_id):
            raise ValueError("task inputs changed since run initialization")
    else:
        if workspace.parent.name != "ws":
            raise ValueError("standalone provenance requires the canonical run/ws/task layout")
        # A directory named 'ws' alone is not a trusted layout contract.
        immutable_inputs(workspace)
        context = build_context(ROOT, identifier(run_dir.name), [task_id],
                                scorer=scorer, judge=judge_model,
                                output_root=run_dir.parent, output_files=output_files)
    return context


def validate_result(path: Path, expected: dict, task_id: str, acceptance: Path) -> None:
    from grading import result_status, STATUS_EXIT

    identifier(task_id)
    row = read_json(path.with_name(path.name + ".provenance.json"))
    validate_manifest(row, expected)
    if expected.get("scorer_contract_version") != 2 or expected.get("execution") != {
        "mode": "dry", "admission": "blocked", "sandbox": "not_verified",
        "approval_reference": None, "execution_ready": False,
    }:
        raise ValueError("unsupported scorer/admission contract")
    if task_id not in expected["tasks"]:
        raise ValueError("task not selected")
    task = expected["tasks"][task_id]
    if task.get("input_status") != "captured":
        raise ValueError("canonical input identity unavailable")
    if file_hash(acceptance) != task["acceptance_sha256"]:
        raise ValueError("acceptance differs from trusted context")
    if row.get("result_bindings") != [binding(path, expected, task_id, acceptance)]:
        raise ValueError("result binding mismatch")
    result = read_json(path)
    status = result.get("status")
    if (not isinstance(status, str) or status not in STATUS_EXIT
            or type(result.get("schema_version")) is not int
            or result.get("schema_version") != 2
            or result_status(path, STATUS_EXIT[status], acceptance) != status):
        raise ValueError("invalid graded-result contract")


def finalize(run_dir: Path, expected: dict) -> None:
    """Bind an existing terminal summary; refuse lost tasks, stale credits or bad counts."""
    from grading import credited_status

    path = run_dir / "summary.json"
    summary = read_json(path)
    tasks = summary.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(t, dict) for t in tasks):
        raise ValueError("invalid summary tasks")
    if (sorted(t.get("id", "") for t in tasks) != expected["selected_task_ids"]
            or summary.get("run_id") != expected["run_id"] or summary.get("total") != len(tasks)):
        raise ValueError("summary run/task inventory mismatch")
    if any(t.get("status") not in STATUSES for t in tasks):
        raise ValueError("unknown task status")
    for status, count in STATUSES.items():
        if summary.get(count) != sum(t["status"] == status for t in tasks):
            raise ValueError("summary counts differ from task inventory")
    bindings = []
    for task in tasks:
        for scorer in ("shell", "deepeval"):
            result = run_dir / f"{identifier(task['id'])}.{scorer}.json"
            if result.exists():
                acceptance = ROOT / "eval/pipeline/custom-eval/tasks" / task["id"] / "acceptance.md"
                validate_result(result, expected, task["id"], acceptance)
                bindings.append(binding(result, expected, task["id"], acceptance))
        if task["status"] in {"resolved", "partial"}:
            scorer = "shell" if expected["scorer"] == "both" else expected["scorer"]
            result = run_dir / f"{task['id']}.{scorer}.json"
            acceptance = ROOT / "eval/pipeline/custom-eval/tasks" / task["id"] / "acceptance.md"
            if credited_status(result, 0 if task["status"] == "resolved" else 2,
                               acceptance, expected, task["id"]) != task["status"]:
                raise ValueError("summary attempted unbound credit")
    bindings.append(binding(path, expected, None))
    write_json(run_dir / MANIFEST, manifest(expected, bindings))


def failed_start(run_dir: Path, run_id: str, task_ids: list[str], suite: str) -> None:
    """Capture a terminal setup failure, never a partially successful context."""
    identifier(run_id)
    for task_id in task_ids:
        identifier(task_id)
    write_json(run_dir / MANIFEST, {
        "schema_version": VERSION, "attribution": "unavailable", "reason": "capture_failed",
        "run_id": run_id, "selected_task_ids": sorted(task_ids), "result_bindings": [],
    })
    summary = {
        "suite": suite, "run_id": run_id, "run_status": "setup_error", "dry_run": True,
        "total": len(task_ids), "tasks": [{"id": t, "status": "setup_error"} for t in task_ids],
        "setup_errors": ["provenance capture failed; no staging or execution"],
    }
    summary.update({field: len(task_ids) if status == "setup_error" else 0
                    for status, field in STATUSES.items()})
    write_json(run_dir / "summary.json", summary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "finish"))
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--suite", default="custom-eval")
    parser.add_argument("--agent")
    parser.add_argument("--judge")
    parser.add_argument("--scorer", default="both")
    parser.add_argument("--native", default="python")
    parser.add_argument("--native-version")
    parser.add_argument("--expected-context")
    args = parser.parse_args()
    try:
        checked_path(args.run_dir)
        if args.action == "start":
            if args.output_root is None:
                raise ValueError("explicit output root required")
            output_root = checked_path(args.output_root).resolve()
            if checked_path(args.run_dir).resolve().parent != output_root:
                raise ValueError("run directory must be directly below the output root")
            context = build_context(ROOT, args.run_id, args.task_id, suite=args.suite,
                                    agent=args.agent, judge=args.judge, scorer=args.scorer,
                                    native=args.native, native_version=args.native_version,
                                    output_root=output_root)
            write_json(args.run_dir / MANIFEST, manifest(context))
            print(identity(context))
        else:
            finalize(args.run_dir, load_expected(args.run_dir, args.expected_context))
    except (OSError, ValueError, KeyError, TypeError):
        if args.action == "start":
            try:
                failed_start(args.run_dir, args.run_id, args.task_id, args.suite)
            except (OSError, ValueError, KeyError, TypeError):
                # Unsafe/unwritable exports cannot retain even failure metadata.
                print("provenance failure metadata could not be retained", file=sys.stderr)
        print("provenance validation failed; no reproducibility/credit claim", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
