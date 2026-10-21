"""Canonical fixture verification and safe enumeration of workspace evidence."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from agile_eval import file_io

PRUNED_DIRS = {
    ".git", "bin", "obj", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", "target", ".pytest_cache", ".copilot-home", ".copilot-runs",
}
SKIP_FILES = {
    "solution-profile.yaml", "eval-inputs.json", "inputs.json", "baseline-manifest.json",
    ".npmrc", ".netrc", "auth.json", "tokens.json", "credentials", "credentials.json",
    "config.json", "hosts.yml", "id_rsa", "id_ed25519",
}
BINARY_SUFFIXES = {
    ".dll", ".exe", ".pdb", ".so", ".dylib", ".zip", ".tar", ".gz", ".png",
    ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".woff", ".woff2", ".nupkg",
}


def safe_relative(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("invalid input path")
    parts = value.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise ValueError("input path traversal is forbidden")
    return PurePosixPath(value)


def safe_file(root: Path, value: str) -> Path:
    rel = safe_relative(value)
    path = root.joinpath(*rel.parts)
    file_io.checked_path(path)
    path.resolve(strict=True).relative_to(root.resolve(strict=True))
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError("symlinked judge input is forbidden")
    if not path.is_file():
        raise ValueError("judge input is not a file")
    return path


def _canonical_baseline_files(
    task_id: str, task_root: Path | None = None,
) -> tuple[dict[str, str], dict]:
    task_root = task_root or Path(__file__).resolve().parents[2] / "pipeline" / "custom-eval" / "tasks"
    task_dir = task_root / task_id
    if task_dir.parent.resolve() != task_root.resolve() or not task_dir.is_dir():
        raise ValueError("workspace task has no canonical repository fixture origin")
    declaration_path = safe_file(task_dir, "inputs.json")
    declaration = json.loads(file_io.read_bytes(declaration_path).decode("utf-8"))
    if (not isinstance(declaration, dict) or declaration.get("version") != 1
            or not isinstance(declaration.get("inputs"), list)):
        raise ValueError("canonical fixture input declaration is invalid")
    expected = {}

    def add_file(destination: str, source: Path) -> None:
        if destination not in expected and len(expected) >= file_io.MAX_FILES:
            raise ValueError("canonical input inventory exceeds file limit")
        expected[destination] = file_io.digest(file_io.read_bytes(source))

    add_file("context/solution-profile.yaml", safe_file(task_dir, "solution-profile.yaml"))
    add_file("context/inputs.json", declaration_path)
    for entry in declaration["inputs"]:
        if not isinstance(entry, dict) or entry.get("required") is not True:
            raise ValueError("canonical fixture input entry is invalid")
        source_rel = safe_relative(entry["source"])
        source = task_dir.joinpath(*source_rel.parts)
        file_io.checked_path(source)
        source.resolve(strict=True).relative_to(task_dir.resolve(strict=True))
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
            raise ValueError("canonical fixture contains a symlink")
        destination = safe_relative(entry["destination"]).as_posix()
        if source.is_dir():
            for path in source.rglob("*"):
                file_io.checked_path(path)
                if path.is_symlink():
                    raise ValueError("canonical fixture contains a symlink")
                if path.is_file():
                    relative = path.relative_to(source).as_posix()
                    add_file(f"{destination}/{relative}", path)
        else:
            add_file(destination, source)
    return expected, declaration


def immutable_inputs(workspace: Path, baseline_dir: str | Path | None = None) -> str:
    """Validate originals against immutable repository fixtures, not workspace claims."""
    if not workspace.is_dir():
        raise ValueError("workspace does not exist")
    expected, declaration = _canonical_baseline_files(workspace.name)
    metadata_path = workspace / ".github" / "eval-inputs.json"
    if metadata_path.exists():
        raise ValueError("workspace-local baseline metadata is untrusted and unsupported")
    trusted = workspace.parent.parent / "baseline" / workspace.name
    if baseline_dir is not None and Path(baseline_dir).resolve(strict=False) != trusted.resolve(strict=False):
        raise ValueError("baseline path must be the evaluator's canonical sibling")
    if any(p.is_symlink() for p in [trusted, *trusted.parents]):
        raise ValueError("symlinked immutable input root is forbidden")
    trusted = trusted.resolve(strict=True)
    produced = workspace.resolve()
    if trusted == produced or produced in trusted.parents or trusted in produced.parents:
        raise ValueError("immutable inputs must be outside the produced workspace")
    manifest_path = safe_file(trusted, "baseline-manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version") != 2:
        raise ValueError("invalid immutable input manifest")
    if manifest.get("task_id") != workspace.name:
        raise ValueError("immutable manifest task id differs from canonical workspace origin")
    if manifest.get("provenance") != declaration.get("provenance", "synthetic benchmark fixture"):
        raise ValueError("immutable manifest provenance differs from canonical fixture")
    if not isinstance(manifest.get("files"), list) or not all(isinstance(e, dict) for e in manifest["files"]):
        raise ValueError("invalid immutable manifest files")
    files = {}
    for entry in manifest["files"]:
        rel = entry["path"]
        if rel in files:
            raise ValueError("duplicate immutable input path")
        path = safe_file(trusted, rel)
        digest = file_io.digest(path.read_bytes())
        if digest != entry["sha256"]:
            raise ValueError(f"immutable input hash mismatch: {rel}")
        files[rel] = digest
    if files != expected:
        raise ValueError("immutable input hashes do not match canonical repository fixture")
    inventory = set()
    for path in trusted.rglob("*"):
        if path.is_symlink():
            raise ValueError("symlinked immutable input is forbidden")
        if path.is_file() and path != manifest_path:
            inventory.add(path.relative_to(trusted).as_posix())
    if inventory != set(files):
        raise ValueError("immutable snapshot inventory differs from manifest")
    declared = [rel for rel in expected if not rel.startswith("context/")]
    if not declared:
        return "(canonical task has no immutable comparison inputs)"
    return (
        f"Repository-fixture originals verified at {trusted}\n"
        + "\n".join(f"- {rel} (sha256 {files[rel]})" for rel in declared)
        + "\nOriginals are comparison inputs ONLY: never grade them as produced deliverables, "
        "copy answers from them, or modify them. Use them to verify unchanged production "
        "code and render equivalence even when the produced chart was removed. This is "
        "integrity checking, not an OS access boundary; live evaluation is disabled. "
        "Do not read context/ or undeclared files. If tools or the literal criterion "
        "(including ingress hosts) cannot establish equivalence, mark UNVERIFIED with a reason."
    )


def gradable_files(workspace: Path):
    for path in sorted(workspace.rglob("*")):
        parts = path.relative_to(workspace).parts
        if not path.is_file() or path.is_symlink():
            continue
        if any(p in PRUNED_DIRS for p in parts[:-1]):
            continue
        if path.name in SKIP_FILES or path.suffix.lower() in BINARY_SUFFIXES:
            continue
        if path.name.startswith(".env") or path.suffix.lower() in {".pem", ".key", ".pfx"}:
            continue
        # Internal configuration can contain auth; .github deliverables remain visible.
        if parts[0] in {".ssh", ".aws", ".azure", ".copilot", ".config"}:
            continue
        yield safe_file(workspace, "/".join(parts))


def artifact_dump(workspace: Path) -> str:
    sections = []
    total = 0
    for path in gradable_files(workspace):
        if total >= 60000:
            sections.append("(artifact dump capped; inspect workspace for remaining files)")
            break
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if len(body) > 8000:
            body = body[:8000] + "\n...[truncated]"
        sections.append(f"### {path.relative_to(workspace).as_posix()}\n```\n{body}\n```")
        total += len(body)
    return "\n\n".join(sections) or "(no gradable files in index; inspect workspace)"
