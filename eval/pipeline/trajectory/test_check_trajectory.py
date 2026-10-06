"""Offline protocol regressions for the event schema, emitters, and trajectory."""

import importlib.util
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = ROOT / "eval" / "pipeline" / "trajectory" / "check-trajectory.py"
spec = importlib.util.spec_from_file_location("check_trajectory", CHECKER_PATH)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


RUN_ID = "01914e2a-9b1c-7c3d-8e4f-1a2b3c4d5e6f"


def event(kind, phase, index, **extra):
    value = {
        "schema_version": 2,
        "timestamp": f"2026-10-06T08:00:{index:02d}.000Z",
        "run_id": RUN_ID,
        "agent": "dev-lead",
        "phase": phase,
        "event_type": kind,
    }
    value.update(extra)
    return value

def disabled_cost():
    return {"status": "disabled", "reason": "disabled for synthetic test"}


def measured_cost(unmetered=False):
    usd = None if unmetered else 0.01
    metric_set = {
        "calls": 0,
        "tokens_in": 120,
        "tokens_out": 0,
        "tokens_reasoning": 0,
        "tokens_cache_read": 0,
        "tokens_total": 120,
        "aiu": 0.0,
        "duration_ms": 0,
        "models": [],
        "usd": usd,
    }
    return {
        "status": "unmetered" if unmetered else "measured",
        "source": "collect-usage.py",
        "usage": {
            "session_id": "synthetic-session",
            "totals": dict(metric_set),
            "by_phase": {"coding": dict(metric_set)},
            "by_agent": {"dev-lead": dict(metric_set)},
            "usd": usd,
            "usd_basis": "not-metered" if unmetered else "rate:0 USD per AIU",
            "unattributed": dict(metric_set),
            "warnings": [],
            "breaches": [],
        },
    }


def successful_run():
    events = [
        event("run_start", "intake", 0, payload={
            "requirement_summary": "Synthetic trajectory test",
            "profile_loaded": True,
        }),
        event("phase_start", "research", 1),
        event("phase_complete", "research", 2, outcome="success"),
        event("phase_start", "coding", 3),
        event("phase_complete", "coding", 4, outcome="success"),
        event("handoff_received", "coding", 5, payload={
            "from_agent": "coding", "sentinel": "IMPLEMENTATION COMPLETE",
        }),
        event("gate_check", "test-bar", 6, outcome="success", payload={
            "gate": "test_bar",
        }),
        event("phase_start", "review-lead", 7),
        event("phase_complete", "review-lead", 8, outcome="success"),
        event("handoff_received", "review-lead", 9, payload={
            "from_agent": "review-lead", "sentinel": "REVIEW COMPLETE",
        }),
        event("gate_check", "review-lead", 10, outcome="success", payload={
            "gate": "review",
        }),
        event("run_complete", "wrap-up", 11, outcome="success", payload={
            "cost_summary": disabled_cost(),
        }),
    ]
    return events


def set_ordered_timestamps(events):
    for index, item in enumerate(events):
        item["timestamp"] = f"2026-10-06T08:00:{index:02d}.000Z"
    return events


def failures(events):
    return {check_id for check_id, required, ok, _detail in checker.run_checks(events)
            if required and not ok}


