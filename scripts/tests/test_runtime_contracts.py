"""Offline regressions for runtime gates and their instruction contracts."""

import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "plugins" / "agile-agents-core"
COLLECTOR = CORE / "skills" / "cost-budget" / "scripts" / "collect-usage.py"
REQUIRE_RUNNERS = os.environ.get("RUNTIME_GATE_REQUIRE_RUNNERS") == "1"

spec = importlib.util.spec_from_file_location("collect_usage", COLLECTOR)
usage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(usage)


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.store = self.directory / "usage.db"
        self.log = self.directory / "events.jsonl"
        with closing(sqlite3.connect(self.store)) as conn, conn:
            conn.execute(
                "CREATE TABLE assistant_usage_events (session_id TEXT, agent_id TEXT, "
                "model TEXT, initiator TEXT, input_tokens INTEGER, output_tokens INTEGER, "
                "reasoning_tokens INTEGER, cache_read_tokens INTEGER, total_nano_aiu INTEGER, "
                "duration_ms INTEGER, created_at TEXT)"
            )
        self.windows([("coding", "10:00:00", "10:10:00"),
                      ("review-lead", "10:10:00", "10:20:00")])

    def windows(self, windows):
        events = []
        for phase, start, end in windows:
            events.append({"event_type": "phase_start", "phase": phase,
                           "timestamp": "2026-10-05T%sZ" % start})
            if end is not None:
                events.append({"event_type": "phase_complete", "phase": phase,
                               "timestamp": "2026-10-05T%sZ" % end})
        self.log.write_text("\n".join(json.dumps(event) for event in events),
                            encoding="utf-8")

    def row(self, aiu, when="10:05:00", tokens=0, session="test"):
        timestamp = "2026-10-05T%sZ" % when if ":" in when else when
        nano_aiu = int(usage.Decimal(str(aiu)) * 10**9)
        with closing(sqlite3.connect(self.store)) as conn, conn:
            conn.execute("INSERT INTO assistant_usage_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                         (session, "worker", "test-model", None, tokens, 0, 0, 0,
                          nano_aiu, 100, timestamp))

    def collect(self, *flags, event_log=True):
        command = [sys.executable, str(COLLECTOR), "--session-id", "test",
                   "--store", str(self.store), "--since", "2026-10-05T10:00:00Z"]
        if event_log:
            command += ["--event-log", str(self.log)]
        result = subprocess.run(command + list(flags), capture_output=True, text=True,
                                timeout=20)
        return result.returncode, json.loads(result.stdout)

    def test_phase_cap_is_not_run_cap(self):
        self.row(5000)
        self.row(5000, "10:15:00")
        code, result = self.collect("--phase", "coding", "--max-phase-aiu", "8000",
                                    "--max-aiu", "20000")
        self.assertEqual(code, 0)
        self.assertEqual(result["totals"]["aiu"], 10000)
        self.assertEqual(result["by_phase"]["coding"]["aiu"], 5000)

    def test_prior_usage_excluded_at_checkpoint_and_completion(self):
        self.row(6000, "09:00:00")
        self.row(5000)
        self.row(9000, session="other-session")
        for flags in [("--phase", "coding", "--max-phase-aiu", "8000"), ()]:
            with self.subTest(flags=flags):
                code, result = self.collect("--max-aiu", "8000", *flags)
                self.assertEqual(code, 0)
                self.assertEqual(result["totals"]["aiu"], 5000)
                self.assertEqual(result["by_phase"]["coding"]["aiu"], 5000)

    def test_run_and_phase_breaches_independent(self):
        self.row(5000)
        self.row(5000, "10:15:00")
        code, result = self.collect("--max-aiu", "8000", "--phase", "coding",
                                    "--max-phase-aiu", "8000")
        self.assertEqual(code, 2)
        self.assertEqual([b["scope"] for b in result["breaches"]], ["per_run"])
        code, result = self.collect("--max-aiu", "20000", "--phase", "coding",
                                    "--max-phase-aiu", "4000")
        self.assertEqual(code, 2)
        self.assertEqual([b["scope"] for b in result["breaches"]], ["per_phase"])

    def test_exact_thresholds_without_display_rounding(self):
        for metric in ("aiu", "tokens", "usd", "phase"):
            for actual, expected in ((109, 0), (110, 2), (111, 2)):
                with self.subTest(metric=metric, actual=actual):
                    with closing(sqlite3.connect(self.store)) as conn, conn:
                        conn.execute("DELETE FROM assistant_usage_events")
                    self.row(actual, tokens=actual)
                    flags = {"aiu": ["--max-aiu", "100"],
                             "tokens": ["--max-tokens", "100"],
                             "usd": ["--usd-per-aiu", "0.5", "--max-usd", "50"],
                             "phase": ["--phase", "coding", "--max-phase-aiu", "100"]}
                    code, result = self.collect(*flags[metric])
                    self.assertEqual(code, expected)
                    self.assertEqual(bool(result["breaches"]), expected == 2)
        with closing(sqlite3.connect(self.store)) as conn, conn:
            conn.execute("DELETE FROM assistant_usage_events")
        self.row("109.999999999")
        code, result = self.collect("--max-aiu", "100")
        self.assertEqual(result["totals"]["aiu"], 110)  # display rounds, decision does not
        self.assertEqual(code, 0)

    def test_warning_boundary_and_unrated_usd(self):
        for actual, warned in ((79, False), (80, True)):
            with self.subTest(actual=actual):
                with closing(sqlite3.connect(self.store)) as conn, conn:
                    conn.execute("DELETE FROM assistant_usage_events")
                self.row(actual)
                code, result = self.collect("--max-aiu", "100")
                self.assertEqual(code, 0)
                self.assertEqual(bool(result["warnings"]), warned)
                self.assertIsNone(result["usd"])

    def test_zero_and_unset_caps(self):
        code, result = self.collect("--max-aiu", "0", "--max-tokens", "0")
        self.assertEqual(code, 0)
        self.row(1, tokens=1)
        code, result = self.collect("--max-aiu", "0", "--max-tokens", "0")
        self.assertEqual(code, 2)
        self.assertEqual(len(result["breaches"]), 2)
        code, result = self.collect()
        self.assertEqual(code, 0)
        self.assertEqual(result["breaches"], [])

    def test_repeated_windows_aggregate_and_boundary_is_not_double_counted(self):
        self.windows([("coding", "10:00:00", "10:10:00"),
                      ("review-lead", "10:10:00", "10:20:00"),
                      ("coding", "10:20:00", None)])
        self.row(5000)
        self.row(1000, "10:10:00")
        self.row(5000, "10:25:00")
        code, result = self.collect("--phase", "coding", "--max-phase-aiu", "8000")
        self.assertEqual(code, 2)
        self.assertEqual(result["by_phase"]["coding"]["aiu"], 10000)
        self.assertEqual(result["by_phase"]["review-lead"]["aiu"], 1000)

    def test_missing_phase_is_not_zero_but_empty_window_is(self):
        code, result = self.collect("--phase", "absent", "--max-phase-aiu", "1")
        self.assertEqual(code, 3)
        self.assertIn("no attribution window", result["reason"])
        code, result = self.collect("--phase", "coding", "--max-phase-aiu", "1")
        self.assertEqual(code, 0)
        self.assertEqual(result["by_phase"]["coding"]["aiu"], 0)

    def test_invalid_metering_inputs(self):
        cases = [("--since", "not-a-date"), ("--max-aiu", "-1"),
                 ("--max-aiu", "NaN"), ("--max-aiu", "Infinity"),
                 ("--max-aiu", "1e10000"),
                 ("--max-tokens", "1.5"), ("--phase", "coding"),
                 ("--max-phase-aiu", "100"), ("--max-usd", "10")]
        for flags in cases:
            with self.subTest(flags=flags):
                code, result = self.collect(*flags)
                self.assertEqual(code, 3)
                self.assertEqual(result["error"], "usage-unavailable")
        self.row(1, "invalid")
        code, result = self.collect()
        self.assertEqual(code, 3)
        self.assertIn("invalid timestamp", result["reason"])

    def test_gating_requires_run_boundary(self):
        result = subprocess.run(
            [sys.executable, str(COLLECTOR), "--session-id", "test",
             "--store", str(self.store), "--max-aiu", "100"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 3)
        self.assertIn("gating requires --since", json.loads(result.stdout)["reason"])

    def test_unusable_store_and_event_log(self):
        code, result = self.collect("--store", str(self.directory / "missing.db"))
        self.assertEqual(code, 3)
        self.assertIn("store not found", result["reason"])
        self.log.write_text("not-json", encoding="utf-8")
        code, result = self.collect()
        self.assertEqual(code, 3)
        self.assertIn("invalid event JSON", result["reason"])
        self.windows([("coding", "10:10:00", "10:00:00")])
        code, result = self.collect()
        self.assertEqual(code, 3)
        self.windows([("coding", "10:00:00", "10:20:00"),
                      ("review-lead", "10:10:00", "10:30:00")])
        code, result = self.collect()
        self.assertEqual(code, 3)


class ProfileRunnerTests(unittest.TestCase):
    def runners(self):
        runners = []
        if shutil.which("pwsh"):
            runners.append(["pwsh", "-NoProfile", "-File",
                            str(CORE / "skills/test-bar-gate/scripts/run-gate.ps1")])
        elif REQUIRE_RUNNERS:
            self.fail("pwsh is required for runtime gate regression checks")
        bash = os.environ.get("RUNTIME_GATE_BASH") or shutil.which("bash")
        if os.name != "nt" or os.environ.get("RUNTIME_GATE_BASH"):
            if bash and shutil.which("yq"):
                runners.append([bash, str(CORE / "skills/test-bar-gate/scripts/run-gate.sh")])
            elif REQUIRE_RUNNERS:
                self.fail("bash and mikefarah yq are required on Unix")
        if not runners:
            self.skipTest("No gate runner available")
        return runners

    def run_gate(self, runner, cwd, path=None):
        flag = "-ProfilePath" if runner[0] == "pwsh" else "--profile"
        command = runner + ([flag, path] if path else [])
        env = os.environ.copy()
        env.pop("COPILOT_EVENT_LOG", None)
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=30)
        return result.returncode, result.stdout + result.stderr

    def test_profile_resolution_and_configuration_failures(self):
        runnable = {"quality_gates": {"test_bar": {
            "lint": {"command": [sys.executable, "-c", "exit(0)"]},
            "typecheck": {"enabled": False}, "unit_test": {"enabled": False}}}}
        disabled = {"quality_gates": {"test_bar": {"enabled": False}}}
        for runner in self.runners():
            with self.subTest(runner=runner[0]), tempfile.TemporaryDirectory() as temp:
                cwd = Path(temp)
                canonical = cwd / ".github" / "solution-profile.yaml"
                canonical.parent.mkdir()
                root_profile = cwd / "solution-profile.yaml"

                code, output = self.run_gate(runner, cwd)
                self.assertEqual(code, 2, output)
                root_profile.write_text(json.dumps(runnable), encoding="utf-8")
                code, output = self.run_gate(runner, cwd)
                self.assertEqual(code, 0, output)
                self.assertIn('"check":"lint"', output.replace(" ", ""))
                self.assertNotIn("no_stack_match", output)

                canonical.write_text(json.dumps(disabled), encoding="utf-8")
                code, output = self.run_gate(runner, cwd)
                self.assertEqual(code, 0, output)
                self.assertIn("disabled_by_profile", output)
                code, output = self.run_gate(runner, cwd, "solution-profile.yaml")
                self.assertEqual(code, 0, output)
                self.assertNotIn("disabled_by_profile", output)
                code, output = self.run_gate(runner, cwd, "missing.yaml")
                self.assertEqual(code, 2, output)

                for invalid in ("", "{}", "[]", "scalar", "key: [unfinished"):
                    canonical.write_text(invalid, encoding="utf-8")
                    code, output = self.run_gate(runner, cwd)
                    self.assertEqual(code, 2, (invalid, output))
                    self.assertNotIn("no_stack_match", output)
                canonical.write_text("tech_stack: {primary_languages: [unsupported]}",
                                     encoding="utf-8")
                code, output = self.run_gate(runner, cwd)
                self.assertEqual(code, 0, output)
                self.assertIn("no_stack_match", output)


