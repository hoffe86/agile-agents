"""Pure verdict parsing and normalization. No I/O or optional dependencies."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


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
    # Response order is not evidence. Persist/read one canonical criterion order.
    criteria.sort(key=lambda criterion: criterion["id"])
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
