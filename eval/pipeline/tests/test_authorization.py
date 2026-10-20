"""Offline policy and real SQLite contracts; no SDK, DeepEval or model calls."""
from __future__ import annotations

from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, fields, replace
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


EVAL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EVAL))

from authorization import (  # noqa: E402
    AdmissionReceipt, Assessment, BatchEnvelope, BLOCKERS, Budget, Decision, Grant,
    Identities, InvalidRecord, Operation, PlanSubmission, Readiness, SELECTED_TASKS,
    TASK05, evaluate, evaluate_operation, live_readiness, sha256,
)
from authorization_ledger import AdmissionDenied, Ledger  # noqa: E402


NOW = "2026-10-20T12:00:00Z"
LATER = "2026-10-20T12:00:01Z"
EXPIRED = "2026-10-20T12:01:00Z"
PLAN = b"Read the immutable diff.patch and write only the Markdown description.\n"
INPUT = EVAL / "pipeline/custom-eval/tasks" / TASK05 / "baseline/diff.patch"


def records() -> tuple[BatchEnvelope, PlanSubmission, Assessment]:
    identities = Identities(
        sha256(b"source"), sha256(b"plugin"), sha256(b"overlay"),
        sha256(INPUT.read_bytes()), "copilot-cli-1.0.98-sdk-1.0.22",
        sha256(b"locked-toolchain"), "gpt-6.1-sol",
        ("read_input", "write_description"),
    )
    operations = (
        Operation("read_input", "/worker/input/diff.patch", "writer", 65536),
        Operation("write_description", "/worker/output/description.md", "writer", 8192),
    )
    envelope = BatchEnvelope(
        1, "batch-1", "human-approval-oct20", NOW, "2026-10-20T13:00:00Z",
        SELECTED_TASKS, (TASK05,), (identities,), operations, "independent-assessor",
        3, 3, Budget(300, 30, 300), 60,
    )
    submission = PlanSubmission(
        1, envelope.batch_id, "run-1", "attempt-1", TASK05, "controller-1",
        "native-session-1", envelope.digest, "/controller/native/plan.md",
        sha256(PLAN), identities, operations, Budget(100, 10, 100), "assessment-1",
    )
    return envelope, submission, advice(submission)


def advice(submission: PlanSubmission, **changes: object) -> Assessment:
    return replace(Assessment(
        submission.assessment_reference, "independent-assessor",
        submission.digest, "in_scope",
    ), **changes)


def mutations(submission: PlanSubmission) -> dict[str, PlanSubmission]:
    """Every validly typed binding mutation; invalid versions are tested separately."""
    changes = {
        "batch_id": "batch-2", "run_id": "run-2", "attempt_id": "attempt-2",
        "task_id": SELECTED_TASKS[0], "controller_instance_id": "controller-2",
        "native_session_id": "native-session-2", "envelope_digest": sha256(b"other"),
        "plan_path": "/controller/native/other.md",
        "plan_sha256": sha256(PLAN.replace(b"\n", b"\r\n")),
        "identities": replace(submission.identities, model_id="gpt-6-astra"),
        "operations": (submission.operations[0],),
        "budget": Budget(99, 10, 100), "assessment_reference": "assessment-2",
    }
    result = {name: replace(submission, **{name: value}) for name, value in changes.items()}
    for item in fields(Identities):
        value = getattr(submission.identities, item.name)
        changed = (("read_input",) if item.name == "capabilities" else
                   sha256(b"changed") if item.name.endswith("_sha256") else value + "-changed")
        result["identities." + item.name] = replace(
            submission, identities=replace(submission.identities, **{item.name: changed}))
    for item in fields(Operation):
        value = getattr(submission.operations[0], item.name)
        changed = value - 1 if item.name == "max_bytes" else value + "-changed"
        operation = replace(submission.operations[0], **{item.name: changed})
        result["operations." + item.name] = replace(
            submission, operations=(operation, submission.operations[1]))
    for item in fields(Budget):
        result["budget." + item.name] = replace(submission, budget=replace(
            submission.budget, **{item.name: getattr(submission.budget, item.name) - 1}))
    return result


def race_consume(path: str, submission_json: bytes, grant_id: str,
                 ready: object, start: object, results: object) -> None:
    """Spawn-safe worker: each process owns an independent SQLite connection."""
    try:
        submission = PlanSubmission.from_json(submission_json)
        with Ledger(Path(path), controller_instance_id="controller-1", join_existing=True) as ledger:
            ready.put("ready")
            if not start.wait(20):
                results.put("start_timeout")
                return
            try:
                ledger.consume(grant_id, current_binding=submission, now=LATER)
                results.put("consumed")
            except AdmissionDenied as exc:
                results.put(str(exc))
    except Exception as exc:
        results.put(type(exc).__name__)