class TrajectoryContractTests(unittest.TestCase):
    def test_archived_unversioned_event_is_not_current_v2_compliance_evidence(self):
        legacy = event("phase_start", "coding", 1)
        legacy.pop("schema_version")
        errors = checker._event_schema_errors([legacy])
        self.assertTrue(any("schema_version" in error for error in errors))

    def test_v2_schema_cannot_reinterpret_pre_cutoff_historical_event(self):
        old_timestamp = event("phase_start", "coding", 1)
        old_timestamp["timestamp"] = "2026-10-05T21:12:20.999Z"
        errors = checker._event_schema_errors([old_timestamp])
        self.assertTrue(any("UTC cutoff" in error for error in errors))

    def test_unversioned_and_pre_cutoff_logs_are_classified_by_cli_without_rewriting(self):
        archived = event("phase_start", "coding", 1)
        unversioned = dict(archived)
        unversioned.pop("schema_version")
        old_v2 = dict(archived, timestamp="2026-10-05T21:12:20.999Z")
        for contents in (unversioned, old_v2):
            with self.subTest(contents=contents):
                original = (json.dumps(contents, separators=(",", ":")) + "\n").encode()
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "archived.events.jsonl"
                    path.write_bytes(original)
                    result = subprocess.run(
                        [sys.executable, str(CHECKER_PATH), str(path)],
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("UNSUPPORTED historical/unsupported", result.stdout)
                    self.assertIn("not current v2 compliance evidence", result.stdout)
                    self.assertIn("Timestamps do not authenticate archive provenance", result.stdout)
                    self.assertIn("FAIL  schema-valid", result.stdout)
                    self.assertEqual(path.read_bytes(), original)

    def test_supervisor_only_successful_trajectory_passes(self):
        self.assertEqual(failures(successful_run()), set())

    def test_schema_rejects_workers_unknown_events_and_self_reported_cost(self):
        cases = []
        worker = successful_run()
        worker[3]["agent"] = "coding"
        cases.append(("worker event", worker))

        unsupported = successful_run()
        unsupported[1]["event_type"] = "cost_summary"
        cases.append(("unsupported event", unsupported))

        invented_cost = successful_run()
        invented_cost[-1]["tokens_in"] = 10
        cases.append(("self-reported usage", invented_cost))

        for name, events in cases:
            with self.subTest(name=name):
                self.assertIn("schema-valid", failures(events))

    def test_run_bookends_and_identity_are_enforced(self):
        events = successful_run()
        events[0]["run_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
        self.assertIn("single-run-id", failures(events))

        events = successful_run()[1:]
        self.assertIn("run-bookends", failures(events))

        events = successful_run()
        events.insert(1, dict(events[0]))
        set_ordered_timestamps(events)
        self.assertIn("run-bookends", failures(events))

    def test_event_specific_required_payload_fields_are_enforced(self):
        events = successful_run()
        next(item for item in events if item.get("payload", {}).get("gate") == "review")[
            "payload"].pop("gate")
        self.assertIn("schema-valid", failures(events))

    def test_schema_rejects_arbitrary_payload_fields_and_sensitive_strings(self):
        unsupported = successful_run()
        unsupported[0]["payload"]["raw_response"] = "synthetic only"
        self.assertIn("schema-valid", failures(unsupported))

        for field, value in (
            ("args_summary", "sent to alice@example.test"),
            ("payload", {"requirement_summary": "password=fixtureSecret123", "profile_loaded": True}),
        ):
            with self.subTest(field=field):
                events = successful_run()
                if field == "args_summary":
                    events[1][field] = value
                else:
                    events[0][field] = value
                self.assertIn("schema-valid", failures(events))

    def test_phase_window_diagnostics_do_not_echo_untrusted_phase_values(self):
        events = successful_run()
        events[3]["phase"] = "UNTRUSTED_PHASE_CONTENT"
        _windows, errors = checker._windows(events)
        self.assertTrue(errors)
        self.assertNotIn("UNTRUSTED_PHASE_CONTENT", " ".join(errors))

    def test_rejects_invalid_event_shapes_without_crashing(self):
        cases = [
            [None],
            ["not-an-event"],
            [{"event_type": "run_start"}],
            successful_run(),
        ]
        cases[-1][2]["timestamp"] = "not-a-timestamp"
        cases[-1][-1]["payload"]["cost_summary"] = {"status": "measured"}
        for events in cases:
            with self.subTest(events=events[:1]):
                self.assertIn("schema-valid", failures(events))

        wrong_type = successful_run()
        wrong_type[3]["phase"] = []
        self.assertIn("schema-valid", failures(wrong_type))

        impossible_integer = successful_run()
        impossible_integer[0]["duration_ms"] = 10 ** 10000
        self.assertIn("schema-valid", failures(impossible_integer))

    def test_rejects_out_of_order_timestamps_and_invalid_outcomes(self):
        events = successful_run()
        events[4]["timestamp"], events[3]["timestamp"] = (
            events[3]["timestamp"], events[4]["timestamp"])
        self.assertIn("chronological-timestamps", failures(events))

        events = successful_run()
        events[4]["outcome"] = "skipped"
        self.assertIn("schema-valid", failures(events))

    def test_rejects_reversed_and_overlapping_phase_windows(self):
        reversed_window = successful_run()
        reversed_window[1]["event_type"] = "phase_complete"
        reversed_window[1]["outcome"] = "success"
        reversed_window[2]["event_type"] = "phase_start"
        reversed_window[2].pop("outcome", None)
        self.assertIn("phase-windows", failures(reversed_window))

        overlapping = successful_run()
        overlapping.insert(4, event("phase_start", "infrastructure", 4))
        set_ordered_timestamps(overlapping)
        self.assertIn("phase-windows", failures(overlapping))

    def test_rejects_research_after_implementation(self):
        events = successful_run()
        research = events[1:3]
        del events[1:3]
        events[5:5] = research
        set_ordered_timestamps(events)
        self.assertIn("research-before-implementation", failures(events))

    def test_rejects_failed_gates_on_a_successful_run(self):
        events = successful_run()
        for item in events:
            if item["event_type"] == "gate_check":
                item["outcome"] = "fail"
        self.assertIn("unresolved-gate-failure", failures(events))

    def test_failed_test_bar_can_be_recovered_by_fix_and_fresh_pass(self):
        events = successful_run()
        events[6]["outcome"] = "fail"
        events[7:7] = [
            event("phase_start", "coding", 7),
            event("phase_complete", "coding", 8, outcome="success"),
            event("handoff_received", "coding", 9, payload={
                "from_agent": "coding", "sentinel": "IMPLEMENTATION COMPLETE",
            }),
            event("gate_check", "test-bar", 10, outcome="success", payload={
                "gate": "test_bar",
            }),
        ]
        set_ordered_timestamps(events)
        self.assertEqual(failures(events), set())

    def test_failed_review_can_be_recovered_after_reverification(self):
        events = successful_run()
        events[10]["outcome"] = "fail"
        events[-1:-1] = [
            event("phase_start", "coding", 11),
            event("phase_complete", "coding", 12, outcome="success"),
            event("handoff_received", "coding", 13, payload={
                "from_agent": "coding", "sentinel": "IMPLEMENTATION COMPLETE",
            }),
            event("gate_check", "test-bar", 14, outcome="success", payload={
                "gate": "test_bar",
            }),
            event("phase_start", "review-lead", 15),
            event("phase_complete", "review-lead", 16, outcome="success"),
            event("handoff_received", "review-lead", 17, payload={
                "from_agent": "review-lead", "sentinel": "REVIEW COMPLETE",
            }),
            event("gate_check", "review-lead", 18, outcome="success", payload={
                "gate": "review",
            }),
        ]
        set_ordered_timestamps(events)
        self.assertEqual(failures(events), set())

    def test_failed_review_is_an_honest_terminal_outcome(self):
        events = successful_run()
        events[10]["outcome"] = "fail"
        events[-1]["outcome"] = "fail"
        events[-1]["payload"]["termination_reason"] = "Review found a blocking issue"
        self.assertEqual(failures(events), set())

    def test_requires_verification_before_review_and_invalidates_it_after_fixes(self):
        premature_review = successful_run()
        review_start = premature_review.pop(7)
        review_complete = premature_review.pop(7)
        premature_review.insert(6, review_start)
        premature_review.insert(7, review_complete)
        set_ordered_timestamps(premature_review)
        self.assertIn("verification-before-review", failures(premature_review))

        stale_verification = successful_run()
        stale_verification[7:7] = [
            event("phase_start", "coding", 7),
            event("phase_complete", "coding", 8, outcome="success"),
        ]
        set_ordered_timestamps(stale_verification)
        self.assertIn("verification-before-review", failures(stale_verification))

        unverified_review = successful_run()
        unverified_review.pop(6)
        unverified_review[-1]["outcome"] = "fail"
        unverified_review[-1]["payload"]["termination_reason"] = (
            "Review started without a successful verification gate")
        set_ordered_timestamps(unverified_review)
        self.assertIn("verification-before-review", failures(unverified_review))

    def test_explicit_not_applicable_test_bar_is_accepted(self):
        events = successful_run()
        gate = next(item for item in events
                    if item["event_type"] == "gate_check"
                    and item["payload"]["gate"] == "test_bar")
        gate["outcome"] = "partial"
        gate["payload"].update({
            "applicability": "not_applicable",
            "reason": "No runnable application or changed tests",
        })
        self.assertEqual(failures(events), set())

    def test_honest_early_stop_does_not_require_unreached_stages(self):
        for outcome in ("fail", "partial"):
            with self.subTest(outcome=outcome):
                events = [
                    event("run_start", "intake", 0, payload={
                        "requirement_summary": "Synthetic early stop",
                        "profile_loaded": True,
                    }),
                    event("phase_start", "research", 1),
                    event("phase_complete", "research", 2, outcome=outcome),
                    event("run_complete", "research", 3, outcome=outcome, payload={
                        "termination_reason": "Research could not verify the required input",
                        "cost_summary": disabled_cost(),
                    }),
                ]
                self.assertEqual(failures(events), set())

    def test_non_successful_termination_requires_a_reason(self):
        events = [
            event("run_start", "intake", 0, payload={
                "requirement_summary": "Synthetic early stop",
                "profile_loaded": True,
            }),
            event("run_complete", "intake", 1, outcome="partial", payload={
                "cost_summary": disabled_cost(),
            }),
        ]
        self.assertIn("schema-valid", failures(events))

    def test_measured_and_unmetered_cost_summaries_are_distinct(self):
        events = successful_run()
        events[-1]["payload"]["cost_summary"] = measured_cost()
        self.assertEqual(failures(events), set())

        events[-1]["payload"]["cost_summary"] = measured_cost(unmetered=True)
        self.assertEqual(failures(events), set())

    def test_schema_requires_cost_status_to_match_every_collector_usd_bucket(self):
        for status, invalid_value in (
            ("measured", None),
            ("unmetered", 0.0),
        ):
            for location in ("usd", "totals", "unattributed", "by_phase", "by_agent"):
                with self.subTest(status=status, location=location):
                    events = successful_run()
                    summary = measured_cost(unmetered=status == "unmetered")
                    usage = summary["usage"]
                    if location in ("usd", "totals", "unattributed"):
                        if location == "usd":
                            usage["usd"] = invalid_value
                        else:
                            usage[location]["usd"] = invalid_value
                    else:
                        bucket = usage[location]
                        next(iter(bucket.values()))["usd"] = invalid_value
                    events[-1]["payload"]["cost_summary"] = summary
                    self.assertTrue(checker._event_schema_errors(events))
                    self.assertIn("schema-valid", failures(events))

    def test_schema_binds_collector_usd_basis_to_cost_status(self):
        for status, invalid_basis in (
            ("measured", "not-metered"),
            ("unmetered", "rate:0 USD per AIU"),
        ):
            with self.subTest(status=status):
                events = successful_run()
                summary = measured_cost(unmetered=status == "unmetered")
                summary["usage"]["usd_basis"] = invalid_basis
                events[-1]["payload"]["cost_summary"] = summary
                self.assertTrue(checker._event_schema_errors(events))

    def test_unavailable_cost_summary_requires_a_reason_and_source(self):
        events = successful_run()
        events[-1]["payload"]["cost_summary"] = {
            "status": "unavailable",
            "source": "collect-usage.py",
            "reason": "Usage store was unavailable",
        }
        self.assertEqual(failures(events), set())

        events[-1]["payload"]["cost_summary"].pop("reason")
        self.assertIn("schema-valid", failures(events))


class EventFileTests(unittest.TestCase):
    def test_malformed_and_ambiguous_json_lines_fail_cleanly(self):
        inputs = [
            '{"event_type":"run_start"}\n',
            '{"run_id":"one","run_id":"two"}\n',
            '{"value":NaN}\n',
            '[]\n',
        ]
        for raw in inputs:
            with self.subTest(raw=raw), tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False,
            ) as handle:
                handle.write(raw)
                path = Path(handle.name)
            self.addCleanup(path.unlink, missing_ok=True)
            output = io.StringIO()
            with redirect_stdout(output):
                result = checker.check_file(path)
            self.assertEqual(result, 1)
            self.assertIn("FAIL", output.getvalue())

    def test_duplicate_property_diagnostic_does_not_echo_untrusted_key(self):
        raw = '{"untrusted-property-name":1,"untrusted-property-name":2}\n'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "duplicate.events.jsonl"
            path.write_text(raw, encoding="utf-8")
            output = io.StringIO()
            with redirect_stdout(output):
                result = checker.check_file(path)
        self.assertEqual(result, 1)
        self.assertIn("duplicate JSON property", output.getvalue())
        self.assertNotIn("untrusted-property-name", output.getvalue())


class EmitterIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pwsh = shutil.which("pwsh")
        cls.bash = os.environ.get("RUNTIME_EVENT_BASH") or shutil.which("bash")
        if os.name == "nt" and not os.environ.get("RUNTIME_EVENT_BASH"):
            git_bash = Path(r"C:\Program Files\Git\bin\bash.exe")
            cls.bash = str(git_bash) if git_bash.is_file() else cls.bash

    def require_emitters(self):
        if not self.pwsh or not self.bash:
            self.skipTest("pwsh and Bash are required to exercise both event emitters")

    def bash_path(self, path):
        if os.name != "nt":
            return str(path)
        result = subprocess.run(
            [self.bash, "-c", 'cygpath -u "$1"', "cygpath", str(path)],
            capture_output=True, text=True, check=True, timeout=10,
        )
        return result.stdout.strip()

    def emit(self, emitter, event_type, phase, temp_dir, outcome=None, payload=None,
             args_summary=None, tool_name=None):
        script_dir = ROOT / "plugins" / "agile-agents-core" / "skills" / "run-event-log" / "scripts"
        env = os.environ.copy()
        env["COPILOT_RUNS_DIR"] = self.bash_path(temp_dir) if emitter == "bash" else str(temp_dir)
        if emitter == "bash":
            env["PYTHON"] = self.bash_path(Path(sys.executable))
        payload_json = json.dumps(payload) if payload is not None else None
        if emitter == "powershell":
            command = [
                self.pwsh, "-NoProfile", "-File", str(script_dir / "emit-event.ps1"),
                "-RunId", RUN_ID, "-Agent", "dev-lead", "-Phase", phase,
                "-EventType", event_type,
            ]
            if outcome:
                command.extend(["-Outcome", outcome])
            if args_summary:
                command.extend(["-ArgsSummary", args_summary])
            if tool_name:
                command.extend(["-ToolName", tool_name])
            if payload_json:
                command.extend(["-Payload", payload_json])
        else:
            script = self.bash_path(script_dir / "emit-event.sh")
            command = [
                self.bash, script, "--run-id", RUN_ID, "--agent", "dev-lead",
                "--phase", phase, "--event-type", event_type,
            ]
            if outcome:
                command.extend(["--outcome", outcome])
            if args_summary:
                command.extend(["--args-summary", args_summary])
            if tool_name:
                command.extend(["--tool-name", tool_name])
            if payload_json:
                command.extend(["--payload-json", payload_json])
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)

    def test_real_emitters_produce_a_valid_supervisor_only_run(self):
        self.require_emitters()
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            events = [
                ("powershell", "run_start", "intake", None, {
                    "requirement_summary": "Synthetic emitter test", "profile_loaded": True,
                }),
                ("powershell", "phase_start", "research", None, None),
                ("bash", "phase_complete", "research", "success", None),
                ("bash", "phase_start", "coding", None, None),
                ("powershell", "phase_complete", "coding", "success", None),
                ("bash", "handoff_received", "coding", None, {
                    "from_agent": "coding", "sentinel": "IMPLEMENTATION COMPLETE",
                }),
                ("powershell", "gate_check", "test-bar", "success", {"gate": "test_bar"}),
                ("bash", "phase_start", "review-lead", None, None),
                ("powershell", "phase_complete", "review-lead", "success", None),
                ("bash", "gate_check", "review-lead", "success", {"gate": "review"}),
                ("powershell", "run_complete", "wrap-up", "success", {
                    "cost_summary": disabled_cost(),
                }),
            ]
            for emitter, kind, phase, outcome, payload in events:
                result = self.emit(emitter, kind, phase, base, outcome, payload)
                self.assertEqual(
                    result.returncode, 0,
                    f"{result.args!r}\n{emitter} {kind} {payload!r}: {result.stdout}{result.stderr}",
                )

            lines = (base / RUN_ID / "events.jsonl").read_text(encoding="utf-8").splitlines()
            produced = [json.loads(line) for line in lines]
            self.assertEqual(failures(produced), set())
            self.assertTrue(all(item["agent"] == "dev-lead" for item in produced))

    def test_both_emitters_reject_worker_owned_events(self):
        self.require_emitters()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script_dir = ROOT / "plugins" / "agile-agents-core" / "skills" / "run-event-log" / "scripts"
            ps_env = os.environ.copy()
            ps_env["COPILOT_RUNS_DIR"] = str(root / "ps")
            ps = subprocess.run([
                self.pwsh, "-NoProfile", "-File", str(script_dir / "emit-event.ps1"),
                "-RunId", RUN_ID, "-Agent", "coding", "-Phase", "coding",
                "-EventType", "phase_start",
            ], env=ps_env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(ps.returncode, 0)

            bash_env = os.environ.copy()
            bash_env["COPILOT_RUNS_DIR"] = self.bash_path(root / "bash")
            bash_env["PYTHON"] = self.bash_path(Path(sys.executable))
            bash = subprocess.run([
                self.bash, self.bash_path(script_dir / "emit-event.sh"),
                "--run-id", RUN_ID, "--agent", "coding", "--phase", "coding",
                "--event-type", "phase_start",
            ], env=bash_env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(bash.returncode, 0)

    def test_both_emitters_reject_sensitive_and_unsupported_input_without_appending(self):
        self.require_emitters()
        cases = [
            ("run_start", "intake", None, {
                "requirement_summary": "Contact alice@example.test",
                "profile_loaded": True,
            }, None, None),
            ("run_complete", "wrap-up", "fail", {
                "termination_reason": "synthetic",
                "cost_summary": {"status": "disabled", "reason": "API_KEY=fixtureValue123"},
            }, None, None),
            ("run_start", "intake", None, {
                "requirement_summary": "safe summary",
                "profile_loaded": True,
                "raw_response": "synthetic output",
            }, None, None),
            ("run_complete", "wrap-up", "fail", {
                "termination_reason": "synthetic",
                "cost_summary": {
                    **measured_cost(),
                    "usage": {
                        **measured_cost()["usage"],
                        "unredacted_output": "synthetic scorer text",
                    },
                },
            }, None, None),
            ("tool_call", "coding", None, None, "Authorization: Bearer fixtureToken12345", "agent"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for emitter in ("powershell", "bash"):
                for index, (kind, phase, outcome, payload, args, tool) in enumerate(cases):
                    with self.subTest(emitter=emitter, case=index):
                        base = root / emitter / str(index)
                        run_dir = base / RUN_ID
                        run_dir.mkdir(parents=True)
                        archive = run_dir / "events.jsonl"
                        original = b"previous event bytes\n"
                        archive.write_bytes(original)
                        result = self.emit(
                            emitter, kind, phase, base, outcome, payload,
                            args_summary=args, tool_name=tool,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(archive.read_bytes(), original)
                        self.assertNotIn("alice@example.test", result.stdout + result.stderr)
                        self.assertNotIn("fixtureValue123", result.stdout + result.stderr)
                        self.assertNotIn("fixtureToken12345", result.stdout + result.stderr)

    def test_both_emitters_preserve_measured_and_unmetered_collector_results(self):
        self.require_emitters()
        for emitter in ("powershell", "bash"):
            for unmetered in (False, True):
                with self.subTest(emitter=emitter, unmetered=unmetered), tempfile.TemporaryDirectory() as temp:
                    usage = measured_cost(unmetered=unmetered)["usage"]
                    usage["warnings"] = [{
                        "scope": "per_phase", "metric": "aiu",
                        "actual": 8.1, "limit": 10.0, "phase": "coding",
                    }]
                    usage["breaches"] = [{
                        "scope": "per_run", "metric": "tokens",
                        "actual": 120, "limit": 100,
                    }]
                    payload = {
                        "termination_reason": "synthetic terminal event",
                        "cost_summary": {
                            "status": "unmetered" if unmetered else "measured",
                            "source": "collect-usage.py",
                            "usage": usage,
                        },
                    }
                    result = self.emit(
                        emitter, "run_complete", "wrap-up", Path(temp),
                        "fail", payload,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    line = (Path(temp) / RUN_ID / "events.jsonl").read_text(
                        encoding="utf-8").splitlines()[0]
                    produced = json.loads(line)
                    self.assertEqual(checker._event_schema_errors([produced]), [])
                    self.assertEqual(checker._cost_summary_errors(produced), [])

    def test_both_emitters_reject_cost_status_inconsistent_bucket_usd(self):
        self.require_emitters()
        for emitter in ("powershell", "bash"):
            for unmetered in (False, True):
                with self.subTest(emitter=emitter, unmetered=unmetered), tempfile.TemporaryDirectory() as temp:
                    summary = measured_cost(unmetered=unmetered)
                    bucket = summary["usage"]["by_phase"]["coding"]
                    bucket["usd"] = 0.0 if unmetered else None
                    payload = {
                        "cost_summary": {
                            "status": "unmetered" if unmetered else "measured",
                            "source": "collect-usage.py",
                            "usage": summary["usage"],
                        },
                    }
                    result = self.emit(
                        emitter, "run_complete", "wrap-up", Path(temp),
                        "success", payload,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((Path(temp) / RUN_ID / "events.jsonl").exists())

    def test_both_emitters_reject_case_variant_allowlist_keys(self):
        self.require_emitters()
        payloads = [
            ("run_start", None, {
                "Requirement_summary": "Synthetic case test",
                "profile_loaded": True,
            }),
            ("run_complete", "success", {
                "cost_summary": {
                    "STATUS": "disabled",
                    "reason": "synthetic case test",
                },
            }),
            ("run_complete", "success", {
                "cost_summary": {
                    "status": "measured",
                    "source": "collect-usage.py",
                    "usage": {
                        **measured_cost()["usage"],
                        "warnings": [{
                            "SCOPE": "per_run",
                            "metric": "tokens",
                            "actual": 1,
                            "limit": 2,
                        }],
                    },
                },
            }),
        ]
        with tempfile.TemporaryDirectory() as temp:
            for emitter in ("powershell", "bash"):
                for index, (kind, outcome, payload) in enumerate(payloads):
                    with self.subTest(emitter=emitter, case=index):
                        base = Path(temp) / emitter / str(index)
                        result = self.emit(
                            emitter, kind, "wrap-up", base, outcome, payload,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse((base / RUN_ID / "events.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