def contract_errors(files):
    """Bounded textual invariants, not a general Markdown or agent parser."""
    errors = []
    lead = files["dev-lead"]
    for field in ("Behavior added/modified", "Existing tests modified"):
        if "- %s:" % field not in files["infrastructure"]:
            errors.append("infrastructure missing " + field)
    if "Unreviewed dimensions" in lead or "Not verifiable from this diff" not in lead:
        errors.append("analysis consumer field drift")
    if "- Not verifiable from this diff:" not in files["data-scientist"]:
        errors.append("analysis producer field drift")
    if "- Code verification:" not in files["data-scientist"] or "`Code verification`" not in lead:
        errors.append("analysis code evidence drift")
    for author in ("coding", "infrastructure", "architect", "data-scientist"):
        if "- Findings addressed:" not in files[author]:
            errors.append(author + " missing corrective accounting")
        if "exactly once" in files[author] or "one round —" in files[author]:
            errors.append(author + " stale retry count")
    approve = files["plan-approval"].split("## Handling the answer")[1].split("- **Adjust**")[0]
    if "Stage 5 conditional design approval" not in approve:
        errors.append("approval bypasses design gate")
    for required in ("Re-verify before re-review", "failed\n  rerun prevents reviewer dispatch",
                     "does **not reset**", "staged and unstaged diffs",
                     "run_started_at", "Not verifiable from this diff"):
        if required not in lead:
            errors.append("supervisor missing " + required)
    for required in ("--since", "--max-phase-aiu", "max_aiu_per_phase_overrides",
                     "stop_on_breach", "enabled", "≥110%"):
        if required not in files["cost-budget"]:
            errors.append("cost instructions missing " + required)
    return errors


