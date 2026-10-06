"""Validate and stage one custom-eval task's declared, versioned inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


REQUIRED_PROFILE_FIELDS = (
    ("identity", "project_name"),
    ("identity", "lifecycle_stage"),
    ("documentation", "location"),
    ("backlog", "platform"),
    ("tech_stack", "primary_languages"),
    ("tech_stack", "test_discipline"),
)
CHECKS = ("lint", "typecheck", "unit_test", "integration_test", "coverage", "mutation")
DEFAULT_ENABLED = {"lint": True, "typecheck": True, "unit_test": True}
RESERVED_DESTINATIONS = {
    "solution-profile.yaml",
    ".github/solution-profile.yaml",
    ".github/eval-inputs.json",
    "inputs.json",
    "prompt.md",
    "acceptance.md",
}


class SetupError(ValueError):
    """An invalid or unsafe fixture that must stop evaluation before agent invocation."""


def _field(root: dict[str, Any], path: tuple[str, ...]) -> Any:
    node: Any = root
    for part in path:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _safe_relative(value: Any, label: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise SetupError(f"{label} must be a non-empty slash-separated relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise SetupError(f"{label} is not a safe relative path: {value!r}")
    if ":" in path.parts[0]:
        raise SetupError(f"{label} must not contain a drive-qualified path: {value!r}")
    return path


def _load_yaml(path: Path, label: str) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SetupError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise SetupError(f"{label} must be a YAML mapping")
    return value


def validate_profile(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    profile = _load_yaml(path, "solution-profile.yaml")
    missing = [
        ".".join(field)
        for field in REQUIRED_PROFILE_FIELDS
        if not _field(profile, field)
    ]
    if missing:
        raise SetupError("solution profile is missing required fields: " + ", ".join(missing))

    languages = _field(profile, ("tech_stack", "primary_languages"))
    if not isinstance(languages, list) or not all(
        isinstance(language, (str, dict)) and language for language in languages
    ):
        raise SetupError("tech_stack.primary_languages must be a non-empty list")
    discipline = _field(profile, ("tech_stack", "test_discipline"))
    if not isinstance(discipline, str) or discipline not in {"tdd", "bdd", "test-after", "none"}:
        raise SetupError("tech_stack.test_discipline must be tdd, bdd, test-after, or none")
    if _field(profile, ("backlog", "create_tasks")) is not False:
        raise SetupError("backlog.create_tasks must be false for disposable evaluation workspaces")
    if _field(profile, ("infrastructure", "deploy_verify")) != "off":
        raise SetupError('infrastructure.deploy_verify must be the string "off"')

    test_bar = _field(profile, ("quality_gates", "test_bar"))
    if not isinstance(test_bar, dict) or not isinstance(test_bar.get("enabled"), bool):
        raise SetupError("quality_gates.test_bar.enabled must be explicitly true or false")
    if not test_bar["enabled"]:
        if not isinstance(test_bar.get("skip_reason"), str) or not test_bar["skip_reason"].strip():
            raise SetupError("a disabled test bar requires a non-empty skip_reason")
        return profile, []

    resolved: list[dict[str, Any]] = []
    for check in CHECKS:
        definition = test_bar.get(check)
        if definition is None:
            enabled = DEFAULT_ENABLED.get(check, False)
            definition = {}
        elif not isinstance(definition, dict):
            raise SetupError(f"quality_gates.test_bar.{check} must be a mapping")
        else:
            enabled = definition.get("enabled", DEFAULT_ENABLED.get(check, False))
        if not isinstance(enabled, bool):
            raise SetupError(f"quality_gates.test_bar.{check}.enabled must be boolean")
        if not enabled:
            continue
        command = definition.get("command")
        if not isinstance(command, list) or not command or not all(
            isinstance(item, str) and item.strip() for item in command
        ):
            raise SetupError(
                f"enabled quality_gates.test_bar.{check} requires a non-empty argv command list"
            )
        resolved.append({"check": check, "argv": command})
    if not resolved:
        raise SetupError("an enabled test bar must resolve at least one explicit check command")
    return profile, resolved


def _reject_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise SetupError(f"fixture inputs must not contain symlinks: {path}")
    if path.is_dir():
        for root, dirs, files in os.walk(path, followlinks=False):
            root_path = Path(root)
            for name in dirs + files:
                child = root_path / name
                if child.is_symlink():
                    raise SetupError(f"fixture inputs must not contain symlinks: {child}")


def _load_inputs(task_dir: Path) -> tuple[dict[str, Any], list[tuple[Path, PurePosixPath]]]:
    declaration_path = task_dir / "inputs.json"
    if not declaration_path.is_file() or declaration_path.is_symlink():
        raise SetupError("required input declaration is missing: inputs.json")
    try:
        declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot read inputs.json: {exc}") from exc
    if not isinstance(declaration, dict) or declaration.get("version") != 1:
        raise SetupError("inputs.json must declare version 1")
    entries = declaration.get("inputs")
    if not isinstance(entries, list):
        raise SetupError("inputs.json.inputs must be a list")

    resolved: list[tuple[Path, PurePosixPath]] = []
    destinations: list[PurePosixPath] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise SetupError(f"inputs[{index}] must be a mapping")
        if entry.get("required") is not True:
            raise SetupError(f"inputs[{index}].required must be true for declared baseline inputs")
        source_rel = _safe_relative(entry.get("source"), f"inputs[{index}].source")
        destination = _safe_relative(entry.get("destination"), f"inputs[{index}].destination")
        if destination.as_posix() in RESERVED_DESTINATIONS:
            raise SetupError(f"input destination is reserved: {destination}")
        for previous in destinations:
            if destination == previous or destination in previous.parents or previous in destination.parents:
                raise SetupError(f"input destinations overlap: {previous} and {destination}")
        destinations.append(destination)

        source = task_dir.joinpath(*source_rel.parts)
        try:
            source.resolve(strict=True).relative_to(task_dir.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise SetupError(f"input source escapes the task fixture or is missing: {source_rel}") from exc
        if not source.is_file() and not source.is_dir():
            raise SetupError(f"input source is not a file or directory: {source_rel}")
        _reject_symlinks(source)
        resolved.append((source, destination))
    return declaration, resolved


def _preflight(
    task_dir: Path, workspace: Path, baseline_dir: Path
) -> dict[str, Any]:
    task_dir = task_dir.resolve(strict=True)
    profile_path = task_dir / "solution-profile.yaml"
    if not profile_path.is_file() or profile_path.is_symlink():
        raise SetupError("required solution-profile.yaml is missing or is a symlink")
    profile, checks = validate_profile(profile_path)
    declaration, inputs = _load_inputs(task_dir)

    workspace = workspace.absolute()
    baseline_dir = baseline_dir.absolute()
    if workspace == baseline_dir or workspace in baseline_dir.parents or baseline_dir in workspace.parents:
        raise SetupError("workspace and immutable baseline directories must be separate")
    if workspace.exists() or baseline_dir.exists():
        raise SetupError("workspace and immutable baseline paths must not already exist")
    for target in (workspace, baseline_dir):
        resolved_target = target.resolve(strict=False)
        if resolved_target == task_dir or task_dir in resolved_target.parents:
            raise SetupError("staging destinations must not be inside the canonical task fixture")
    return {
        "task_dir": task_dir,
        "profile_path": profile_path,
        "profile": profile,
        "checks": checks,
        "declaration": declaration,
        "inputs": inputs,
        "workspace": workspace,
        "baseline_dir": baseline_dir,
    }


def _files_under(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stage(plan: dict[str, Any]) -> dict[str, Any]:
    task_dir = plan["task_dir"]
    profile_path = plan["profile_path"]
    checks = plan["checks"]
    declaration = plan["declaration"]
    inputs = plan["inputs"]
    workspace = plan["workspace"]
    baseline_dir = plan["baseline_dir"]
    workspace.mkdir(parents=True)
    baseline_dir.mkdir(parents=True)
    baseline_context = baseline_dir / "context"
    baseline_context.mkdir()
    shutil.copy2(profile_path, workspace / "solution-profile.yaml")
    shutil.copy2(profile_path, baseline_context / "solution-profile.yaml")
    shutil.copy2(task_dir / "inputs.json", baseline_context / "inputs.json")
    (workspace / ".github").mkdir()
    shutil.copy2(profile_path, workspace / ".github" / "solution-profile.yaml")

    for source, destination in inputs:
        workspace_target = workspace.joinpath(*destination.parts)
        baseline_target = baseline_dir.joinpath(*destination.parts)
        workspace_target.parent.mkdir(parents=True, exist_ok=True)
        baseline_target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, workspace_target)
            shutil.copytree(source, baseline_target)
        else:
            shutil.copy2(source, workspace_target)
            shutil.copy2(source, baseline_target)

    hashes = []
    for file_path in _files_under(baseline_dir):
        hashes.append({
            "path": file_path.relative_to(baseline_dir).as_posix(),
            "sha256": _sha256(file_path),
        })
    baseline_manifest = {
        "version": 2,
        "task_id": task_dir.name,
        "provenance": declaration.get("provenance", "synthetic benchmark fixture"),
        "files": hashes,
    }
    (baseline_dir / "baseline-manifest.json").write_text(
        json.dumps(baseline_manifest, indent=2) + "\n", encoding="utf-8"
    )
    staged_files = [entry for entry in hashes if not entry["path"].startswith("context/")]
    return {
        "status": "prepared",
        "task_id": task_dir.name,
        "workspace": str(workspace.resolve()),
        "baseline_dir": str(baseline_dir.resolve()),
        "profile_fields_validated": [".".join(path) for path in REQUIRED_PROFILE_FIELDS],
        "resolved_checks": checks,
        "inputs": staged_files,
        "baseline_integrity": "verified against canonical repository fixtures by evaluator",
    }


def prepare(task_dir: Path, workspace: Path, baseline_dir: Path) -> dict[str, Any]:
    return _stage(_preflight(task_dir, workspace, baseline_dir))


def prepare_many(suite_root: Path, run_dir: Path, task_ids: list[str]) -> dict[str, Any]:
    if not task_ids:
        raise SetupError("at least one task id is required")
    if len(set(task_ids)) != len(task_ids):
        raise SetupError("task ids must be unique")
    plans: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    suite_root = suite_root.resolve(strict=True)
    for task_id in task_ids:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", task_id):
            errors.append({"task_id": task_id, "errors": ["task id contains unsafe path characters"]})
            continue
        task_dir = suite_root / "tasks" / task_id
        try:
            plans.append(_preflight(
                task_dir,
                run_dir / "ws" / task_id,
                run_dir / "baseline" / task_id,
            ))
        except (OSError, SetupError) as exc:
            errors.append({"task_id": task_id, "errors": [str(exc)]})
    if errors:
        return {
            "status": "setup_error",
            "tasks": [
                {"task_id": task_id, "status": "setup_error" if any(
                    error["task_id"] == task_id for error in errors
                ) else "not_prepared"}
                for task_id in task_ids
            ],
            "errors": errors,
        }

    prepared: list[dict[str, Any]] = []
    try:
        for plan in plans:
            prepared.append(_stage(plan))
    except OSError as exc:
        return {
            "status": "setup_error",
            "tasks": [{"task_id": task_id, "status": "not_prepared"} for task_id in task_ids],
            "errors": [{"task_id": plan["task_dir"].name, "errors": [str(exc)]}],
        }
    return {"status": "prepared", "tasks": prepared}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-dir", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--suite-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--task-id", action="append")
    args = parser.parse_args()
    try:
        if args.suite_root or args.run_dir or args.task_id:
            if not args.suite_root or not args.run_dir or not args.task_id:
                parser.error("--suite-root, --run-dir, and at least one --task-id are required together")
            result = prepare_many(args.suite_root, args.run_dir, args.task_id)
        else:
            if not args.task_dir or not args.workspace or not args.baseline_dir:
                parser.error("--task-dir, --workspace, and --baseline-dir are required")
            result = prepare(args.task_dir, args.workspace, args.baseline_dir)
    except (OSError, SetupError) as exc:
        result = {
            "status": "setup_error",
            "task_id": args.task_dir.name if args.task_dir else None,
            "errors": [str(exc)],
        }
        print(json.dumps(result))
        return 2
    print(json.dumps(result))
    return 0 if result["status"] == "prepared" else 2


if __name__ == "__main__":
    raise SystemExit(main())
