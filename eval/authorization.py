"""Offline admission policy. Eligibility is never permission to execute.

All inputs are controller-supplied records, not workspace approval files. Canonical
submission bytes include assessment_reference, but not the assessment/outcome;
Assessment binds that digest separately, avoiding a digest cycle.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Self, get_args, get_origin, get_type_hints

VERSION = 1
MAX_JSON_BYTES = 128 * 1024
TASK05 = "task-05-pr-description"
SELECTED_TASKS = (
    "task-01-csharp-minimal-api-endpoint", "task-02-python-di-refactor",
    "task-03-bicep-storage-waf", "task-04-adr-library-tradeoff", TASK05,
    "task-06-gha-oidc-deploy", "task-07-test-coverage-uplift",
    "task-08-threat-model-api", "task-09-polly-resilience",
    "task-10-helm-to-kustomize",
)
BLOCKERS = (
    "live_hold", "controller_ledger_isolation_unverified",
    "native_atomic_admission_unverified", "stage4_plan_provenance_unverified",
    "delegate_model_provenance_unverified", "credential_transport_unverified",
    "pinned_runtime_compatibility_unverified",
)


class InvalidRecord(ValueError):
    """Bounded diagnostic; never retains rejected input."""

    def __init__(self) -> None:
        super().__init__("invalid_record")


def _require(condition: bool) -> None:
    if not condition:
        raise InvalidRecord()


def identifier(value: str) -> str:
    _require(type(value) is str and
             re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}", value) is not None)
    return value


def _hash(value: str) -> None:
    _require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None)


def timestamp(value: str) -> datetime:
    """Wire times are UTC, whole seconds, with an explicit Z."""
    _require(type(value) is str and
             re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value) is not None)
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        raise InvalidRecord() from None


def expires_at(now: str, seconds: int, ceiling: str) -> str:
    try:
        end = min(timestamp(now) + timedelta(seconds=seconds), timestamp(ceiling))
        return end.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, ValueError):
        raise InvalidRecord() from None


def _path(value: str) -> None:
    _require(type(value) is str and 0 < len(value) <= 4096)
    _require(not any(ord(c) < 32 for c in value))
    # Paths are exact opaque native bindings; never resolve/follow them here.
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    _require(posix.is_absolute() or windows.is_absolute())
    _require(".." not in posix.parts and ".." not in windows.parts)
    _require(not value.startswith(("\\\\", "//")))  # no network paths


def sha256(data: bytes) -> str:
    _require(type(data) is bytes)
    return hashlib.sha256(data).hexdigest()


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise InvalidRecord()


def _decode(annotation: type, value: object, *, wire: bool) -> object:
    if get_origin(annotation) is tuple:
        _require(type(value) is (list if wire else tuple))
        _require(len(value) <= 32)
        return tuple(_decode(get_args(annotation)[0], item, wire=wire) for item in value)
    if isinstance(annotation, type) and issubclass(annotation, Record):
        if wire:
            return annotation.from_dict(value)
        _require(type(value) is annotation)
        value.__post_init__()
        return value
    _require(type(value) is annotation)
    if annotation is str:
        _require(0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value))
    if annotation is int:
        _require(0 <= value <= 2**31 - 1)
    return value


class Record:
    """Exact schemas, frozen nested records and tuples; no coercion or extras."""

    def __post_init__(self) -> None:
        for name, annotation in get_type_hints(type(self)).items():
            _decode(annotation, getattr(self, name), wire=False)
        self._validate()

    def _validate(self) -> None:
        pass

    @classmethod
    def from_dict(cls, value: dict) -> Self:
        _require(type(value) is dict)
        schema = get_type_hints(cls)
        _require(set(value) == set(schema))
        return cls(**{name: _decode(kind, value[name], wire=True)
                      for name, kind in schema.items()})

    @classmethod
    def from_json(cls, data: str | bytes) -> Self:
        _require(type(data) in (str, bytes))
        try:
            _require(len(data) <= MAX_JSON_BYTES)
            if type(data) is bytes:
                data = data.decode("utf-8")
            _require(len(data.encode("utf-8")) <= MAX_JSON_BYTES)
            value = json.loads(data, object_pairs_hook=_pairs,
                               parse_constant=_invalid_constant)
            return cls.from_dict(value)
        except (ValueError, TypeError, RecursionError, UnicodeError):
            raise InvalidRecord() from None

    def canonical_bytes(self) -> bytes:
        self.__post_init__()
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")

    @property
    def digest(self) -> str:
        return sha256(self.canonical_bytes())


@dataclass(frozen=True)
class Identities(Record):
    source_sha256: str
    plugin_sha256: str
    overlay_sha256: str
    input_sha256: str
    runtime_id: str
    toolchain_sha256: str
    model_id: str
    capabilities: tuple[str, ...]

    def _validate(self) -> None:
        for field in fields(self):
            if field.name.endswith("_sha256"):
                _hash(getattr(self, field.name))
        identifier(self.runtime_id)
        identifier(self.model_id)
        _require(bool(self.capabilities) and len(set(self.capabilities)) == len(self.capabilities))
        for capability in self.capabilities:
            identifier(capability)


@dataclass(frozen=True)
class Budget(Record):
    tokens: int
    aiu: int
    seconds: int

    def _validate(self) -> None:
        _require(self.tokens > 0 and self.aiu > 0 and self.seconds > 0)

    def fits(self, ceiling: Budget) -> bool:
        return all(getattr(self, f.name) <= getattr(ceiling, f.name) for f in fields(self))


@dataclass(frozen=True)
class Operation(Record):
    kind: str
    target: str
    actor_id: str
    max_bytes: int

    def _validate(self) -> None:
        identifier(self.kind)
        identifier(self.actor_id)
        _path(self.target)
        _require(0 < self.max_bytes <= MAX_JSON_BYTES)


@dataclass(frozen=True)
class BatchEnvelope(Record):
    version: int
    batch_id: str
    approval_reference: str
    valid_from: str
    valid_until: str
    selected_tasks: tuple[str, ...]
    permitted_tasks: tuple[str, ...]
    permitted_identities: tuple[Identities, ...]
    permitted_operations: tuple[Operation, ...]
    assessor_id: str
    max_attempts: int
    max_attempts_per_task: int
    budget: Budget
    grant_ttl_seconds: int

    def _validate(self) -> None:
        _require(self.version == VERSION)
        identifier(self.batch_id)
        identifier(self.approval_reference)
        identifier(self.assessor_id)
        _require(timestamp(self.valid_from) < timestamp(self.valid_until))
        _require(self.selected_tasks == SELECTED_TASKS)
        _require(self.permitted_tasks == (TASK05,))
        _require(bool(self.permitted_identities))
        _require(len(set(self.permitted_identities)) == len(self.permitted_identities))
        _require(0 < self.max_attempts_per_task <= self.max_attempts)
        _require(0 < self.grant_ttl_seconds <= self.budget.seconds)
        _require(len(self.permitted_operations) == 2)
        _require({o.kind for o in self.permitted_operations} ==
                 {"read_input", "write_description"})
        read = next(o for o in self.permitted_operations if o.kind == "read_input")
        write = next(o for o in self.permitted_operations if o.kind == "write_description")
        _require(PureWindowsPath(read.target).name == "diff.patch")
        _require(PureWindowsPath(write.target).suffix == ".md")
        _require(read.target != write.target)
        for identity in self.permitted_identities:
            _require(set(identity.capabilities) == {"read_input", "write_description"})


@dataclass(frozen=True)
class PlanSubmission(Record):
    version: int
    batch_id: str
    run_id: str
    attempt_id: str
    task_id: str
    controller_instance_id: str
    native_session_id: str
    envelope_digest: str
    plan_path: str
    plan_sha256: str
    identities: Identities
    operations: tuple[Operation, ...]
    budget: Budget
    assessment_reference: str

    def _validate(self) -> None:
        _require(self.version == VERSION)
        for name in ("batch_id", "run_id", "attempt_id", "task_id",
                     "controller_instance_id", "native_session_id", "assessment_reference"):
            identifier(getattr(self, name))
        _hash(self.envelope_digest)
        _hash(self.plan_sha256)
        _path(self.plan_path)
        _require(bool(self.operations) and len(set(self.operations)) == len(self.operations))


@dataclass(frozen=True)
class Assessment(Record):
    reference: str
    assessor_id: str
    submission_digest: str
    outcome: str

    def _validate(self) -> None:
        identifier(self.reference)
        identifier(self.assessor_id)
        _hash(self.submission_digest)
        _require(self.outcome in ("in_scope", "out_of_scope", "uncertain"))


@dataclass(frozen=True)
class Decision(Record):
    outcome: str
    reason_codes: tuple[str, ...]

    def _validate(self) -> None:
        _require(self.outcome in ("eligible", "block_task", "abort_batch"))
        _require(bool(self.reason_codes))
        for reason in self.reason_codes:
            identifier(reason)


@dataclass(frozen=True)
class Grant(Record):
    grant_id: str
    submission: PlanSubmission
    submission_digest: str
    issued_at: str
    expires_at: str
    state: str

    def _validate(self) -> None:
        identifier(self.grant_id)
        _require(self.submission_digest == self.submission.digest)
        _require(timestamp(self.issued_at) < timestamp(self.expires_at))
        _require(self.state == "issued")


@dataclass(frozen=True)
class AdmissionReceipt(Record):
    ledger_id: str
    grant_id: str
    submission: PlanSubmission
    submission_digest: str
    consumed_at: str
    expires_at: str

    def _validate(self) -> None:
        identifier(self.ledger_id)
        identifier(self.grant_id)
        _require(self.submission_digest == self.submission.digest)
        _require(timestamp(self.consumed_at) < timestamp(self.expires_at))


@dataclass(frozen=True)
class Readiness(Record):
    execution_ready: bool
    state: str
    blocker_codes: tuple[str, ...]

    def _validate(self) -> None:
        _require(self.execution_ready is False and self.state == "not_ready")
        _require(self.blocker_codes == BLOCKERS)


def live_readiness() -> Readiness:
    return Readiness(False, "not_ready", BLOCKERS)


def _valid(record: Record, kind: type[Record]) -> bool:
    if type(record) is not kind:
        return False
    try:
        record.__post_init__()
        return True
    except (InvalidRecord, TypeError, AttributeError):
        return False


def _scope_fits(operations: tuple[Operation, ...], allowed: tuple[Operation, ...]) -> bool:
    return all(any(o.kind == a.kind and o.target == a.target and
                   o.actor_id == a.actor_id and o.max_bytes <= a.max_bytes
                   for a in allowed) for o in operations)


def evaluate(envelope: BatchEnvelope, submission: PlanSubmission,
             assessment: Assessment | None, *, now: str) -> Decision:
    """Pure policy only: caller must independently authenticate the envelope."""
    try:
        current_time = timestamp(now)
    except InvalidRecord:
        return Decision("abort_batch", ("invalid_time",))
    if not _valid(envelope, BatchEnvelope) or not _valid(submission, PlanSubmission):
        return Decision("block_task", ("invalid_record",))
    if (submission.batch_id != envelope.batch_id or
            submission.envelope_digest != envelope.digest):
        return Decision("abort_batch", ("envelope_binding_mismatch",))
    if not timestamp(envelope.valid_from) <= current_time < timestamp(envelope.valid_until):
        return Decision("block_task", ("envelope_time_invalid",))
    if submission.task_id not in envelope.permitted_tasks:
        return Decision("block_task", ("unsupported_task",))
    if submission.identities not in envelope.permitted_identities:
        return Decision("abort_batch", ("identity_mismatch",))
    if (not _scope_fits(submission.operations, envelope.permitted_operations) or
            any(o.kind not in submission.identities.capabilities for o in submission.operations)):
        return Decision("block_task", ("operation_out_of_scope",))
    if not submission.budget.fits(envelope.budget):
        return Decision("block_task", ("budget_exceeded",))
    if not _valid(assessment, Assessment):
        return Decision("block_task", ("assessment_missing_or_invalid",))
    actors = {o.actor_id for o in submission.operations}
    if (assessment.assessor_id != envelope.assessor_id or
            assessment.assessor_id in actors | {
                submission.controller_instance_id, submission.native_session_id}):
        return Decision("block_task", ("assessor_not_independent",))
    if (assessment.reference != submission.assessment_reference or
            assessment.submission_digest != submission.digest):
        return Decision("block_task", ("assessment_binding_mismatch",))
    if assessment.outcome != "in_scope":
        return Decision("block_task", ("assessment_" + assessment.outcome,))
    return Decision("eligible", ("policy_eligible_not_execution_ready",))


def evaluate_operation(receipt: AdmissionReceipt, operation: Operation,
                       current_binding: PlanSubmission, *, now: str) -> Decision:
    """Receipt is context, not bearer authority; live operation admission stays held.

    A future adapter must fetch the receipt from its trusted ledger and check
    revocation as well. Deserializing a receipt from the workspace grants nothing.
    """
    if (not _valid(receipt, AdmissionReceipt) or not _valid(operation, Operation) or
            not _valid(current_binding, PlanSubmission)):
        return Decision("block_task", ("invalid_record",))
    if current_binding != receipt.submission:
        return Decision("abort_batch", ("current_binding_mismatch",))
    try:
        if not timestamp(receipt.consumed_at) <= timestamp(now) < timestamp(receipt.expires_at):
            return Decision("block_task", ("receipt_expired",))
    except InvalidRecord:
        return Decision("abort_batch", ("invalid_time",))
    if not _scope_fits((operation,), current_binding.operations):
        return Decision("block_task", ("operation_out_of_scope",))
    return Decision("block_task", ("execution_not_ready",))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check-readiness",))
    parser.parse_args()
    print(live_readiness().canonical_bytes().decode("ascii"))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