class InstructionTests(unittest.TestCase):
    def setUp(self):
        self.files = {name: (CORE / "agents" / (name + ".agent.md")).read_text(encoding="utf-8")
                      for name in ("dev-lead", "coding", "infrastructure",
                                   "architect", "data-scientist")}
        self.files["plan-approval"] = (
            CORE / "skills/dev-lead-templates/references/plan-approval.md"
        ).read_text(encoding="utf-8")
        self.files["cost-budget"] = (CORE / "skills/cost-budget/SKILL.md").read_text(encoding="utf-8")

    def test_contracts_match(self):
        self.assertEqual(contract_errors(self.files), [])

    def test_known_contradictions_are_detected(self):
        mutations = [
            ("infrastructure", "- Existing tests modified:", "- Removed test field:"),
            ("infrastructure", "- Behavior added/modified:", "- Removed behavior field:"),
            ("dev-lead", "Not verifiable from this diff", "Unreviewed dimensions"),
            ("data-scientist", "- Code verification:", "- Removed code field:"),
            ("architect", "- Findings addressed:", "- Removed corrective field:"),
            ("coding", "`dev-lead` owns the", "one round — `dev-lead` owns the"),
            ("plan-approval", "Stage 5 conditional design approval", "Stage 6"),
            ("dev-lead", "Re-verify before re-review", "Then re-run review"),
            ("dev-lead", "does **not reset**", "resets"),
            ("cost-budget", "--since", "--no-run-bound"),
        ]
        for name, old, new in mutations:
            with self.subTest(name=name, old=old):
                changed = dict(self.files)
                self.assertIn(old, changed[name])
                changed[name] = changed[name].replace(old, new)
                self.assertTrue(contract_errors(changed))


if __name__ == "__main__":
    unittest.main()