def crash_after_consumption(path: str, submission_json: bytes, grant_id: str) -> None:
    submission = PlanSubmission.from_json(submission_json)
    ledger = Ledger(Path(path), controller_instance_id="controller-1", join_existing=True)
    ledger.consume(grant_id, current_binding=submission, now=LATER)
    # Model a response lost after durable consumption, not a clean shutdown.
    os._exit(23)


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope, self.submission, self.assessment = records()

    def test_strict_roundtrip_for_every_record(self) -> None:
        grant = Grant("opaque-grant", self.submission, self.submission.digest, NOW, EXPIRED, "issued")
        receipt = AdmissionReceipt("ledger-1", grant.grant_id, self.submission,
                                   self.submission.digest, LATER, EXPIRED)
        values = (self.envelope, self.submission, self.assessment,
                  self.submission.identities, self.submission.budget,
                  self.submission.operations[0], Decision("block_task", ("held",)),
                  grant, receipt, live_readiness())
        for value in values:
            with self.subTest(record=type(value).__name__):
                self.assertEqual(type(value).from_json(value.canonical_bytes()), value)
                self.assertEqual(type(value).from_dict(json.loads(value.canonical_bytes())), value)
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, fields(value)[0].name, None)

    def test_unknown_missing_duplicate_keys_and_nonfinite_numbers_deny(self) -> None:
        encoded = self.submission.canonical_bytes().decode()
        cases = (
            encoded[:-1] + ',"approved":true}',
            encoded.replace('"version":1', '"version":1,"version":1'),
            encoded.replace('"version":1', '"version":NaN'),
            encoded.replace('"version":1', '"version":Infinity'),
            encoded.replace('"version":1', '"version":-Infinity'),
            encoded.replace('"version":1', '"version":1e999'),
            encoded.replace('"version":1', '"version":true'),
            encoded.replace('"version":1', '"version":"1"'),
            encoded.replace('"version":1', '"version":2'),
            encoded.replace('"version":1', '"version":null'),
            encoded.replace(',"version":1', ""),
            encoded.replace('"tokens":100', '"tokens":100,"tokens":100'),
            "[]", "null", "{", b"\xff", "[" * 1001, " " * (128 * 1024 + 1),
        )
        for data in cases:
            with self.subTest(data=str(data)[:60]), self.assertRaises(InvalidRecord):
                PlanSubmission.from_json(data)

    def test_every_record_field_rejects_wrong_type_and_unknown_key(self) -> None:
        for record in (self.envelope, self.submission, self.assessment,
                       self.submission.identities, self.submission.budget,
                       self.submission.operations[0], live_readiness()):
            for field in fields(record):
                data = json.loads(record.canonical_bytes())
                data[field.name] = None
                with self.subTest(record=type(record).__name__, field=field.name):
                    with self.assertRaises(InvalidRecord):
                        type(record).from_dict(data)
            data = json.loads(record.canonical_bytes())
            data["approved"] = True
            with self.assertRaises(InvalidRecord):
                type(record).from_dict(data)

    def test_nested_mutable_types_and_empty_identities_deny(self) -> None:
        for changes in (
            {"operations": list(self.submission.operations)},
            {"operations": ()}, {"identities": asdict(self.submission.identities)},
            {"plan_sha256": "not-a-hash"}, {"run_id": ""}, {"plan_path": "relative.md"},
            {"plan_path": "/native/../plan.md"}, {"plan_path": r"\\server\plan.md"},
        ):
            with self.subTest(changes=changes), self.assertRaises(InvalidRecord):
                replace(self.submission, **changes)

    def test_invalid_time_and_interval_deny(self) -> None:
        for value in ("2026-02-30T00:00:00Z", "2026-10-20T12:00:00",
                      "2026-10-20T12:00:00+00:00", "2026-10-20T12:00:00.1Z",
                      "2026-10-20T12:00:60Z", "", None):
            with self.subTest(value=value), self.assertRaises(InvalidRecord):
                replace(self.envelope, valid_from=value)
        with self.assertRaises(InvalidRecord):
            replace(self.envelope, valid_until=NOW)

    def test_exact_bytes_and_assessment_have_no_digest_cycle(self) -> None:
        self.assertNotEqual(sha256(PLAN), sha256(PLAN.replace(b"\n", b"\r\n")))
        original = self.submission.digest
        changed = replace(self.assessment, outcome="uncertain")
        self.assertEqual(changed.submission_digest, original)
        self.assertEqual(self.submission.digest, original)
        self.assertNotEqual(changed.digest, self.assessment.digest)

    def test_full_inventory_matches_real_tasks_and_only_task05_is_permitted(self) -> None:
        actual = tuple(sorted(p.name for p in (EVAL / "pipeline/custom-eval/tasks").iterdir()
                              if p.is_dir() and p.name.startswith("task-")))
        self.assertEqual(actual, SELECTED_TASKS)
        self.assertEqual(len(actual), 10)
        self.assertEqual(self.envelope.permitted_tasks, (TASK05,))
        self.assertEqual(self.submission.identities.input_sha256, sha256(INPUT.read_bytes()))
        with self.assertRaises(InvalidRecord):
            replace(self.envelope, selected_tasks=(TASK05,))
        with self.assertRaises(InvalidRecord):
            replace(self.envelope, permitted_tasks=SELECTED_TASKS)


class PolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope, self.submission, self.assessment = records()

    def test_matching_records_are_eligible_but_readiness_is_permanently_false(self) -> None:
        result = evaluate(self.envelope, self.submission, self.assessment, now=NOW)
        self.assertEqual(result, Decision("eligible", ("policy_eligible_not_execution_ready",)))
        self.assertEqual(live_readiness(), Readiness(False, "not_ready", BLOCKERS))
        with self.assertRaises(InvalidRecord):
            replace(live_readiness(), execution_ready=True)
        self.assertIn("native_atomic_admission_unverified", BLOCKERS)
        self.assertIn("controller_ledger_isolation_unverified", BLOCKERS)
        self.assertIn("credential_transport_unverified", BLOCKERS)

    def test_absent_uncertain_out_of_scope_and_mismatched_assessments_deny(self) -> None:
        for assessment in (
            None, Decision("eligible", ("forged",)),
            replace(self.assessment, outcome="uncertain"),
            replace(self.assessment, outcome="out_of_scope"),
            replace(self.assessment, submission_digest=sha256(b"other")),
            replace(self.assessment, reference="different"),
            replace(self.assessment, assessor_id="writer"),
        ):
            with self.subTest(assessment=assessment):
                self.assertEqual(evaluate(self.envelope, self.submission, assessment,
                                          now=NOW).outcome, "block_task")

    def test_assessor_cannot_be_actor_session_or_controller_even_if_envelope_says_so(self) -> None:
        for actor in ("writer", "controller-1", "native-session-1"):
            envelope = replace(self.envelope, assessor_id=actor)
            submission = replace(self.submission, envelope_digest=envelope.digest)
            with self.subTest(actor=actor):
                self.assertEqual(evaluate(envelope, submission, advice(submission, assessor_id=actor),
                                          now=NOW).reason_codes, ("assessor_not_independent",))

    def test_every_submission_binding_mutation_invalidates_original_assessment(self) -> None:
        cases = mutations(self.submission)
        self.assertEqual(set(f.name for f in fields(PlanSubmission)) - {"version"},
                         {name for name in cases if "." not in name})
        for name, submission in cases.items():
            with self.subTest(field=name):
                self.assertNotEqual(evaluate(self.envelope, submission, self.assessment,
                                             now=NOW).outcome, "eligible")

    def test_favorable_advice_cannot_expand_operations_or_capabilities(self) -> None:
        for kind in ("open_pr", "edit_source", "network", "jira", "write_input", "shell"):
            operation = replace(self.submission.operations[1], kind=kind)
            submission = replace(self.submission, operations=(operation,))
            with self.subTest(operation=kind):
                self.assertEqual(evaluate(self.envelope, submission, advice(submission),
                                          now=NOW).reason_codes, ("operation_out_of_scope",))
        expanded = replace(self.submission, identities=replace(
            self.submission.identities, capabilities=("read_input", "write_description", "shell")))
        self.assertEqual(evaluate(self.envelope, expanded, advice(expanded),
                                  now=NOW).outcome, "abort_batch")

    def test_each_identity_mutation_denies_even_with_favorable_advice(self) -> None:
        for name, submission in mutations(self.submission).items():
            if name.startswith("identities."):
                with self.subTest(field=name):
                    self.assertEqual(evaluate(self.envelope, submission, advice(submission),
                                              now=NOW).outcome, "abort_batch")

    def test_nine_unsupported_tasks_stay_in_denominator_and_deny(self) -> None:
        denied = []
        for task in SELECTED_TASKS:
            submission = replace(self.submission, task_id=task)
            if task != TASK05:
                denied.append(evaluate(self.envelope, submission, advice(submission),
                                       now=NOW).reason_codes)
        self.assertEqual(denied, [("unsupported_task",)] * 9)

    def test_time_boundaries_invalid_records_and_excess_budget_deny(self) -> None:
        for now in ("2026-10-20T11:59:59Z", self.envelope.valid_until):
            with self.subTest(now=now):
                self.assertEqual(evaluate(self.envelope, self.submission, self.assessment,
                                          now=now).reason_codes, ("envelope_time_invalid",))
        self.assertEqual(evaluate(self.envelope, self.submission, self.assessment,
                                  now="invalid").outcome, "abort_batch")
        self.assertEqual(evaluate({}, self.submission, self.assessment, now=NOW).outcome,
                         "block_task")
        submission = replace(self.submission, budget=Budget(301, 30, 300))
        self.assertEqual(evaluate(self.envelope, submission, advice(submission),
                                  now=NOW).reason_codes, ("budget_exceeded",))

    def test_receipt_is_context_not_bearer_permission(self) -> None:
        receipt = AdmissionReceipt("ledger-1", "grant-1", self.submission,
                                   self.submission.digest, NOW, EXPIRED)
        read = self.submission.operations[0]
        self.assertEqual(evaluate_operation(receipt, read, self.submission, now=NOW),
                         Decision("block_task", ("execution_not_ready",)))
        self.assertEqual(evaluate_operation(receipt, replace(read, kind="shell"),
                                             self.submission, now=NOW).reason_codes,
                         ("operation_out_of_scope",))
        self.assertEqual(evaluate_operation(receipt, read, self.submission,
                                             now=EXPIRED).reason_codes, ("receipt_expired",))
        self.assertEqual(evaluate_operation(receipt, read, self.submission,
                                             now="invalid").outcome, "abort_batch")
        self.assertEqual(evaluate_operation({}, read, self.submission, now=NOW).outcome,
                         "block_task")
        for name, binding in mutations(self.submission).items():
            with self.subTest(field=name):
                self.assertEqual(evaluate_operation(receipt, read, binding,
                                                     now=NOW).outcome, "abort_batch")


class LedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name).resolve() / "admission.sqlite"
        self.envelope, self.submission, self.assessment = records()
        self.ledger = self.open()
        self.register()

    def open(self, *, join: bool = False, controller: str = "controller-1") -> Ledger:
        ledger = Ledger(self.path, controller_instance_id=controller, join_existing=join)
        self.addCleanup(ledger.close)
        return ledger

    def register(self, envelope: BatchEnvelope | None = None, ledger: Ledger | None = None) -> None:
        envelope = envelope or self.envelope
        (ledger or self.ledger).register_envelope(
            envelope, expected_digest=envelope.digest,
            approval_reference=envelope.approval_reference)

    def issue(self, submission: PlanSubmission | None = None) -> Grant:
        submission = submission or self.submission
        result = self.ledger.issue(submission, advice(submission), now=NOW)
        self.assertIsInstance(result, Grant)
        return result

    def deny_consume(self, grant_id: str, reason: str, **kwargs: object) -> AdmissionDenied:
        with self.assertRaisesRegex(AdmissionDenied, "^" + reason + "$") as caught:
            self.ledger.consume(grant_id, current_binding=kwargs.get("binding", self.submission),
                                now=kwargs.get("now", LATER))
        return caught.exception

    def test_matching_envelope_issues_and_consumes_once_with_durable_receipt(self) -> None:
        grant = self.issue()
        receipt = self.ledger.consume(grant.grant_id, current_binding=self.submission, now=LATER)
        self.assertEqual(receipt.submission, self.submission)
        self.assertEqual(receipt.ledger_id, self.ledger.ledger_id)
        self.assertEqual(receipt.submission_digest, self.submission.digest)
        with closing(sqlite3.connect(self.path)) as db, db:
            state, stored = db.execute("SELECT state,receipt FROM grants").fetchone()
        self.assertEqual(state, "consumed")
        self.assertEqual(AdmissionReceipt.from_json(stored), receipt)
        self.deny_consume(grant.grant_id, "grant_not_issued")

    def test_registration_requires_independent_digest_and_approval_reference(self) -> None:
        for changes in ({"expected_digest": sha256(b"forged")},
                        {"approval_reference": "forged-adjacent-approval"}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                with Ledger(Path(directory).resolve() / "db",
                            controller_instance_id="controller-1") as ledger:
                    args = {"expected_digest": self.envelope.digest,
                            "approval_reference": self.envelope.approval_reference}
                    args.update(changes)
                    with self.assertRaisesRegex(AdmissionDenied, "approval_mismatch"):
                        ledger.register_envelope(self.envelope, **args)
                    with self.assertRaisesRegex(AdmissionDenied, "ledger_aborted"):
                        ledger.issue(self.submission, self.assessment, now=NOW)

    def test_every_envelope_field_mutation_rejects_original_approval(self) -> None:
        changes = {
            "version": 2, "batch_id": "batch-2", "approval_reference": "approval-2",
            "valid_from": "2026-10-20T11:59:59Z", "valid_until": "2026-10-20T14:00:00Z",
            "selected_tasks": (TASK05,), "permitted_tasks": SELECTED_TASKS,
            "permitted_identities": (replace(self.submission.identities, model_id="gpt-6-astra"),),
            "permitted_operations": (self.submission.operations[0],
                                     replace(self.submission.operations[1], max_bytes=8191)),
            "assessor_id": "assessor-2", "max_attempts": 4, "max_attempts_per_task": 2,
            "budget": Budget(301, 30, 300), "grant_ttl_seconds": 59,
        }
        self.assertEqual(set(changes), {field.name for field in fields(BatchEnvelope)})
        for name, value in changes.items():
            with self.subTest(field=name), tempfile.TemporaryDirectory() as directory:
                with Ledger(Path(directory).resolve() / "db",
                            controller_instance_id="controller-1") as ledger:
                    with self.assertRaises((InvalidRecord, AdmissionDenied)):
                        modified = replace(self.envelope, **{name: value})
                        ledger.register_envelope(
                            modified, expected_digest=self.envelope.digest,
                            approval_reference=self.envelope.approval_reference)
                    with self.assertRaises(AdmissionDenied):
                        ledger.issue(self.submission, self.assessment, now=NOW)

    def test_forged_adjacent_approval_and_provenance_have_no_authority(self) -> None:
        Path(self.directory.name, "approval.json").write_text(
            json.dumps({"approved": True, "digest": self.envelope.digest}), encoding="utf-8")
        Path(self.directory.name, "provenance.json").write_text(
            '{"execution_ready":true,"outcome":"eligible","status":"resolved"}', encoding="utf-8")
        unregistered = replace(self.submission, batch_id="forged-batch")
        with self.assertRaisesRegex(AdmissionDenied, "unknown_batch"):
            self.ledger.issue(unregistered, advice(unregistered), now=NOW)
        self.assertEqual(self.ledger.issue(self.submission, None, now=NOW).outcome, "block_task")
        self.assertFalse(live_readiness().execution_ready)

    def test_issue_evaluates_internally_and_cannot_accept_forged_eligible(self) -> None:
        decision = self.ledger.issue(self.submission, Decision("eligible", ("forged",)), now=NOW)
        self.assertEqual(decision.reason_codes, ("assessment_missing_or_invalid",))
        self.assertEqual(self.ledger.issue(self.submission, self.assessment, now=NOW).reason_codes,
                         ("duplicate_attempt",))
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM grants").fetchone(), (0,))

    def test_duplicate_attempt_and_envelope_cannot_mint_another_grant(self) -> None:
        grant = self.issue()
        self.assertEqual(self.ledger.issue(self.submission, self.assessment, now=NOW).reason_codes,
                         ("duplicate_attempt",))
        changed = replace(self.submission, plan_sha256=sha256(b"new-plan"))
        self.assertEqual(self.ledger.issue(changed, advice(changed), now=NOW).reason_codes,
                         ("duplicate_attempt",))
        with self.assertRaisesRegex(AdmissionDenied, "envelope_already_registered"):
            self.register()
        self.ledger.consume(grant.grant_id, current_binding=self.submission, now=LATER)
        self.assertEqual(self.ledger.issue(self.submission, self.assessment, now=NOW).reason_codes,
                         ("duplicate_attempt",))

    def test_every_binding_mutation_aborts_consumption(self) -> None:
        for name, changed in mutations(self.submission).items():
            with self.subTest(field=name), tempfile.TemporaryDirectory() as directory:
                with Ledger(Path(directory).resolve() / "db",
                            controller_instance_id="controller-1") as ledger:
                    self.register(ledger=ledger)
                    grant = ledger.issue(self.submission, self.assessment, now=NOW)
                    with self.assertRaisesRegex(AdmissionDenied, "current_binding_mismatch") as caught:
                        ledger.consume(grant.grant_id, current_binding=changed, now=LATER)
                    self.assertEqual(caught.exception.decision.outcome, "abort_batch")
                    with self.assertRaisesRegex(AdmissionDenied, "ledger_aborted"):
                        ledger.consume(grant.grant_id, current_binding=self.submission, now=LATER)

    def test_expired_not_yet_valid_unknown_and_revoked_grants_deny(self) -> None:
        grant = self.issue()
        self.deny_consume(grant.grant_id, "grant_expired", now=EXPIRED)
        self.deny_consume(grant.grant_id, "grant_expired", now="2026-10-20T11:59:59Z")
        self.deny_consume("unknown-grant", "unknown_grant")
        self.ledger.invalidate_attempt(self.submission.attempt_id, reason="native_transition_uncertain")
        self.deny_consume(grant.grant_id, "grant_not_issued")

    def test_attempt_limits_include_blocked_and_revoked_attempts(self) -> None:
        self.ledger.issue(self.submission, None, now=NOW)
        second = replace(self.submission, attempt_id="attempt-2")
        self.issue(second)
        self.ledger.invalidate_attempt(second.attempt_id, reason="cancelled")
        third = replace(self.submission, attempt_id="attempt-3")
        self.issue(third)
        fourth = replace(self.submission, attempt_id="attempt-4")
        self.assertEqual(self.ledger.issue(fourth, advice(fourth), now=NOW).reason_codes,
                         ("attempt_limit_exceeded",))

    def test_cumulative_budget_not_refunded_after_revocation_or_consumption(self) -> None:
        large = replace(self.submission, budget=Budget(150, 15, 150))
        grant = self.issue(large)
        self.ledger.consume(grant.grant_id, current_binding=large, now=LATER)
        second = replace(large, attempt_id="attempt-2")
        self.issue(second)
        self.ledger.invalidate_attempt(second.attempt_id, reason="response_lost")
        third = replace(self.submission, attempt_id="attempt-3")
        self.assertEqual(self.ledger.issue(third, advice(third), now=NOW).reason_codes,
                         ("budget_exceeded",))

    def test_each_budget_dimension_enforces_cumulative_limit(self) -> None:
        for dimension in ("tokens", "aiu", "seconds"):
            with self.subTest(dimension=dimension), tempfile.TemporaryDirectory() as directory:
                with Ledger(Path(directory).resolve() / "db",
                            controller_instance_id="controller-1") as ledger:
                    self.register(ledger=ledger)
                    budget = replace(self.submission.budget, **{
                        dimension: getattr(self.envelope.budget, dimension)})
                    first = replace(self.submission, budget=budget)
                    self.assertIsInstance(ledger.issue(first, advice(first), now=NOW), Grant)
                    second = replace(self.submission, attempt_id="attempt-2")
                    self.assertEqual(ledger.issue(second, advice(second), now=NOW).reason_codes,
                                     ("budget_exceeded",))

    def test_grant_expiry_is_capped_by_envelope_and_attempt_duration(self) -> None:
        for end, seconds, expected in (
            ("2026-10-20T12:00:30Z", 100, "2026-10-20T12:00:30Z"),
            ("2026-10-20T13:00:00Z", 10, "2026-10-20T12:00:10Z"),
        ):
            with self.subTest(end=end, seconds=seconds), tempfile.TemporaryDirectory() as directory:
                with Ledger(Path(directory).resolve() / "db",
                            controller_instance_id="controller-1") as ledger:
                    envelope = replace(self.envelope, valid_until=end)
                    self.register(envelope, ledger)
                    submission = replace(self.submission, envelope_digest=envelope.digest,
                                         budget=replace(self.submission.budget, seconds=seconds))
                    grant = ledger.issue(submission, advice(submission), now=NOW)
                    self.assertEqual(grant.expires_at, expected)
                    with self.assertRaisesRegex(AdmissionDenied, "grant_expired"):
                        ledger.consume(grant.grant_id, current_binding=submission, now=expected)

    def test_policy_abort_is_persisted_and_not_just_returned(self) -> None:
        submission = replace(self.submission, identities=replace(
            self.submission.identities, model_id="unapproved-model"))
        self.assertEqual(self.ledger.issue(submission, advice(submission), now=NOW).outcome,
                         "abort_batch")
        second = self.open(join=True)
        with self.assertRaisesRegex(AdmissionDenied, "batch_aborted"):
            second.issue(self.submission, self.assessment, now=NOW)

    def test_abort_batch_denies_existing_and_future_grants(self) -> None:
        grant = self.issue()
        self.ledger.abort_batch(self.envelope.batch_id, reason="disconnect")
        self.deny_consume(grant.grant_id, "grant_not_issued")
        with self.assertRaisesRegex(AdmissionDenied, "batch_aborted"):
            self.ledger.issue(replace(self.submission, attempt_id="attempt-2"),
                              self.assessment, now=NOW)
        with self.assertRaisesRegex(AdmissionDenied, "envelope_already_registered"):
            self.register()

    def test_restart_aborts_unfinished_attempt_and_fences_old_connection(self) -> None:
        grant = self.issue()
        restarted = self.open(controller="controller-2")
        with self.assertRaisesRegex(AdmissionDenied, "grant_not_issued"):
            restarted.consume(grant.grant_id, current_binding=self.submission, now=LATER)
        with self.assertRaisesRegex(AdmissionDenied, "batch_aborted"):
            restarted.issue(replace(self.submission, controller_instance_id="controller-2"),
                            self.assessment, now=NOW)
        self.assertEqual(self.deny_consume(grant.grant_id, "controller_mismatch").decision.outcome,
                         "abort_batch")

    def test_process_crash_after_consumption_does_not_refund_or_resume(self) -> None:
        grant = self.issue()
        context = multiprocessing.get_context("spawn")
        process = context.Process(target=crash_after_consumption, args=(
            str(self.path), self.submission.canonical_bytes(), grant.grant_id))
        process.start()
        process.join(30)
        if process.is_alive():
            process.terminate()
            process.join(10)
            self.fail("crash worker did not complete")
        self.assertEqual(process.exitcode, 23)
        restarted = self.open(controller="controller-2")
        with self.assertRaisesRegex(AdmissionDenied, "grant_not_issued"):
            restarted.consume(grant.grant_id, current_binding=self.submission, now=LATER)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT state,tokens,aiu,seconds FROM attempts").fetchone(),
                             ("consumed", 100, 10, 100))
            self.assertEqual(db.execute("SELECT state FROM batches").fetchone(), ("aborted",))
            self.assertIsNotNone(db.execute("SELECT receipt FROM grants").fetchone()[0])

    def test_two_independent_connections_share_one_use(self) -> None:
        grant = self.issue()
        second = self.open(join=True)
        second.consume(grant.grant_id, current_binding=self.submission, now=LATER)
        self.deny_consume(grant.grant_id, "grant_not_issued")

    def test_two_processes_racing_consumption_produce_exactly_one_receipt(self) -> None:
        grant = self.issue()
        context = multiprocessing.get_context("spawn")
        ready, results, start = context.Queue(), context.Queue(), context.Event()
        processes = [context.Process(target=race_consume, args=(
            str(self.path), self.submission.canonical_bytes(), grant.grant_id,
            ready, start, results)) for _ in range(2)]
        try:
            for process in processes:
                process.start()
            self.assertEqual([ready.get(timeout=30) for _ in processes], ["ready", "ready"])
            start.set()
            outcomes = [results.get(timeout=30) for _ in processes]
            self.assertCountEqual(outcomes, ["consumed", "grant_not_issued"])
            for process in processes:
                process.join(30)
                self.assertEqual(process.exitcode, 0)
        finally:
            start.set()
            for process in processes:
                if process.is_alive():
                    process.terminate()
                    process.join(10)
            ready.close()
            results.close()
        self.deny_consume(grant.grant_id, "grant_not_issued")

    def test_required_write_failure_is_terminal_and_has_bounded_error(self) -> None:
        grant = self.issue()
        # Fault injection into a real connection, not a mock transaction/ledger.
        self.ledger._connection.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE
            else sqlite3.SQLITE_OK)
        error = self.deny_consume(grant.grant_id, "ledger_integrity_failure")
        self.assertEqual(error.decision.outcome, "abort_batch")
        self.ledger._connection.set_authorizer(None)
        self.deny_consume(grant.grant_id, "ledger_aborted")
        restarted = self.open(controller="controller-2")
        with self.assertRaisesRegex(AdmissionDenied, "grant_not_issued"):
            restarted.consume(grant.grant_id, current_binding=self.submission, now=LATER)

    def test_commit_failure_never_returns_receipt(self) -> None:
        grant = self.issue()
        self.ledger._connection.set_authorizer(
            lambda action, argument, *_: sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_TRANSACTION and argument == "COMMIT" else sqlite3.SQLITE_OK)
        self.deny_consume(grant.grant_id, "ledger_integrity_failure")
        self.ledger._connection.set_authorizer(None)
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT receipt FROM grants").fetchone(), (None,))
        self.deny_consume(grant.grant_id, "ledger_aborted")

    def test_corrupt_grant_and_cross_table_bindings_abort(self) -> None:
        corruptions = (
            ("UPDATE grants SET record=?", ('{"secret":"never-echo-this"}',)),
            ("UPDATE grants SET submission_digest=?", (sha256(b"wrong"),)),
            ("UPDATE grants SET assessment=?", ('{}',)),
            ("UPDATE attempts SET task_id=?", ("different-task",)),
            ("UPDATE attempts SET tokens=?", (99,)),
            ("UPDATE grants SET receipt=?", ('{}',)),
            ("PRAGMA user_version=999", ()),
            ("DELETE FROM metadata", ()),
            ("PRAGMA ignore_check_constraints=ON", ()),
        )
        for statement, parameters in corruptions:
            with self.subTest(statement=statement), tempfile.TemporaryDirectory() as directory:
                path = Path(directory).resolve() / "db"
                with Ledger(path, controller_instance_id="controller-1") as ledger:
                    self.register(ledger=ledger)
                    grant = ledger.issue(self.submission, self.assessment, now=NOW)
                    with closing(sqlite3.connect(path)) as db, db:
                        db.execute(statement, parameters)
                        if statement.startswith("PRAGMA ignore"):
                            db.execute("UPDATE grants SET state='unknown'")
                    with self.assertRaises(AdmissionDenied) as caught:
                        ledger.consume(grant.grant_id, current_binding=self.submission, now=LATER)
                    self.assertEqual(caught.exception.decision.outcome, "abort_batch")
                    self.assertNotIn("never-echo-this", str(caught.exception))

    def test_corrupt_database_and_missing_join_fail_closed(self) -> None:
        self.ledger.close()
        self.path.write_bytes(b"corrupt-synthetic-secret")
        with self.assertRaisesRegex(AdmissionDenied, "^ledger_initialization_failed$"):
            self.open()
        with self.assertRaisesRegex(AdmissionDenied, "^ledger_initialization_failed$"):
            Ledger(self.path.with_name("missing"), controller_instance_id="controller-1",
                   join_existing=True)

    def test_missing_live_database_and_invalid_paths_fail_closed(self) -> None:
        grant = self.issue()
        self.ledger._connection.close()
        self.path.unlink()
        self.assertEqual(self.deny_consume(grant.grant_id, "ledger_integrity_failure")
                         .decision.outcome, "abort_batch")
        for path in (Path("relative.sqlite"), self.path.parent,
                     self.path.parent / ".." / "escape.sqlite"):
            with self.subTest(path=path), self.assertRaisesRegex(
                    AdmissionDenied, "ledger_initialization_failed"):
                Ledger(path, controller_instance_id="controller-1")

    def test_wrong_controller_join_and_issue_abort(self) -> None:
        with self.assertRaisesRegex(AdmissionDenied, "ledger_initialization_failed"):
            self.open(join=True, controller="controller-2")
        submission = replace(self.submission, controller_instance_id="controller-2")
        with self.assertRaisesRegex(AdmissionDenied, "controller_mismatch"):
            self.ledger.issue(submission, advice(submission), now=NOW)
        with self.assertRaisesRegex(AdmissionDenied, "ledger_aborted"):
            self.issue()

    def test_database_file_substitution_fails_closed(self) -> None:
        grant = self.issue()
        # Windows disallows renaming an open SQLite file: close its OS handle only.
        # Reconnect to that same original file after moving it. The ledger retains
        # its anchors and must detect substitution, not just a closed connection.
        self.ledger._connection.close()
        original = self.path.with_name("original.sqlite")
        self.path.rename(original)
        self.path.write_bytes(original.read_bytes())
        self.path.chmod(0o600)
        self.ledger._connection = sqlite3.connect(original, isolation_level=None)
        error = self.deny_consume(grant.grant_id, "ledger_path_substituted")
        self.assertEqual(error.decision.outcome, "abort_batch")

    def test_parent_directory_substitution_fails_closed(self) -> None:
        grant = self.issue()
        self.ledger._connection.close()
        parent = self.path.parent
        moved = parent.with_name(parent.name + "-moved")
        parent.rename(moved)
        try:
            parent.mkdir(mode=0o700)
            self.path.write_bytes((moved / self.path.name).read_bytes())
            self.path.chmod(0o600)
            self.ledger._connection = sqlite3.connect(moved / self.path.name, isolation_level=None)
            self.assertEqual(self.deny_consume(grant.grant_id, "ledger_path_substituted")
                             .decision.outcome, "abort_batch")
        finally:
            self.ledger._connection.close()
            self.path.unlink()
            parent.rmdir()
            moved.rename(parent)

    def test_unsafe_sidefile_is_rejected_before_sqlite_uses_it(self) -> None:
        grant = self.issue()
        side = Path(str(self.path) + "-journal")
        side.mkdir()
        self.addCleanup(side.rmdir)
        self.assertEqual(self.deny_consume(grant.grant_id, "unsafe_ledger_path")
                         .decision.outcome, "abort_batch")

    def test_reparse_point_is_rejected_without_following_it(self) -> None:
        grant = self.issue()
        original = Path.lstat

        def reparse(path: Path) -> object:
            result = original(path)
            if path == self.path:
                class ReparseStat:
                    st_mode = result.st_mode
                    st_file_attributes = 0x400
                return ReparseStat()
            return result

        with patch.object(Path, "lstat", reparse):
            self.assertEqual(self.deny_consume(grant.grant_id, "unsafe_ledger_path")
                             .decision.outcome, "abort_batch")

    def test_symbolic_link_is_rejected_without_following_it(self) -> None:
        grant = self.issue()
        original = Path.lstat

        def symlink(path: Path) -> os.stat_result:
            result = original(path)
            if path == self.path:
                attributes = list(result)
                attributes[0] = stat.S_IFLNK | 0o600
                return os.stat_result(attributes)
            return result

        # lstat fault injection is portable without Windows CreateSymbolicLink privilege.
        with patch.object(Path, "lstat", symlink):
            self.assertEqual(self.deny_consume(grant.grant_id, "unsafe_ledger_path")
                             .decision.outcome, "abort_batch")

    def test_hardlinked_ledger_is_rejected(self) -> None:
        grant = self.issue()
        alias = self.path.with_name("alias.sqlite")
        os.link(self.path, alias)
        self.assertEqual(self.deny_consume(grant.grant_id, "unsafe_ledger_path")
                         .decision.outcome, "abort_batch")

    def test_unknown_attempt_and_batch_do_not_create_state(self) -> None:
        with self.assertRaisesRegex(AdmissionDenied, "unknown_attempt"):
            self.ledger.invalidate_attempt("absent", reason="cancelled")
        with self.assertRaisesRegex(AdmissionDenied, "unknown_batch"):
            self.ledger.abort_batch("absent", reason="cancelled")
        self.issue()


class OfflineEntrypointTests(unittest.TestCase):
    def test_imports_and_readiness_work_without_site_packages_or_network(self) -> None:
        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
def deny(event, args):
    if event.startswith(('socket.', 'subprocess.', 'sqlite3.connect')):
        raise AssertionError(event)
sys.addaudithook(deny)
import authorization, authorization_ledger
assert not any(n.startswith(('copilot', 'deepeval')) for n in sys.modules)
print(authorization.live_readiness().canonical_bytes().decode())
"""
        result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(EVAL)],
                                capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["execution_ready"])

    def test_readiness_cli_exits_two_without_staging_or_ledger_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-I", "-S", str(EVAL / "authorization.py"), "check-readiness"],
                cwd=directory, capture_output=True, text=True, check=False, timeout=20)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout),
                             json.loads(live_readiness().canonical_bytes()))
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
