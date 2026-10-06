"""Shared, offline outcome contract. No model or DeepEval dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePosixPath


class Verdict(str, Enum):
    RESOLVED = "RESOLVED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"
    SETUP_ERROR = "SETUP_ERROR"


VERDICT_SCORE = {
    Verdict.RESOLVED: 1.0, Verdict.PARTIAL: 0.5, Verdict.FAILED: 0.0,
    Verdict.UNVERIFIED: 0.0, Verdict.SETUP_ERROR: 0.0,
}
VERDICT_EXIT = {
    Verdict.RESOLVED: 0, Verdict.FAILED: 1, Verdict.PARTIAL: 2,
    Verdict.UNVERIFIED: 3, Verdict.SETUP_ERROR: 4,
}
STATUS_EXIT = {v.value.lower(): code for v, code in VERDICT_EXIT.items()}
CRITERION = re.compile(r"^\s*(\d+)\.\s+(PASS|FAIL|UNVERIFIED)\s+-\s+(\S.*)$", re.I)
VERDICT = re.compile(r"^\s*VERDICT:\s*(RESOLVED|PARTIAL|FAILED|UNVERIFIED)\s*$", re.I)
NUMBERED = re.compile(r"^\s*(\d+)\.\s+\S")


@dataclass
class JudgeResult:
    verdict: Verdict
    response: str
    claimed_verdict: str | None = None
    criteria: list[dict] = field(default_factory=list)
    expected_criteria: int = 0
    complete: bool = False
    reasons: list[str] = field(default_factory=list)
    error_kind: str | None = None
    judge_exit: int | None = None

    @property
    def unverified(self) -> bool:
        return any(c["status"] == "UNVERIFIED" for c in self.criteria) or (
            self.verdict is Verdict.UNVERIFIED
        )

    @property
    def score(self) -> float:
        return VERDICT_SCORE[self.verdict]

    @property
    def exit_code(self) -> int:
        return VERDICT_EXIT[self.verdict]

    def to_dict(self) -> dict:
        return {
            "schema_version": 2, "status": self.verdict.value.lower(),
            "claimed_verdict": self.claimed_verdict, "normalized_verdict": self.verdict.value,
            "score": self.score, "exit_code": self.exit_code,
            "expected_criteria": self.expected_criteria,
            "criteria": [
                {"id": criterion["id"], "status": criterion["status"]}
                for criterion in self.criteria
            ],
            "complete": self.complete, "unverified": self.unverified,
            "contract_valid": self.error_kind is None,
            "verified_failures": [c["id"] for c in self.criteria if c["status"] == "FAIL"],
            "reasons": [_safe_reason(reason) for reason in self.reasons],
            "error_kind": self.error_kind,
            "judge_exit": self.judge_exit,
        }


def _safe_reason(reason: str) -> str:
    """Keep persisted diagnostics bounded and prevent arbitrary output from being copied."""
    if "sandbox" in reason.lower() and "disabled" in reason.lower():
        return "live verification disabled: OS sandbox unavailable"
    return "diagnostic withheld; inspect source output only in an approved local context"


def acceptance_count(text: str) -> int:
    ids = [int(m.group(1)) for line in text.splitlines() if (m := NUMBERED.match(line))]
    if not ids or ids != list(range(1, len(ids) + 1)):
        raise ValueError("acceptance criteria must be a contiguous, unique numbered list")
    return len(ids)


def has_unverified(text: str) -> bool:
    return any(
        m.group(2).upper() == "UNVERIFIED"
        for line in (text or "").splitlines() if (m := CRITERION.match(line))
    )


def environment_error(reason: str, kind: str, response: str = "", **kwargs) -> JudgeResult:
    if response:
        result = parse_result(response, kwargs.get("expected_criteria", 0),
                              judge_exit=kwargs.get("judge_exit") or 0)
        result.verdict = Verdict.SETUP_ERROR
        result.complete = False
        result.error_kind = kind
        result.reasons.insert(0, reason)
        return result
    return JudgeResult(Verdict.SETUP_ERROR, response, reasons=[reason], error_kind=kind, **kwargs)


def verification_disabled(expected: int) -> JudgeResult:
    """Return an honest uncertainty result until an OS-level judge sandbox exists."""
    result = parse_result(
        "\n".join(
            [*(f"{index}. UNVERIFIED - verification sandbox unavailable"
               for index in range(1, expected + 1)),
             "VERDICT: UNVERIFIED"]
        ),
        expected,
    )
    result.reasons = [
        "live verification is disabled: no credential-free, network-disabled OS sandbox"
    ]
    return result


def parse_result(text: str, expected: int, *, judge_exit: int = 0) -> JudgeResult:
    """Strict anchored lines; prose mentions never count as verification statuses."""
    lines = [line for line in (text or "").splitlines() if line.strip()]
    criteria = []
    verdicts = []
    errors = []
    for line in lines:
        if m := CRITERION.match(line):
            criteria.append({
                "id": int(m.group(1)), "status": m.group(2).upper(), "reason": m.group(3),
            })
        elif NUMBERED.match(line):
            errors.append("malformed criterion status line")
        if m := VERDICT.match(line):
            verdicts.append(m.group(1).upper())
        elif re.match(r"^\s*VERDICT\b", line, re.I):
            errors.append("malformed verdict line")
    claimed = verdicts[0] if len(verdicts) == 1 else None
    if len(verdicts) != 1:
        errors.append("expected exactly one verdict line")
    elif not lines or not VERDICT.fullmatch(lines[-1]):
        errors.append("verdict must be the final non-empty line")
    ids = [c["id"] for c in criteria]
    if expected < 1 or sorted(ids) != list(range(1, expected + 1)):
        errors.append("criterion ids/count do not match acceptance criteria (missing or duplicate)")
    if judge_exit:
        errors.insert(0, f"judge CLI exited {judge_exit}; response cannot award credit")
    result = JudgeResult(
        Verdict.SETUP_ERROR, text, claimed, criteria, expected, not errors,
        errors, "judge_cli" if judge_exit else ("judge_contract" if errors else None),
        judge_exit,
    )
    if errors:
        return result
    states = {c["status"] for c in criteria}
    if "UNVERIFIED" in states:
        result.complete = False
        # Uncertainty never erases observed failures. They remain individually recorded,
        # and no verified passes + a failure still means the work failed.
        result.verdict = (
            Verdict.FAILED if "FAIL" in states and "PASS" not in states else Verdict.UNVERIFIED
        )
        result.reasons = [f"criterion {c['id']}: {c['reason']}" for c in criteria
                          if c["status"] == "UNVERIFIED"]
    elif states == {"PASS"}:
        # A judge may have additional evidence of catastrophic breakage: do not upgrade.
        result.verdict = Verdict(claimed)
        if result.verdict is Verdict.UNVERIFIED:
            result.complete = False
            result.reasons = ["judge claimed UNVERIFIED despite verified criterion lines"]
    elif "PASS" in states:
        result.verdict = Verdict.FAILED if claimed == "FAILED" else Verdict.PARTIAL
    else:
        result.verdict = Verdict.FAILED
    if result.verdict.value != claimed:
        result.reasons.append(f"claimed {claimed} normalized to {result.verdict.value}")
    return result


def parse_verdict(text: str, expected: int | None = None) -> Verdict:
    if expected is None:
        expected = sum(bool(CRITERION.match(line)) for line in (text or "").splitlines())
    return parse_result(text, expected).verdict


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
    path.resolve(strict=True).relative_to(root.resolve(strict=True))
    if any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
        raise ValueError("symlinked judge input is forbidden")
    if not path.is_file():
        raise ValueError("judge input is not a file")
    return path


def _canonical_baseline_files(task_id: str) -> tuple[dict[str, str], dict]:
    task_root = Path(__file__).resolve().parent / "pipeline" / "custom-eval" / "tasks"
    task_dir = task_root / task_id
    if task_dir.parent.resolve() != task_root.resolve() or not task_dir.is_dir():
        raise ValueError("workspace task has no canonical repository fixture origin")
    declaration_path = safe_file(task_dir, "inputs.json")
    declaration = json.loads(declaration_path.read_text(encoding="utf-8"))
    if declaration.get("version") != 1 or not isinstance(declaration.get("inputs"), list):
        raise ValueError("canonical fixture input declaration is invalid")
    expected = {
        "context/solution-profile.yaml": hashlib.sha256(
            safe_file(task_dir, "solution-profile.yaml").read_bytes()
        ).hexdigest(),
        "context/inputs.json": hashlib.sha256(declaration_path.read_bytes()).hexdigest(),
    }
    for entry in declaration["inputs"]:
        if not isinstance(entry, dict) or entry.get("required") is not True:
            raise ValueError("canonical fixture input entry is invalid")
        source_rel = safe_relative(entry["source"])
        source = task_dir.joinpath(*source_rel.parts)
        source.resolve(strict=True).relative_to(task_dir.resolve(strict=True))
        if source.is_symlink() or any(parent.is_symlink() for parent in source.parents):
            raise ValueError("canonical fixture contains a symlink")
        destination = safe_relative(entry["destination"]).as_posix()
        if source.is_dir():
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError("canonical fixture contains a symlink")
                if path.is_file():
                    relative = path.relative_to(source).as_posix()
                    expected[f"{destination}/{relative}"] = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
        else:
            expected[destination] = hashlib.sha256(source.read_bytes()).hexdigest()
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
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
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


SELF_TEST_CASES = [
    (0, "1. PASS - ok\nVERDICT: RESOLVED"),
    (2, "1. PASS - ok\n2. FAIL - missing\nVERDICT: PARTIAL"),
    (1, "1. FAIL - broken\nVERDICT: FAILED"),
    (4, "no verdict here"),
    (4, "1. PASS - ok\nVERDICT: RESOLVED\nVERDICT: FAILED"),
    (0, "1. pass - ok\nverdict: resolved"),
    (3, "1. UNVERIFIED - tool missing\nVERDICT: RESOLVED"),
]


def self_test() -> int:
    for want, text in SELF_TEST_CASES:
        result = parse_result(text, 2 if text.startswith("1. PASS - ok\n2.") else 1)
        assert result.exit_code == want, (want, result.to_dict())
    print("grading contract self-test: PASS")
    return 0


def result_status(path: Path, exit_code: int, acceptance: Path | None = None) -> str:
    """Validate the bounded structured result without retaining raw judge output."""
    try:
        row = json.loads(path.read_text(encoding="utf-8-sig"))
        if row.get("schema_version") != 2:
            return "setup_error"
        if acceptance and row["expected_criteria"] != acceptance_count(
            acceptance.read_text(encoding="utf-8")
        ):
            return "setup_error"
        status = row["status"]
        if status not in STATUS_EXIT or STATUS_EXIT[status] != exit_code:
            return "setup_error"
        if row.get("exit_code") != exit_code:
            return "setup_error"
        if row.get("raw_response_persisted") is not False:
            return "setup_error"
        if status == "setup_error":
            return (
                status if row.get("normalized_verdict") == "SETUP_ERROR"
                and row.get("score") == 0 else "setup_error"
            )
        criteria = row["criteria"]
        if not isinstance(criteria, list) or [item.get("id") for item in criteria] != list(
            range(1, row["expected_criteria"] + 1)
        ):
            return "setup_error"
        states = [item.get("status") for item in criteria]
        if any(state not in {"PASS", "FAIL", "UNVERIFIED"} for state in states):
            return "setup_error"
        claimed = row.get("claimed_verdict")
        if claimed not in {v.value for v in Verdict if v not in {Verdict.SETUP_ERROR}}:
            return "setup_error"
        canonical = "\n".join(
            [*(f"{item['id']}. {item['status']} - evidence omitted"
               for item in criteria), f"VERDICT: {claimed}"]
        )
        parsed = parse_result(canonical, row["expected_criteria"]).to_dict()
        if any(row.get(key) != parsed[key] for key in (
            "status", "normalized_verdict", "score", "complete", "unverified",
            "verified_failures",
        )):
            return "setup_error"
        return status
    except (OSError, ValueError, KeyError, TypeError):
        return "setup_error"


def write_result(result: JudgeResult, path: str | Path | None) -> None:
    row = result.to_dict()
    row["raw_response_persisted"] = False
    print("[judge-result] " + json.dumps(row))
    if path:
        Path(path).write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")


class GradingArgumentParser(argparse.ArgumentParser):
    """Bad scorer arguments are setup errors, never legacy PARTIAL exit 2."""

    def error(self, message: str) -> None:
        result = environment_error(message, "setup")
        write_result(result, None)
        self.exit(result.exit_code, f"{self.prog}: {message}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--result-status", type=Path)
    ap.add_argument("--exit-code", type=int, default=4)
    ap.add_argument("--acceptance", type=Path)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        raise SystemExit(self_test())
    if args.result_status:
        print(result_status(args.result_status, args.exit_code, args.acceptance))
