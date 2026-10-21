"""Offline canonical policy and single-job contracts; no SDK or model calls."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, fields, replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch


EVAL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EVAL / "python"))

from agile_eval.authorization import (  # noqa: E402
    Assessment, BatchEnvelope, BLOCKERS, Budget, Decision, Identities, InvalidRecord,
    JobAuthorization, Operation, PlanSubmission, Readiness, SELECTED_TASKS,
    MAX_JSON_BYTES, TASK05, evaluate, live_readiness, sha256,
)


NOW = "2026-10-20T12:00:00Z"
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
        3, 3, Budget(300, 30, 300),
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


class RecordTests(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope, self.submission, self.assessment = records()

    def test_strict_roundtrip_for_every_record(self) -> None:
        values = (self.envelope, self.submission, self.assessment,
                  self.submission.identities, self.submission.budget,
                  self.submission.operations[0], Decision("block_task", ("held",)),
                  live_readiness())
        for value in values:
            with self.subTest(record=type(value).__name__):
                self.assertEqual(type(value).from_json(value.canonical_bytes()), value)
                self.assertEqual(type(value).from_dict(json.loads(value.canonical_bytes())), value)
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, fields(value)[0].name, None)

    def test_encoded_limit_is_consistent_for_construction_dict_json_and_canonical(self) -> None:
        submission = replace(self.submission, plan_path="/native/" + "東京" * 100,
                             operations=tuple(replace(o, max_bytes=1024)
                                              for o in self.submission.operations))
        encoded = submission.canonical_bytes()
        wire = json.loads(encoded)
        compact_utf8 = json.dumps(wire, ensure_ascii=False, separators=(",", ":"))
        self.assertLess(len(compact_utf8.encode("utf-8")), len(encoded) - 1)
        with patch("agile_eval.authorization.MAX_JSON_BYTES", len(encoded)):
            self.assertEqual(replace(submission), submission)
            self.assertEqual(PlanSubmission.from_dict(wire), submission)
            self.assertEqual(PlanSubmission.from_json(encoded), submission)
            self.assertEqual(submission.canonical_bytes(), encoded)
        with patch("agile_eval.authorization.MAX_JSON_BYTES", len(encoded) - 1):
            for name, build in (
                ("constructor", lambda: replace(submission)),
                ("dict", lambda: PlanSubmission.from_dict(wire)),
                ("json", lambda: PlanSubmission.from_json(compact_utf8)),
                ("canonical", submission.canonical_bytes),
            ):
                with self.subTest(entrypoint=name), self.assertRaisesRegex(
                        InvalidRecord, "^invalid_record$"):
                    build()

    def test_aggregate_operations_exceed_real_encoded_limit(self) -> None:
        operations = tuple(replace(self.submission.operations[0],
                                   target="/" + str(i).zfill(2) + "x" * 4093)
                           for i in range(32))
        wire = json.loads(self.submission.canonical_bytes())
        wire["operations"] = [asdict(operation) for operation in operations]
        self.assertGreater(len(json.dumps(wire).encode("utf-8")), MAX_JSON_BYTES)
        with self.assertRaisesRegex(InvalidRecord, "^invalid_record$"):
            replace(self.submission, operations=operations)
        with self.assertRaisesRegex(InvalidRecord, "^invalid_record$"):
            PlanSubmission.from_dict(wire)

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
        self.assertEqual(evaluate(self.envelope, self.submission, self.assessment, now=NOW),
                         Decision("eligible", ("policy_eligible_not_execution_ready",)))
        self.assertEqual(live_readiness(), Readiness(False, "not_ready", BLOCKERS))
        with self.assertRaises(InvalidRecord):
            replace(live_readiness(), execution_ready=True)
        self.assertIn("native_atomic_admission_unverified", BLOCKERS)
        self.assertIn("controller_state_isolation_unverified", BLOCKERS)
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

    def test_operation_scope_with_fresh_advice(self) -> None:
        for allowed in self.submission.operations:
            cases = (
                ("target", replace(allowed, target=allowed.target + ".other"), False),
                ("actor", replace(allowed, actor_id="other-writer"), False),
                ("excess_bytes", replace(allowed, max_bytes=allowed.max_bytes + 1), False),
                ("exact_limit", replace(allowed), True),
                ("narrower", replace(allowed, max_bytes=allowed.max_bytes - 1), True),
            )
            for name, operation, fits in cases:
                with self.subTest(kind=allowed.kind, case=name):
                    submission = replace(self.submission, operations=(operation,))
                    assessment = advice(submission)
                    self.assertEqual(assessment.submission_digest, submission.digest)
                    self.assertEqual(
                        evaluate(self.envelope, submission, assessment, now=NOW),
                        Decision("eligible", ("policy_eligible_not_execution_ready",))
                        if fits else Decision("block_task", ("operation_out_of_scope",)))

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


class JobAuthorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.envelope, self.submission, self.assessment = records()
        self.job = JobAuthorization(self.submission)

    def attempt(self, **changes: object) -> Decision:
        args = dict(envelope=self.envelope, current_binding=self.submission,
                    assessment=self.assessment, expected_digest=self.envelope.digest,
                    approval_reference=self.envelope.approval_reference, now=NOW)
        args.update(changes)
        return self.job.attempt(**args)

    def test_starts_unauthorized_and_requires_explicit_independent_approval(self) -> None:
        self.assertEqual(self.job.state, "UNAUTHORIZED")
        self.assertEqual(self.job.attempts, 0)
        self.assertIsNone(self.job.reserved_budget)
        with self.assertRaises(TypeError):
            self.job.attempt(self.envelope, self.submission, self.assessment, now=NOW)
        self.assertEqual(self.job.state, "UNAUTHORIZED")
        self.assertEqual(self.attempt().outcome, "eligible")
        self.assertEqual((self.job.state, self.job.attempts), ("USED", 1))
        self.assertEqual(self.job.reserved_budget, self.submission.budget)
        self.assertEqual(self.attempt().reason_codes, ("job_already_used",))
        self.assertFalse(live_readiness().execution_ready)

    def test_wrong_approval_identity_or_digest_is_terminal(self) -> None:
        for changes in ({"expected_digest": sha256(b"forged")},
                        {"approval_reference": "forged-adjacent-approval"}):
            with self.subTest(changes=changes):
                self.job = JobAuthorization(self.submission)
                self.assertEqual(self.attempt(**changes).reason_codes, ("approval_mismatch",))
                self.assertEqual(self.job.state, "ABORTED")
                self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    def test_every_envelope_field_mutation_rejects_original_approval(self) -> None:
        changes = {
            "version": 2, "batch_id": "batch-2", "approval_reference": "approval-2",
            "valid_from": "2026-10-20T11:59:59Z", "valid_until": "2026-10-20T14:00:00Z",
            "selected_tasks": (TASK05,), "permitted_tasks": SELECTED_TASKS,
            "permitted_identities": (replace(self.submission.identities, model_id="gpt-6-astra"),),
            "permitted_operations": (self.submission.operations[0],
                                     replace(self.submission.operations[1], max_bytes=8191)),
            "assessor_id": "assessor-2", "max_attempts": 4, "max_attempts_per_task": 2,
            "budget": Budget(301, 30, 300),
        }
        self.assertEqual(set(changes), {field.name for field in fields(BatchEnvelope)})
        for name, value in changes.items():
            with self.subTest(field=name):
                self.job = JobAuthorization(self.submission)
                # Deliberately malformed frozen input must also be revalidated.
                modified = replace(self.envelope)
                object.__setattr__(modified, name, value)
                self.assertEqual(self.attempt(envelope=modified).outcome, "abort_batch")
                self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    def test_every_binding_mutation_aborts_even_with_fresh_advice(self) -> None:
        for name, changed in mutations(self.submission).items():
            with self.subTest(field=name):
                self.job = JobAuthorization(self.submission)
                self.assertEqual(self.attempt(current_binding=changed, assessment=advice(changed))
                                 .reason_codes, ("current_binding_mismatch",))
                self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    def test_constructor_snapshots_exact_binding(self) -> None:
        object.__setattr__(self.submission, "plan_sha256", sha256(b"changed"))
        self.assertEqual(self.attempt().reason_codes, ("current_binding_mismatch",))
        with self.assertRaises(InvalidRecord):
            JobAuthorization({})

    def test_blocked_advice_uses_attempt_and_cannot_be_replaced(self) -> None:
        for assessment in (None, replace(self.assessment, outcome="uncertain"),
                           replace(self.assessment, outcome="out_of_scope"),
                           replace(self.assessment, submission_digest=sha256(b"other")),
                           replace(self.assessment, reference="different"),
                           replace(self.assessment, assessor_id="writer")):
            with self.subTest(assessment=assessment):
                self.job = JobAuthorization(self.submission)
                self.assertEqual(self.attempt(assessment=assessment).outcome, "block_task")
                self.assertEqual((self.job.state, self.job.attempts), ("USED", 1))
                self.assertIsNone(self.job.reserved_budget)
                self.assertEqual(self.attempt().reason_codes, ("job_already_used",))

    def test_expiry_and_not_yet_valid_use_attempt_without_reserving_budget(self) -> None:
        for now in ("2026-10-20T11:59:59Z", self.envelope.valid_until):
            with self.subTest(now=now):
                self.job = JobAuthorization(self.submission)
                self.assertEqual(self.attempt(now=now).reason_codes, ("envelope_time_invalid",))
                self.assertEqual(self.job.attempts, 1)
                self.assertIsNone(self.job.reserved_budget)
                self.assertEqual(self.attempt().reason_codes, ("job_already_used",))

    def test_each_budget_dimension_is_bounded_and_never_refunded(self) -> None:
        for dimension in ("tokens", "aiu", "seconds"):
            for excess in (0, 1):
                with self.subTest(dimension=dimension, excess=excess):
                    budget = replace(self.submission.budget, **{
                        dimension: getattr(self.envelope.budget, dimension) + excess})
                    submission = replace(self.submission, budget=budget)
                    self.job = JobAuthorization(submission)
                    result = self.attempt(current_binding=submission, assessment=advice(submission))
                    self.assertEqual(result.outcome, "block_task" if excess else "eligible")
                    reserved = None if excess else budget
                    self.assertEqual(self.job.reserved_budget, reserved)
                    self.job.abort("response_lost")
                    self.job.abort("cancelled")
                    self.assertEqual((self.job.state, self.job.attempts), ("ABORTED", 1))
                    self.assertEqual(self.job.reserved_budget, reserved)
                    self.assertEqual(self.job.terminal_reason, "response_lost")
                    self.assertEqual(self.attempt().reason_codes, ("job_aborted",))

    def test_two_local_threads_can_use_only_one_attempt(self) -> None:
        ready = Barrier(2)

        def attempt() -> str:
            ready.wait(timeout=5)
            return self.attempt().outcome

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(results, ["eligible", "block_task"])
        self.assertEqual(self.job.attempts, 1)
        self.assertEqual(self.job.reserved_budget, self.submission.budget)

    def test_invalid_control_records_latch_and_reinstantiation_restores_no_authority(self) -> None:
        for changes in ({"envelope": {}}, {"current_binding": {}}, {"assessment": {}},
                        {"assessment": Decision("eligible", ("forged",))},
                        {"expected_digest": None}, {"approval_reference": "secret\ninvalid"},
                        {"now": "invalid"}):
            with self.subTest(changes=changes):
                self.job = JobAuthorization(self.submission)
                self.assertEqual(self.attempt(**changes),
                                 Decision("abort_batch", ("invalid_control_record",)))
                self.assertEqual(self.attempt().reason_codes, ("job_aborted",))
                self.job = JobAuthorization(PlanSubmission.from_json(
                    self.submission.canonical_bytes()))
                self.assertEqual((self.job.state, self.job.attempts), ("UNAUTHORIZED", 0))
                with self.assertRaises(TypeError):
                    self.job.attempt(self.envelope, self.submission, self.assessment, now=NOW)
                # A fresh trusted approval invocation, not a restored record.
                self.assertEqual(self.attempt().outcome, "eligible")

    def test_abort_before_approval_is_terminal_even_with_invalid_reason(self) -> None:
        self.job.abort("synthetic-sensitive\ninvalid")
        self.assertEqual(self.job.terminal_reason, "invalid_control_record")
        self.assertEqual(self.attempt().reason_codes, ("job_aborted",))
        self.assertEqual(self.job.attempts, 0)
        self.assertIsNone(self.job.reserved_budget)

    def test_policy_integrity_failure_latches_abort(self) -> None:
        envelope = replace(self.envelope, batch_id="different-batch")
        self.assertEqual(self.attempt(envelope=envelope, expected_digest=envelope.digest)
                         .reason_codes, ("envelope_binding_mismatch",))
        self.assertEqual(self.job.state, "ABORTED")
        self.assertEqual(self.attempt().reason_codes, ("job_aborted",))


class OfflineEntrypointTests(unittest.TestCase):
    def test_fresh_process_does_not_restore_authority_from_adjacent_jsonl_or_results(self) -> None:
        envelope, submission, assessment = records()
        script = """
