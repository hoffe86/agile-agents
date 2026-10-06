"""Offline regressions for runtime gates and their instruction contracts."""

import importlib.util
from contextlib import closing
import json
import os
from pathlib import Path
import re
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


def boundary_contract_errors(files):
    """Scoped instruction regressions, not a simulation of model obedience."""
    errors = []
    prose = {name: " ".join(text.split()) for name, text in files.items()}
    trade = prose["trade-off-reporting"]
    for recipe in ("promote to an ADR", "→ write an ADR", "Recommend creating ADR-0001",
                   "Long reasoning belongs in an ADR"):
        if recipe in trade:
            errors.append("unsolicited ADR recipe")
    for required in ("existing decision capture", "decision gap",
                     "explicit human request", "write-capable authoring context",
                     "Reviewers remain read-only"):
        if required not in trade:
            errors.append("ADR boundary missing " + required)
    if "only when the user explicitly asks" not in prose["architecture-decision-records"]:
        errors.append("explicit ADR request guard missing")

    blocked_routes = {
        "architecture-reviewer": ("architecture-design", "architecture-decision-records",
                                  "acquire-codebase-knowledge", "threat-model-analyst"),
        "security-reviewer": ("security-review", "threat-model-analyst"),
    }
    for reviewer, routes in blocked_routes.items():
        text = files[reviewer]
        # These were automatic entries in "Skills you compose with". A warning
        # elsewhere cannot neutralize reintroducing any of those route entries.
        for route in routes:
            if re.search(r"(?m)^- \*\*`" + re.escape(route) + r"`\*\*", text):
                errors.append(reviewer + " automatic route " + route)
        for required in ("Do not invoke", "read-only", "reviewer-read-only-rules",
                         "STRIDE", "spoofing", "tampering", "repudiation",
                         "information disclosure", "denial of service",
                         "elevation of", "abuse", "existing threat",
                         "https://learn.microsoft.com/en-us/azure/security/develop/"
                         "threat-modeling-tool-threats"):
            if required not in prose[reviewer]:
                errors.append(reviewer + " analysis missing " + required)
    for required in ("Source context", "manifests", "entry points", "imports",
                     "persistence owners", "data flows", "accepted ADRs",
                     "alternatives", "consequences", "migration", "decision gap",
                     "Decision gaps for human resolution:",
                     "https://arc42.org/overview", "https://c4model.com/",
                     "https://adr.github.io/madr/", "independent `security-reviewer`"):
        if required not in prose["architecture-reviewer"]:
            errors.append("architecture analysis missing " + required)
    for recipe in ("ADRs that should exist:", "plus an ADR if irreversible"):
        if recipe in prose["architecture-reviewer"]:
            errors.append("architecture report requests ADR authoring")
    for required in ("lockfiles", "CVEs", "provenance", "integrity", "across files",
                     "entry points to sinks", "framework controls", "reachability",
                     "business-logic abuse", "race conditions", "rate limits",
                     "independent `architecture-reviewer`"):
        if required not in prose["security-reviewer"]:
            errors.append("security analysis missing " + required)
    for reference in ("language-patterns", "vuln-categories", "secret-patterns",
                      "vulnerable-packages"):
        if "../skills/security-review/references/" + reference + ".md" not in files["security-reviewer"]:
            errors.append("security reference missing " + reference)

    lead = files["review-lead"]
    for lens in ("code-reviewer", "security-reviewer"):
        if "| **Always** | `" + lens + "`" not in lead:
            errors.append("unconditional dispatch missing " + lens)
    for owner in ("review-lead", "dev-lead"):
        text = prose[owner]
        for exemption in ("carve-out", "docs-only allow-list"):
            if exemption in text.lower():
                errors.append(owner + " security exemption")
        if re.search(r"(?:security-reviewer.{0,100}may be skipped"
                     r"|may skip.{0,100}security-reviewer)", text):
            errors.append(owner + " security exemption")
        if "owns mandatory secret scanning" not in text:
            errors.append(owner + " orphan secret scan")
    if "`review-lead` always invokes `security-reviewer`" not in prose["dev-lead"]:
        errors.append("supervisor security dispatch missing")

    security = files["security-reviewer"]
    for mechanism in ("`secret-scanning`", "`github/run_secret_scanning`",
                      "otherwise sweep the diff yourself with `search`",
                      "The check itself is never skipped"):
        if mechanism not in prose["security-reviewer"]:
            errors.append("secret scan fallback missing " + mechanism)
    for pattern in ("AKIA[0-9A-Z]{16}", "ghp_", "github_pat_", "sk-[A-Za-z0-9]{20,}",
                    "-----BEGIN .*PRIVATE KEY-----", "xox[baprs]-", "AccountKey=",
                    "SharedAccessSignature", r"password\s*=", "client_secret",
                    ".pem", ".pfx", ".p12"):
        if pattern not in security:
            errors.append("secret pattern missing " + pattern)
    return errors


class InstructionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            name: (CORE / "agents" / (name + ".agent.md")).read_text(encoding="utf-8")
            for name in ("dev-lead", "review-lead", "architecture-reviewer", "security-reviewer")
        }
        for name in ("trade-off-reporting", "architecture-decision-records"):
            self.files[name] = (CORE / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def assert_mutation_detected(self, name, old, new, expected):
        changed = dict(self.files)
        pattern = re.escape(old).replace(r"\ ", r"\s+")
        self.assertRegex(changed[name], pattern)
        changed[name] = re.sub(pattern, lambda _: new, changed[name])
        self.assertIn(expected, boundary_contract_errors(changed))

    def test_instruction_boundaries_match(self):
        self.assertEqual(boundary_contract_errors(self.files), [])

    def test_prose_obligations_allow_whitespace_reflow(self):
        for name, phrase in (
            ("security-reviewer", "across files"),
            ("security-reviewer", "entry points to sinks"),
            ("architecture-reviewer", "Source context"),
            ("trade-off-reporting", "explicit human request"),
            ("dev-lead", "owns mandatory secret scanning"),
            ("security-reviewer", "otherwise sweep the diff yourself with `search`"),
        ):
            with self.subTest(name=name, phrase=phrase):
                changed = dict(self.files)
                pattern = re.escape(phrase).replace(r"\ ", r"\s+")
                self.assertRegex(changed[name], pattern)
                changed[name] = re.sub(
                    pattern, lambda _: phrase.replace(" ", " \n\t "), changed[name])
                self.assertEqual(boundary_contract_errors(changed), [])

    def test_both_unsolicited_adr_recipes_are_rejected(self):
        for recipe in (
            "For longer reasoning → **promote to an ADR** via `architecture-decision-records`.",
            "If a trade-off is architectural → write an ADR via `architecture-decision-records`.",
        ):
            with self.subTest(recipe=recipe):
                changed = dict(self.files)
                changed["trade-off-reporting"] += "\n" + recipe
                self.assertIn("unsolicited ADR recipe", boundary_contract_errors(changed))

    def test_explicit_human_adr_request_remains_supported(self):
        self.assert_mutation_detected(
            "trade-off-reporting", "explicit human request", "autonomous decision",
            "ADR boundary missing explicit human request")
        self.assert_mutation_detected(
            "architecture-decision-records", "only when the user explicitly asks", "automatically",
            "explicit ADR request guard missing")

    def test_architecture_report_requests_decisions_not_new_adrs(self):
        self.assert_mutation_detected(
            "architecture-reviewer", "Decision gaps for human resolution:",
            "ADRs that should exist:", "architecture report requests ADR authoring")
        self.assert_mutation_detected(
            "architecture-reviewer",
            "cite existing rationale or report a decision gap if irreversible",
            "plus an ADR if irreversible", "architecture report requests ADR authoring")

    def test_automatic_authoring_routes_fail_even_with_read_only_warning(self):
        routes = {
            "architecture-reviewer": ("architecture-design", "architecture-decision-records",
                                      "acquire-codebase-knowledge", "threat-model-analyst"),
            "security-reviewer": ("security-review", "threat-model-analyst"),
        }
        for reviewer, skills in routes.items():
            for skill in skills:
                with self.subTest(reviewer=reviewer, skill=skill):
                    self.assert_mutation_detected(
                        reviewer, "## Skills you compose with",
                        "## Skills you compose with\n\n- **`%s`** — invoke for context." % skill,
                        reviewer + " automatic route " + skill)

    def test_substantive_read_only_analysis_cannot_be_removed(self):
        for reviewer, marker, expected in (
            ("architecture-reviewer", "Source context", "architecture analysis missing Source context"),
            ("architecture-reviewer", "decision gap", "architecture analysis missing decision gap"),
            ("security-reviewer", "entry points to sinks",
             "security analysis missing entry points to sinks"),
            ("security-reviewer", "STRIDE", "security-reviewer analysis missing STRIDE"),
            ("architecture-reviewer", "independent `security-reviewer`",
             "architecture analysis missing independent `security-reviewer`"),
            ("security-reviewer", "independent `architecture-reviewer`",
             "security analysis missing independent `architecture-reviewer`"),
        ):
            with self.subTest(reviewer=reviewer, marker=marker):
                self.assert_mutation_detected(reviewer, marker, "removed", expected)

    def test_docs_and_manifest_exemptions_are_rejected_at_both_dispatchers(self):
        # Textual counterexamples only: no filename classifier or fake dispatch
        # implementation, and no claim that a model would detect a README secret.
        for owner in ("review-lead", "dev-lead"):
            for path in ("README.md", "requirements.txt", "CMakeLists.txt",
                         "docs/workflow.yaml", "package-lock.json", "docs/guide.md"):
                with self.subTest(owner=owner, path=path):
                    changed = dict(self.files)
                    changed[owner] += (
                        "\nFor a %s-only diff, `security-reviewer` may be skipped; "
                        "secret scanning still runs unconditionally.\n" % path)
                    self.assertIn(owner + " security exemption", boundary_contract_errors(changed))

    def test_original_allow_list_and_orphan_scan_promise_are_rejected(self):
        for owner in ("review-lead", "dev-lead"):
            with self.subTest(owner=owner):
                changed = dict(self.files)
                changed[owner] += (
                    "\nDocs-only carve-out: `*.md`, `docs/**`, `*.txt`, `LICENSE` — "
                    "may skip the full `security-reviewer` fan-out; secret scanning still runs.\n")
                self.assertIn(owner + " security exemption", boundary_contract_errors(changed))
                self.assert_mutation_detected(
                    owner, "owns mandatory secret scanning", "may perform security checks",
                    owner + " orphan secret scan")

    def test_secret_scan_mechanisms_and_manual_patterns_are_preserved(self):
        for marker in ("`secret-scanning`", "`github/run_secret_scanning`",
                       "otherwise sweep the diff yourself with `search`"):
            with self.subTest(marker=marker):
                self.assert_mutation_detected(
                    "security-reviewer", marker, "removed",
                    "secret scan fallback missing " + marker)
        self.assert_mutation_detected(
            "security-reviewer", "AKIA[0-9A-Z]{16}", "removed",
            "secret pattern missing AKIA[0-9A-Z]{16}")

    def test_unconditional_lenses_cannot_be_downgraded(self):
        for lens in ("code-reviewer", "security-reviewer"):
            with self.subTest(lens=lens):
                self.assert_mutation_detected(
                    "review-lead", "| **Always** | `" + lens + "`",
                    "| **Almost always** | `" + lens + "`",
                    "unconditional dispatch missing " + lens)

    def test_security_reference_data_paths_resolve(self):
        links = re.findall(r"\]\((\.\./skills/security-review/references/[^)]+)\)",
                           self.files["security-reviewer"])
        self.assertEqual(len(links), 4)
        for link in links:
            with self.subTest(link=link):
                self.assertTrue((CORE / "agents" / link).is_file(), link)


def cloud_contract_errors(files):
    """Bounded cloud-routing text contracts; these do not execute an agent."""
    errors = []
    sections = {
        "infrastructure": ("## Routing", "## Skills you compose with"),
        "bootstrapper": ("## Deriving the plugin set", "## Approval gate"),
        "terraform": ("## Applicability", "## 1."),
        "iac": ("## 1. Naming", "## 2."),
        "coverage": ("## 2. Establish the supply", "## 3."),
        "matrix": ("**Azure applicability gate:", "### The IaC-test gap"),
        "helm": ("## 8. What you do NOT do", ""),
    }
    # Complete clauses, not keyword bags: AND must not become OR and an Azure
    # subset must not turn into permission for every provider. These are written
    # contracts; no cloud/availability input is evaluated as a routing model.
    guards = {
        "infrastructure": "Azure-only skills require both an **installed** capability and "
                          "`infrastructure.cloud: azure`.",
        "bootstrapper": "An Azure-only route requires an **installed** capability as well as "
                        "this applicability — a recommendation is not availability.",
        "terraform": "This Azure-only skill requires an **installed** capability and "
                     "`infrastructure.cloud: azure`.",
        "iac": "load **`azure-platform-grounding`** only when **installed** and "
               "`infrastructure.cloud: azure`.",
        "coverage": "Azure-only depth requires an **installed** capability and "
                    "`infrastructure.cloud: azure`.",
        "matrix": "Azure-only cells require an **installed** capability and "
                  "`infrastructure.cloud: azure`.",
        "helm": "Azure-only depth requires both an installed capability and "
                "`infrastructure.cloud: azure` (or an explicitly evidenced, documented "
                "Azure resource subset of a multi-cloud/hybrid target)",
    }
    scopes = {
        "infrastructure": "apply Azure guidance only to that subset.",
        "bootstrapper": "Recommend Azure-only depth only for that subset.",
        "terraform": "Apply this skill only to that subset, never the other providers in the repo.",
        "iac": "Apply Azure guidance only to that subset.",
        "coverage": "Count coverage only for that subset.",
        "matrix": "Count Azure-only coverage only for that subset.",
        "helm": "Apply Azure guidance only to that subset and document that scope in the hand-off.",
    }
    for name, (start, end) in sections.items():
        section = " ".join(files[name].split()).partition(start)[2]
        text = section.partition(end)[0] if end else section
        for marker in ("installed", "infrastructure.cloud: azure", "hybrid alone",
                       "Azure resource subset", "document that scope",
                       "repo/provider conventions", "hand-off"):
            if marker.casefold() not in text.casefold():
                errors.append(name + " missing " + marker)
        if guards[name] not in text:
            errors.append(name + " weakened Azure guard")
        if scopes[name] not in text:
            errors.append(name + " widened Azure scope")
        if (name == "bootstrapper"
                and "recommend Azure-only depth for `infrastructure.cloud: azure`." not in text):
            errors.append(name + " weakened Azure guard")

    routing = files["infrastructure"].partition("## Routing")[2].partition(
        "## Skills you compose with")[0]
    for skill in ("bicep-implementation", "terraform-azure-implementation",
                  "import-infrastructure-as-code", "azure-deployment-preflight"):
        rows = [line for line in routing.splitlines()
                if line.startswith("|") and "`" + skill + "`" in line]
        if (len(rows) != 1 or "only when installed and the Azure applicability gate above "
                "is satisfied" not in " ".join(rows[0].split())):
            errors.append("ungated route " + skill)

    for skill in ("terraform-azure-implementation", "import-infrastructure-as-code"):
        cell = ("`" + skill + "` — Azure-only, subject to the applicability gate below")
        if cell not in " ".join(files["matrix"].split()):
            errors.append("ungated coverage " + skill)

    bootstrap = files["bootstrapper"]
    if "| `infrastructure.iac_tool` | `terraform` |" in bootstrap:
        errors.append("provider-blind Terraform recommendation")
    for marker in ("specific provider-relevant capability", "not availability",
                   "Do not count generic import support as non-Azure implementation coverage"):
        if marker not in " ".join(bootstrap.split()):
            errors.append("bootstrap missing " + marker)

    description = files["terraform"].split("---", 2)[1]
    if ("Azure-targeted Terraform" not in description
            or "DO NOT USE for generic `.tf` files or non-Azure Terraform" not in description
            or "USE FOR any request" in description
            or 'Triggered by "Terraform"' in description):
        errors.append("overbroad Terraform description")
    if "Azure state backend alone does not establish" not in " ".join(files["terraform"].split()):
        errors.append("backend mistaken for resource provider")

    iac = " ".join(files["iac"].split())
    naming = iac.partition("## 1. Naming")[2].partition("## 2.")[0].strip()
    if "`azure-platform-grounding`" not in naming or "azure-platform-conventions" in iac:
        errors.append("missing correct platform reference")
    if (not naming.startswith("`infrastructure.naming_convention` takes precedence")
            or "**Azure-only default:**" not in naming
            or "Non-Azure targets use repo/provider conventions, not CAF." not in naming
            or "Use the **Microsoft Cloud Adoption Framework abbreviations**" in naming):
        errors.append("generic CAF naming")
    for marker in ("declared platform's secrets store", "Preserve the repo's selected backend",
                   "tool/provider's preview"):
        if marker not in iac:
            errors.append("platform assumption missing guard " + marker)
    helm = " ".join(files["helm"].partition("## 1.")[2].partition("## 2.")[0].split())
    if ("route to `infrastructure` through the guarded route in §8" not in helm
            or "`azure-kubernetes`" in helm or "`azure-aks`" in helm):
        errors.append("unguarded early cluster route")
    cluster_route = " ".join(files["helm"].partition("## 8.")[2].split())
    if "route to `infrastructure` using the declared cloud and installed capabilities." not in cluster_route:
        errors.append("cluster route missing installed")
    return errors


class CloudInstructionTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            name: (CORE / "agents" / (name + ".agent.md")).read_text(encoding="utf-8")
            for name in ("infrastructure", "bootstrapper")
        }
        for key, name in (("iac", "iac-best-practices"), ("coverage", "artifact-coverage"),
                          ("helm", "helm-kustomize-implementation")):
            self.files[key] = (CORE / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        self.files["matrix"] = (
            CORE / "skills/artifact-coverage/references/coverage-matrix.md"
        ).read_text(encoding="utf-8")
        self.files["terraform"] = (
            ROOT / "plugins/agile-agents-terraform/skills/terraform-azure-implementation/SKILL.md"
        ).read_text(encoding="utf-8")

    def assert_mutation_detected(self, name, old, new, expected):
        changed = dict(self.files)
        pattern = re.escape(old).replace(r"\ ", r"\s+")
        self.assertRegex(changed[name], pattern)
        changed[name] = re.sub(pattern, lambda _: new, changed[name])
        self.assertIn(expected, cloud_contract_errors(changed))

    def test_cloud_contracts_match(self):
        self.assertEqual(cloud_contract_errors(self.files), [])

    def test_installed_and_cloud_conjunction_cannot_become_disjunction(self):
        for name, old, new in (
            ("infrastructure",
             "both an **installed** capability and `infrastructure.cloud: azure`",
             "either an **installed** capability or `infrastructure.cloud: azure`"),
            ("bootstrapper",
             "an **installed** capability as well as this applicability",
             "an **installed** capability or this applicability"),
            ("terraform",
             "an **installed** capability and `infrastructure.cloud: azure`",
             "an **installed** capability or `infrastructure.cloud: azure`"),
            ("iac",
             "only when **installed** and `infrastructure.cloud: azure`",
             "when **installed** or `infrastructure.cloud: azure`"),
            ("coverage",
             "an **installed** capability and `infrastructure.cloud: azure`",
             "an **installed** capability or `infrastructure.cloud: azure`"),
            ("matrix",
             "an **installed** capability and `infrastructure.cloud: azure`",
             "an **installed** capability or `infrastructure.cloud: azure`"),
            ("helm",
             "both an installed capability and `infrastructure.cloud: azure`",
             "either an installed capability or `infrastructure.cloud: azure`"),
        ):
            with self.subTest(name=name):
                self.assert_mutation_detected(name, old, new, name + " weakened Azure guard")

    def test_azure_subset_scope_cannot_expand_to_other_providers(self):
        for name, old, new in (
            ("infrastructure", "apply Azure guidance only to that subset",
             "apply Azure guidance to all providers in repository"),
            ("bootstrapper", "Recommend Azure-only depth only for that subset",
             "Recommend Azure-only depth for all providers in repository"),
            ("terraform", "Apply this skill only to that subset, never the other providers in the repo",
             "Apply this skill to all providers in repository"),
            ("iac", "Apply Azure guidance only to that subset",
             "Apply Azure guidance to all providers in repository"),
            ("coverage", "Count coverage only for that subset",
             "Count coverage for all providers in repository"),
            ("matrix", "Count Azure-only coverage only for that subset",
             "Count Azure-only coverage for all providers in repository"),
            ("helm", "Apply Azure guidance only to that subset",
             "Apply Azure guidance to all providers in repository"),
        ):
            with self.subTest(name=name):
                self.assert_mutation_detected(name, old, new, name + " widened Azure scope")

    def test_helm_early_entrypoint_defers_to_guarded_route(self):
        self.assert_mutation_detected(
            "helm", "route to `infrastructure` through the guarded route in §8",
            "use the **`azure-kubernetes`** plugin skill or **`azure-aks`** MCP tool",
            "unguarded early cluster route")

    def test_written_fallback_obligations_on_each_cloud_surface(self):
        # Prose assertions only, not a matrix of executed cloud/availability inputs.
        obligations = {
            "infrastructure": (
                "**If no installed skill matches the declared cloud and tool**",
                "Non-Azure Terraform uses this fallback, not the Azure implementation skill.",
                "Missing or conflicting cloud declarations need clarification",
            ),
            "bootstrapper": (
                "If no installed skill matches, agents use repo/provider conventions",
                "Missing or conflicting cloud declarations need clarification",
            ),
            "terraform": (
                "An unavailable skill also takes that fallback",
                "If this gate is not met, do not apply AVM/CAF/Azure tooling",
                "use repo/provider conventions", "provider's own documentation",
                "Missing or conflicting cloud declarations need clarification",
                "hybrid alone is not Azure evidence", "Apply this skill only to that subset",
            ),
            "iac": (
                "If the skill is unavailable, use the declared provider's documentation",
                "Non-Azure targets use repo/provider conventions, not CAF.",
                "Missing or conflicting cloud declarations need clarification",
            ),
            "coverage": (
                "otherwise report a gap and repo/provider conventions",
                "Missing cloud declarations need clarification, not an Azure assumption.",
            ),
            "matrix": (
                "Non-Azure Terraform implementation is a **gap**, not covered by the Azure skill",
                "use repo/provider conventions and provider documentation",
            ),
            "helm": ("Without a matching skill, use repo/provider conventions",),
        }
        for name, clauses in obligations.items():
            for clause in clauses:
                with self.subTest(name=name, clause=clause):
                    self.assertIn(clause, " ".join(self.files[name].split()))

    def test_cloud_prose_guards_allow_whitespace_reflow(self):
        for name, original in self.files.items():
            with self.subTest(name=name):
                changed = dict(self.files)
                frontmatter = original.split("---", 2)
                prefix, body = ("---" + frontmatter[1] + "---", frontmatter[2]) if (
                    original.startswith("---")) else ("", original)
                # Headings and table rows are structural; prose wrapping is not.
                changed[name] = prefix + "\n".join(
                    line if line.startswith(("#", "|")) else line.replace(" ", " \n\t ")
                    for line in body.split("\n"))
                self.assertEqual(cloud_contract_errors(changed), [])

    def test_cloud_and_installation_guards_cannot_be_removed(self):
        for name in ("infrastructure", "bootstrapper", "terraform", "iac", "coverage", "matrix", "helm"):
            for marker in ("installed", "infrastructure.cloud: azure"):
                with self.subTest(name=name, marker=marker):
                    self.assert_mutation_detected(
                        name, marker, "removed", name + " missing " + marker)

    def test_hybrid_requires_evidence_and_documented_scope(self):
        for name in ("infrastructure", "bootstrapper", "terraform", "iac", "coverage", "matrix", "helm"):
            for marker in ("Azure resource subset", "document that scope"):
                with self.subTest(name=name, marker=marker):
                    self.assert_mutation_detected(
                        name, marker, "removed", name + " missing " + marker)

    def test_azure_routes_cannot_be_ungated_even_with_global_warning(self):
        for skill in ("bicep-implementation", "terraform-azure-implementation",
                      "import-infrastructure-as-code", "azure-deployment-preflight"):
            row = next(line for line in self.files["infrastructure"].splitlines()
                       if line.startswith("|") and "`" + skill + "`" in line)
            with self.subTest(skill=skill):
                self.assert_mutation_detected(
                    "infrastructure", row, row.split(" | ")[0] + " | **`" + skill + "`** |",
                    "ungated route " + skill)
                self.assert_mutation_detected(
                    "infrastructure", row, row.replace("installed and", "installed or"),
                    "ungated route " + skill)
        for skill in ("terraform-azure-implementation", "import-infrastructure-as-code"):
            with self.subTest(coverage=skill):
                self.assert_mutation_detected(
                    "matrix",
                    "`" + skill + "` — Azure-only, subject to the applicability gate below",
                    "`" + skill + "` — covers all providers without the applicability gate",
                    "ungated coverage " + skill)

    def test_broad_terraform_triggers_and_recommendations_are_rejected(self):
        self.assert_mutation_detected(
            "terraform", "USE FOR writing, modifying or migrating Terraform for a declared Azure target",
            "USE FOR any request to write, add, modify, or refactor `.tf` files",
            "overbroad Terraform description")
        self.assert_mutation_detected(
            "bootstrapper", "| `infrastructure.iac_tool` + provider needs |",
            "| `infrastructure.iac_tool` | `terraform` |",
            "provider-blind Terraform recommendation")
        self.assert_mutation_detected(
            "terraform", "Azure state backend alone does not establish",
            "Azure state backend establishes", "backend mistaken for resource provider")

    def test_correct_platform_reference_is_required_and_resolves(self):
        for replacement in ("azure-platform-conventions", "removed"):
            with self.subTest(replacement=replacement):
                self.assert_mutation_detected(
                    "iac", "azure-platform-grounding", replacement,
                    "missing correct platform reference")
        self.assertTrue((
            ROOT / "plugins/agile-agents-azure/skills/azure-platform-grounding/SKILL.md"
        ).is_file())

    def test_generic_caf_and_provider_defaults_are_rejected(self):
        self.assert_mutation_detected(
            "iac", "**Azure-only default:**",
            "Use the **Microsoft Cloud Adoption Framework abbreviations**",
            "generic CAF naming")
        for marker, legacy in (
            ("declared platform's secrets store", "Key Vault"),
            ("Preserve the repo's selected backend", "Backend in azurerm"),
            ("tool/provider's preview", "Azure preview"),
        ):
            with self.subTest(marker=marker):
                self.assert_mutation_detected(
                    "iac", marker, legacy, "platform assumption missing guard " + marker)

    def test_provider_fallback_and_generic_import_remain_explicit(self):
        for name in ("infrastructure", "bootstrapper", "terraform", "iac", "coverage", "matrix", "helm"):
            with self.subTest(name=name):
                self.assert_mutation_detected(
                    name, "repo/provider conventions", "Azure conventions",
                    name + " missing repo/provider conventions")
        marker = "Do not count generic import support as non-Azure implementation coverage"
        self.assert_mutation_detected(
            "bootstrapper", marker, "Generic imports cover all providers",
            "bootstrap missing " + marker)
        self.assert_mutation_detected(
            "helm", "installed capabilities", "Azure capabilities",
            "cluster route missing installed")


def testing_contract_errors(files):
    """Text contracts for author-owned testing, not proof of model behaviour."""
    errors = []
    text = {name: " ".join(body.replace("`", "").split())
            for name, body in files.items()}
    for name in ("csharp", "python", "polyglot"):
        for marker in ("invoking coding author", "may fix production logic",
                       "never weaken assertions", "Existing tests modified",
                       "what the old assertion claimed", "why it was invalid"):
            if marker not in text[name]:
                errors.append(name + " missing " + marker)

    for name in ("csharp", "python", "polyglot", "prompt"):
        body = text[name]
        if re.search(r"Don't (?:change|modify) production code|push back to coding", body):
            errors.append(name + " split ownership")
        if re.search(r"(?:Invoke|invoke|Call|call|delegate to|hand off to) (?:the )?coding\b", body):
            errors.append(name + " self delegation")
        if re.search(r"adjust (?:test expectations|expected(?: values)? to pass)", body, re.I):
            errors.append(name + " unsafe expectation repair")

    for name in ("polyglot", "prompt"):
        body = text[name]
        if re.search(
                r"\b(?:invoke|call|delegate to) (?:the )?(?:polyglot-test-agent|testing-practices)\b",
                body, re.I):
            errors.append(name + " recursive fallback")
        if re.search(
                r"polyglot-test-(?:generator|researcher|planner|implementer|builder|tester|fixer|linter)\b",
                body):
            errors.append(name + " nonexistent agent")
        for marker in (".testagent", "80%", "VS Code", "multi-agent pipeline"):
            if marker in body:
                errors.append(name + " stale " + marker)
        if "testing-practices" not in body:
            errors.append(name + " missing shared practices")

    for marker in ("current author", "Do not self-delegate", "Do not re-enter",
                   "installed", "repo conventions", "test manifests", "CI",
                   "happy path", "boundary", "negative path",
                   "targeted tests", "full suite", "lint", "format",
                   "tech_stack.coverage_threshold", "not measured",
                   "IMPLEMENTATION COMPLETE"):
        if marker not in text["polyglot"]:
            errors.append("polyglot missing " + marker)
    description = files["polyglot"].split("---", 2)[1]
    if ("name: polyglot-test-agent" not in description
            or "fallback" not in description
            or "no matching language testing skill is installed" not in description):
        errors.append("polyglot identity or fallback drift")
    if "polyglot-test-agent" not in text["practices"]:
        errors.append("fallback caller missing")
    if "reference only; do not execute its author workflow" not in text["reviewer"]:
        errors.append("reviewer author workflow")
    return errors


class TestingOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.files = {}
        for key, plugin, skill in (
            ("csharp", "dotnet", "csharp-testing"),
            ("python", "python", "python-testing"),
            ("polyglot", "core", "polyglot-test-agent"),
            ("practices", "core", "testing-practices"),
        ):
            self.files[key] = (
                ROOT / "plugins" / ("agile-agents-" + plugin) / "skills" / skill / "SKILL.md"
            ).read_text(encoding="utf-8")
        self.files["prompt"] = (
            CORE / "skills/polyglot-test-agent/unit-test-generation.prompt.md"
        ).read_text(encoding="utf-8")
        self.files["reviewer"] = (
            CORE / "agents/test-reviewer.agent.md"
        ).read_text(encoding="utf-8")

    def assert_mutation_detected(self, name, old, new, expected):
        changed = dict(self.files)
        pattern = re.escape(old).replace(r"\ ", r"\s+")
        self.assertRegex(changed[name], pattern)
        changed[name] = re.sub(pattern, lambda _: new, changed[name])
        self.assertIn(expected, testing_contract_errors(changed))

    def test_author_owned_testing_contracts_match(self):
        self.assertEqual(testing_contract_errors(self.files), [])

    def test_production_fix_permission_and_assertion_accountability_are_required(self):
        for name in ("csharp", "python", "polyglot"):
            for marker in ("invoking `coding` author", "may fix production logic",
                           "never weaken assertions", "Existing tests modified",
                           "what the old assertion claimed", "why it was invalid"):
                with self.subTest(name=name, marker=marker):
                    self.assert_mutation_detected(
                        name, marker, "removed", name + " missing " + marker.replace("`", ""))

    def test_legacy_production_bans_are_rejected_even_with_new_permission(self):
        for name in ("csharp", "python", "polyglot", "prompt"):
            for ban in ("Don't change production code to make a test pass — push back to `coding`.",
                        "Don't modify production code to make a test pass."):
                with self.subTest(name=name, ban=ban):
                    changed = dict(self.files)
                    changed[name] += "\n" + ban
                    self.assertIn(name + " split ownership", testing_contract_errors(changed))

    def test_nonexistent_agents_are_rejected_in_skill_and_adjacent_prompt(self):
        for name in ("polyglot", "prompt"):
            for role in ("generator", "researcher", "planner", "implementer",
                         "builder", "tester", "fixer", "linter"):
                with self.subTest(name=name, role=role):
                    changed = dict(self.files)
                    changed[name] += "\nInvoke `polyglot-test-" + role + "`."
                    self.assertIn(name + " nonexistent agent", testing_contract_errors(changed))

    def test_scaffolding_editor_prerequisite_and_invented_target_are_rejected(self):
        for name in ("polyglot", "prompt"):
            for legacy in (".testagent", "80%", "VS Code", "multi-agent pipeline"):
                with self.subTest(name=name, legacy=legacy):
                    changed = dict(self.files)
                    changed[name] += "\nRequired: " + legacy
                    self.assertIn(name + " stale " + legacy, testing_contract_errors(changed))

    def test_fallback_cannot_reinvoke_itself_or_its_router(self):
        for name in ("polyglot", "prompt"):
            for target in ("polyglot-test-agent", "testing-practices"):
                with self.subTest(name=name, target=target):
                    changed = dict(self.files)
                    changed[name] += "\nInvoke `" + target + "` again to choose the workflow."
                    self.assertIn(name + " recursive fallback", testing_contract_errors(changed))

    def test_unsafe_failure_advice_and_coding_self_delegation_are_rejected(self):
        for name in ("csharp", "python", "polyglot", "prompt"):
            for advice, error in (
                ("Review the test output and adjust test expectations.", "unsafe expectation repair"),
                ("Adjust expected to pass.", "unsafe expectation repair"),
                ("Invoke the `coding` agent to fix it.", "self delegation"),
            ):
                with self.subTest(name=name, advice=advice):
                    changed = dict(self.files)
                    changed[name] += "\n" + advice
                    self.assertIn(name + " " + error, testing_contract_errors(changed))

    def test_fallback_discovery_execution_and_handoff_cannot_be_removed(self):
        for marker in ("current author", "Do not self-delegate", "Do not re-enter",
                       "installed", "repo conventions", "test manifests", "CI",
                       "happy path", "boundary", "negative path", "targeted tests",
                       "full suite", "lint", "format", "tech_stack.coverage_threshold",
                       "not measured", "IMPLEMENTATION COMPLETE"):
            with self.subTest(marker=marker):
                self.assert_mutation_detected(
                    "polyglot", marker, "removed", "polyglot missing " + marker)

    def test_shared_practices_and_reference_only_reviewer_are_required(self):
        for name in ("polyglot", "prompt"):
            with self.subTest(name=name):
                self.assert_mutation_detected(
                    name, "testing-practices", "removed", name + " missing shared practices")
        self.assert_mutation_detected(
            "reviewer", "reference only; do not execute its author workflow",
            "execute its author workflow", "reviewer author workflow")
        self.assert_mutation_detected(
            "practices", "polyglot-test-agent", "removed", "fallback caller missing")

    def test_skill_name_and_narrow_fallback_description_are_preserved(self):
        for marker in ("name: polyglot-test-agent",
                       "no matching language testing skill is installed"):
            with self.subTest(marker=marker):
                self.assert_mutation_detected(
                    "polyglot", marker, "removed", "polyglot identity or fallback drift")


if __name__ == "__main__":
    unittest.main()