import sys
sys.path.insert(0, sys.argv[1])
from agile_eval.authorization import Assessment, BatchEnvelope, JobAuthorization, PlanSubmission
envelope = BatchEnvelope.from_json(sys.argv[2])
submission = PlanSubmission.from_json(sys.argv[3])
assessment = Assessment.from_json(sys.argv[4])
job = JobAuthorization(submission)
assert job.state == 'UNAUTHORIZED' and job.attempts == 0
assert job.reserved_budget is None
try:
    job.attempt(envelope, submission, assessment, now=envelope.valid_from)
except TypeError:
    pass
else:
    raise AssertionError('restored authority without independent approval')
assert job.state == 'UNAUTHORIZED'
"""
        with tempfile.TemporaryDirectory() as directory:
            for name in ("approval.json", "results.json", "audit.jsonl"):
                Path(directory, name).write_text(json.dumps({
                    "state": "USED", "approved": True, "execution_ready": True,
                    "expected_digest": envelope.digest,
                    "approval_reference": envelope.approval_reference,
                }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-c", script, str(EVAL / "python"),
                 envelope.canonical_bytes().decode(), submission.canonical_bytes().decode(),
                 assessment.canonical_bytes().decode()], cwd=directory,
                capture_output=True, text=True, check=False, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_imports_and_readiness_work_without_site_packages_or_network(self) -> None:
        script = """
import json, sys
sys.path.insert(0, sys.argv[1])
def deny(event, args):
    if event.startswith(('socket.', 'subprocess.', 'sqlite3.connect')):
        raise AssertionError(event)
sys.addaudithook(deny)
from agile_eval import authorization
assert not any(n.startswith(('copilot', 'deepeval')) for n in sys.modules)
print(authorization.live_readiness().canonical_bytes().decode())
"""
        result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(EVAL / "python")],
                                capture_output=True, text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["execution_ready"])

    def test_readiness_cli_exits_two_without_staging_or_state_creation(self) -> None:
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
