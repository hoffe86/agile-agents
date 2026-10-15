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


# Independent oracle: never derive expected names from the contracts under test.
# Parenthetical applicability and the backlog's table columns are part of the shape.
HANDOFF_FIELDS = {
    "architect": ("ARCHITECTURE DESIGN COMPLETE", (
        "Topic", "Deliverables", "Framework used", "Recommendation", "Key tradeoffs",
        "NFRs to honour", "Decisions honoured",
        "Decision gaps (need a human decision before coding)", "Facts verified",
        "Assumptions (unverified)", "Well-architected assessment (cloud designs)",
        'Data findings (when the change touches data, else "n/a — no data surface")',
        'Data questions to answer before building (else "none")',
        "Estimated monthly cost band (if cloud-hosted)", "Open questions / risks",
        "Findings addressed", "Recommended next step",
    )),
    "coding": ("IMPLEMENTATION COMPLETE", (
        "Files changed", "Test files changed", "ADRs honoured", "Docs updated",
        "Behavior added/modified", "Public surface added/changed", "Internal-only changes",
        "Build status", "Test run", "Coverage on touched files", "Existing tests modified",
        "Startup verified", "Findings addressed", "Unmet design constraint (if any)",
        "Open questions for review",
    )),
    "infrastructure": ("INFRASTRUCTURE COMPLETE", (
        "Technology", "Files changed", "ADRs honoured", "Docs updated", "Scope",
        "Plan / what-if summary", "Verified modules used (with versions)", "Validation",
        "Secrets touched", "Findings addressed", "Open items for review",
        "IaC tests authored / run", "Behavior added/modified", "Existing tests modified",
        "Recommended next step",
    )),
    "data-scientist": ("ANALYSIS COMPLETE", (
        "Question", "Outcome", "Files changed", "Data used", "Method", "Baseline", "Result",
        "Split & leakage", "Cohort breakdown", "Reproducibility",
        "Dataset status (if you produced one)", "Unmeasured risks",
        "Not verifiable from this diff", "Code verification",
        "Interface for `coding` (if a model ships)", "Findings addressed",
        "Open questions for review",
    )),
    "review-lead": ("REVIEW COMPLETE", (
        "Verdict", "Specialists invoked", "Open findings", "Findings by owner",
        "Files changed", "Recommended next step",
    )),
    "backlog-manager": ("TASKS PLANNED", (
        "Tracker platform", "Parent work item", "Link pattern",
        "Tasks created (provisional, tag `pending-approval`)",
        "Approach comment posted on parent", "Open items / could not link",
    )),
    "bootstrapper": ("BOOTSTRAP COMPLETE", (
        "Profile", "Required fields", "Plugins installed this run", "Plugins already present",
        "Declared but unsupported", "Gaps for the user", "Ready for delivery",
    )),
}
CORRECTIVE_AUTHORS = ("architect", "coding", "infrastructure", "data-scientist")
SCHEMA_CLAUSES = {
    "architect": (
        "Research/design evidence, not permission to invent a decision",
        "Never promote an assumption to a verified fact",
        "**State blockers first**",
        "Each becomes a `data-scientist` task sequenced ahead",
        "Omit on a first pass.",
    ),
    "coding": (
        "Application code and its tests are one hand-off",
        '"none" only when the change is genuinely untestable, with the reason',
        '"<behaviour> → <test name>"', "why you stopped rather than weakening them",
        "what the old assertion claimed and why it was invalid",
        "n/a — change doesn't touch startup",
        "⚠️ couldn't determine — <reason>",
        "Omit the field entirely on a first pass.",
    ),
    "infrastructure": (
        "IaC validation and IaC tests, not application build/test fields",
        "n/a only with a reason no executable test applies",
        "changed/deleted/newly-skipped test: old assertion and why it was invalid",
        "Omit the field entirely on a first-pass implementation.",
    ),
    "data-scientist": (
        "✅ supported", "⚠️ inconclusive", "❌ not supported",
        "⚠️ and ❌ are legitimate completed outcomes, not failures",
        "Do not retry to manufacture a ✅",
        "reports it as a gap rather than assuming it was done",
        '"nothing" is a valid answer',
        "n/a — no reusable code changed, with reason",
        "build/test commands and results; each code behavior → test name",
        "existing tests modified: none or old assertion and why it was invalid",
        "Omit on a first pass.",
    ),
    "review-lead": (
        "keep the full specialist reports and the role's merging rubric",
        "✅ Approve | 🔁 Request changes | ❌ Block", "with skip reasons",
    ),
    "backlog-manager": (
        "on the Plan workflow only", "provisional, tag `pending-approval`",
        "yes — <comment link or id>",
    ),
    "bootstrapper": (
        "`Ready for delivery: no` blocks entry to Stage 1",
        '<created | repaired | already valid>', "yes | no — <what blocks it>",
    ),
}
HANDOFF_PATHS = {
    name: Path("agents") / (name + ".agent.md")
    for name in (*HANDOFF_FIELDS, "dev-lead")
}
HANDOFF_PATHS.update({
    "read-repo-context": Path("skills/read-repo-context/SKILL.md"),
    "handoff-contracts": Path("skills/read-repo-context/references/handoff-contracts.md"),
})


def load_handoff_files(core=CORE):
    return {name: (core / path).read_text(encoding="utf-8")
            for name, path in HANDOFF_PATHS.items()}


def named_contract_section(body, heading):
    """Only our level-two sections, ignoring headings inside fenced examples."""
    sections = []
    current = None
    fenced = False
    for line in body.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            current = (line[3:].strip(), [])
            sections.append(current)
        elif current:
            current[1].append(line)
    matches = [lines for title, lines in sections if title == heading]
    if len(matches) != 1:
        raise ValueError("missing or duplicate section " + heading)
    return "\n".join(matches[0])


def resolve_handoff_section(files, source, heading, core=CORE):
    """Test-only bounded file/heading resolver, not a runtime schema parser."""
    anchor = heading.lower().replace(" ", "-")
    links = re.findall(r"\]\(([^)]+\.md)#([^)]+)\)", files[source])
    matches = [path for path, fragment in links if fragment == anchor]
    if source == "read-repo-context" and heading != "Corrective accounting":
        # The always-loaded receiver uses one file link plus an exact-heading
        # rule instead of preloading a seven-link routing table.
        rule = "level-two section whose heading equals the received sentinel"
        matches = re.findall(r"\[handoff-contracts\.md\]\(([^)#]+\.md)\)", files[source]) if (
            rule in " ".join(files[source].split())) else []
    if len(matches) != 1:
        raise ValueError(source + " missing or duplicate reference " + heading)
    # Loaded artifact location, not cwd. Even an existing different file is wrong.
    target = (core / HANDOFF_PATHS[source]).parent / matches[0]
    if target.resolve() != (core / HANDOFF_PATHS["handoff-contracts"]).resolve():
        raise ValueError(source + " wrong contract file " + heading)
    if "handoff-contracts" not in files:
        raise ValueError("missing contract file")
    return named_contract_section(files["handoff-contracts"], heading)


def schema_block(section, sentinel):
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", section, re.M | re.S)
    matches = [block for block in blocks
               if block.splitlines()[0].removeprefix("## ") == sentinel]
    if len(matches) != 1:
        raise ValueError("missing or duplicate definition " + sentinel)
    return matches[0]


def handoff_contract_errors(files, core=CORE):
    """Offline field, routing and accounting regressions; no model execution."""
    errors = []
    if any(re.search(r"^(?:## )?TESTS COMPLETE\s*\n\s*-\s+", body, re.M)
           for body in files.values()):
        errors.append("retired TESTS COMPLETE definition")
    for author, (sentinel, expected) in HANDOFF_FIELDS.items():
        for source in (author, "dev-lead", "read-repo-context"):
            try:
                section = resolve_handoff_section(files, source, sentinel, core)
                block = schema_block(section, sentinel)
            except ValueError as error:
                errors.append(str(error))
                continue
            pattern = r"^\*\*([^:]+):\*\*" if author == "backlog-manager" else r"^-\s+([^:]+):"
            fields = tuple(" ".join(field.split())
                           for field in re.findall(pattern, block, re.M))
            if fields != expected:
                errors.append(sentinel + " field shape drift")
            for clause in SCHEMA_CLAUSES[author]:
                if clause not in " ".join(section.split()):
                    errors.append(sentinel + " missing semantics " + clause)
            if author == "backlog-manager" and "| Task id | Title | ACs | State |" not in (
                    " ".join(block.split())):
                errors.append("TASKS PLANNED table shape drift")
        # A sentinel mention is fine; a second field definition anywhere in the
        # routed artifacts is not (even if its fence was removed).
        definition = re.compile(
            r"^(?:## )?" + re.escape(sentinel) + r"\s*\n\s*(?:-\s+|\*\*)", re.M)
        count = sum(len(definition.findall(body)) for body in files.values())
        if count != 1:
            errors.append(sentinel + " duplicate or missing definition")
        inline = re.findall(r"^-\s+([^:\n]+):", files[author], re.M)
        if set(inline) & set(expected):
            errors.append(author + " inline field definition")

    for source in (*CORRECTIVE_AUTHORS, "review-lead", "dev-lead", "read-repo-context"):
        try:
            resolve_handoff_section(files, source, "Corrective accounting", core)
        except ValueError as error:
            errors.append(str(error))

    for source in HANDOFF_PATHS.keys() - {"handoff-contracts"}:
        text = " ".join(files[source].split())
        for clause in ("read only", "loaded core", "not the consumer repository's working directory",
                       "malformed contract/context", "do not reconstruct the schema"):
            if clause not in text:
                errors.append(source + " missing loading guard " + clause)
        timing = ("At the beginning of a Plan task" if source == "backlog-manager"
                  else "At the beginning of each task")
        if source == "dev-lead":
            timing = "Before dispatch and on receipt"
        elif source == "read-repo-context":
            timing = "On receipt"
        if timing not in text:
            errors.append(source + " missing loading timing")

    try:
        accounting = " ".join(named_contract_section(
            files.get("handoff-contracts", ""), "Corrective accounting").split())
        for clause in (
            "`Findings addressed` is omitted on a first pass",
            "**every routed finding id**, one line per id",
            "`fixed` — evidence at the changed file:line or deliverable/location",
            "analysis fixes identify the changed artifact and evidence",
            "`disputed` — the reason the finding is wrong or already handled",
            "`not mine` — the named owner to whom it must be routed",
            "A fixer's claim does not close a finding",
            "Missing ids are a malformed hand-off",
            "Preserve original finding ids across re-review",
            "`review-lead` adjudicates with the independent specialists",
            "The supervisor alone owns the findings ledger, retry budgets and corrective re-verification",
        ):
            if clause not in accounting:
                errors.append("corrective accounting missing " + clause)
        for author in CORRECTIVE_AUTHORS:
            section = named_contract_section(files["handoff-contracts"], HANDOFF_FIELDS[author][0])
            field = re.search(r"^-\s+Findings\s+addressed:\s*(.*?)(?=^-\s|\Z)",
                              section, re.M | re.S)
            if not field or not all(part in " ".join(field[1].split())
                                    for part in ("corrective rounds only", "Omit")):
                errors.append(author + " lost corrective applicability")
    except ValueError as error:
        errors.append(str(error))
    return errors


class SharedHandoffTests(unittest.TestCase):
    def setUp(self):
        self.files = load_handoff_files()

    def test_seven_schemas_and_bounded_loading_match(self):
        self.assertEqual(handoff_contract_errors(self.files), [])

    def test_missing_or_renamed_field_fails_independent_oracle(self):
        for author, (sentinel, fields) in HANDOFF_FIELDS.items():
            section = named_contract_section(self.files["handoff-contracts"], sentinel)
            for field in fields:
                prefix = ("**" + field + ":**" if author == "backlog-manager"
                          else "- " + field + ":")
                for replacement in ("", prefix.replace(field, "Renamed field")):
                    with self.subTest(author=author, field=field, replacement=replacement):
                        self.assertIn(prefix, section)
                        changed = dict(self.files)
                        changed["handoff-contracts"] = changed["handoff-contracts"].replace(
                            section, section.replace(prefix, replacement))
                        self.assertIn(sentinel + " field shape drift",
                                      handoff_contract_errors(changed))

    def test_backlog_table_columns_are_part_of_schema(self):
        changed = dict(self.files)
        changed["handoff-contracts"] = changed["handoff-contracts"].replace(
            "| Task id | Title | ACs | State |", "| Task id | Title | ACs |")
        self.assertIn("TASKS PLANNED table shape drift", handoff_contract_errors(changed))

    def test_missing_file_and_heading_fail_explicitly(self):
        changed = dict(self.files)
        del changed["handoff-contracts"]
        self.assertIn("missing contract file", handoff_contract_errors(changed))
        for sentinel, _ in HANDOFF_FIELDS.values():
            with self.subTest(sentinel=sentinel):
                changed = dict(self.files)
                changed["handoff-contracts"] = changed["handoff-contracts"].replace(
                    "## " + sentinel + "\n", "## Renamed section\n", 1)
                self.assertIn("missing or duplicate section " + sentinel,
                              handoff_contract_errors(changed))

    def test_wrong_section_missing_link_and_wrong_file_fail_at_each_route(self):
        for author, (sentinel, _) in HANDOFF_FIELDS.items():
            anchor = sentinel.lower().replace(" ", "-")
            for source in (author, "dev-lead", "read-repo-context"):
                for replacement in (
                    "handoff-contracts.md#corrective-accounting",
                    "missing.md#" + anchor,
                    "SKILL.md#" + anchor,
                    "unlinked",
                ):
                    with self.subTest(source=source, sentinel=sentinel, replacement=replacement):
                        changed = dict(self.files)
                        old = ("handoff-contracts.md)" if source == "read-repo-context"
                               else "handoff-contracts.md#" + anchor)
                        new = replacement + ")" if source == "read-repo-context" else replacement
                        self.assertIn(old, changed[source])
                        changed[source] = changed[source].replace(old, new)
                        self.assertTrue(handoff_contract_errors(changed))

    def test_duplicate_definitions_fail_in_reference_and_inline(self):
        for author, (sentinel, _) in HANDOFF_FIELDS.items():
            block = schema_block(named_contract_section(
                self.files["handoff-contracts"], sentinel), sentinel)
            for destination in ("handoff-contracts", author, "dev-lead", "read-repo-context"):
                with self.subTest(author=author, destination=destination):
                    changed = dict(self.files)
                    changed[destination] += "\n```\n" + block + "```\n"
                    self.assertIn(sentinel + " duplicate or missing definition",
                                  handoff_contract_errors(changed))

    def test_duplicate_heading_is_not_resolved_arbitrarily(self):
        changed = dict(self.files)
        changed["handoff-contracts"] += "\n## IMPLEMENTATION COMPLETE\nWrong section.\n"
        self.assertIn("missing or duplicate section IMPLEMENTATION COMPLETE",
                      handoff_contract_errors(changed))

    def test_inline_fields_without_sentinel_are_still_duplicates(self):
        changed = dict(self.files)
        changed["coding"] += "\n- Test run: <result>\n"
        self.assertIn("coding inline field definition", handoff_contract_errors(changed))

    def test_retired_test_only_handoff_cannot_return(self):
        changed = dict(self.files)
        changed["coding"] += "\n```\nTESTS COMPLETE\n- Test run: <result>\n```\n"
        self.assertIn("retired TESTS COMPLETE definition", handoff_contract_errors(changed))

    def test_receiver_requires_exact_sentinel_heading_rule(self):
        changed = dict(self.files)
        changed["read-repo-context"] = changed["read-repo-context"].replace(
            "equals the received sentinel", "looks relevant")
        self.assertIn("read-repo-context missing or duplicate reference IMPLEMENTATION COMPLETE",
                      handoff_contract_errors(changed))

    def test_role_specific_semantics_cannot_be_lost(self):
        for author, clauses in SCHEMA_CLAUSES.items():
            sentinel = HANDOFF_FIELDS[author][0]
            section = named_contract_section(self.files["handoff-contracts"], sentinel)
            for clause in clauses:
                with self.subTest(author=author, clause=clause):
                    pattern = re.escape(clause).replace(r"\ ", r"\s+")
                    self.assertRegex(section, pattern)
                    changed = dict(self.files)
                    changed["handoff-contracts"] = changed["handoff-contracts"].replace(
                        section, re.sub(pattern, "removed", section))
                    self.assertIn(sentinel + " missing semantics " + clause,
                                  handoff_contract_errors(changed))

    def test_corrective_accounting_loss_is_rejected(self):
        for clause in (
            "`Findings addressed` is omitted on a first pass",
            "**every routed finding id**, one line per id",
            "`fixed` — evidence at the changed file:line or deliverable/location",
            "analysis fixes identify the changed artifact and evidence",
            "`disputed` — the reason the finding is wrong or already handled",
            "`not mine` — the named owner to whom it must be routed",
            "A fixer's claim does not close a finding",
            "Missing ids are a malformed hand-off",
            "Preserve original finding ids across re-review",
            "`review-lead` adjudicates with the independent specialists",
            "The supervisor alone owns the findings ledger, retry budgets and corrective re-verification",
        ):
            with self.subTest(clause=clause):
                pattern = re.escape(clause).replace(r"\ ", r"\s+")
                changed = dict(self.files)
                self.assertRegex(changed["handoff-contracts"], pattern)
                changed["handoff-contracts"] = re.sub(pattern, "removed", changed["handoff-contracts"])
                self.assertIn("corrective accounting missing " + clause,
                              handoff_contract_errors(changed))

    def test_corrective_routes_are_required_for_fixers_and_receivers(self):
        for source in (*CORRECTIVE_AUTHORS, "review-lead", "dev-lead", "read-repo-context"):
            with self.subTest(source=source):
                changed = dict(self.files)
                changed[source] = changed[source].replace("#corrective-accounting", "#missing")
                self.assertIn(source + " missing or duplicate reference Corrective accounting",
                              handoff_contract_errors(changed))

    def test_loading_timing_and_fail_closed_policy_cannot_be_removed(self):
        for source in HANDOFF_PATHS.keys() - {"handoff-contracts"}:
            for clause in ("read only", "loaded core",
                           "not the consumer repository's working directory",
                           "malformed contract/context", "do not reconstruct the schema"):
                with self.subTest(source=source, clause=clause):
                    changed = dict(self.files)
                    pattern = re.escape(clause).replace(r"\ ", r"\s+")
                    changed[source] = re.sub(pattern, "removed", changed[source])
                    self.assertIn(source + " missing loading guard " + clause,
                                  handoff_contract_errors(changed))
            with self.subTest(source=source, timing=True):
                changed = dict(self.files)
                changed[source] = re.sub(
                    r"At the beginning|Before dispatch and on receipt|On receipt",
                    "Whenever convenient", changed[source])
                self.assertIn(source + " missing loading timing", handoff_contract_errors(changed))

    def test_prose_and_field_value_reflow_is_not_contract_drift(self):
        # Preserve Markdown structural lines and link targets; wrap prose and
        # field values, including spaces within labels, without changing words.
        changed = dict(self.files)
        original = changed["handoff-contracts"]
        changed["handoff-contracts"] = "\n".join(
            line.replace(" ", " \n\t ") if (
                line and not line.startswith(("#", "```", "|"))
                and line not in {sentinel for sentinel, _ in HANDOFF_FIELDS.values()}
            ) else line
            for line in original.splitlines()
        )
        self.assertEqual(handoff_contract_errors(changed), [])

    def test_installed_layout_resolves_from_loaded_artifact_not_consumer(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp) / "installed/plugins/agile-agents-core"
            consumer = Path(temp) / "consumer"
            # A contradictory consumer-local file must never supply the schema.
            decoy = consumer / HANDOFF_PATHS["handoff-contracts"]
            decoy.parent.mkdir(parents=True)
            decoy.write_text("## IMPLEMENTATION COMPLETE\nWrong schema.", encoding="utf-8")
            for name, path in HANDOFF_PATHS.items():
                target = installed / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.files[name], encoding="utf-8")
            loaded = load_handoff_files(installed)
            self.assertEqual(handoff_contract_errors(loaded, installed), [])
            section = resolve_handoff_section(
                loaded, "coding", "IMPLEMENTATION COMPLETE", installed)
            self.assertIn("- Test run:", section)
            self.assertNotIn("Wrong schema", section)


# Independent routing oracle: never derive the expected destination from the
# production pointer under test. These helpers are offline test code only.
TEMPLATE_HOME = Path("skills/dev-lead-templates")
STAGE_RECIPES = {
    0: ("intake-plan", "Stage 0"),
    1: ("intake-plan", "Stage 1"),
    2: ("intake-plan", "Stage 2"),
    3: ("intake-plan", "Stage 3"),
    4: ("plan-approval", "Prompt"),
    5: ("design-approval", "Prompt"),
    6: ("implementation-review", "Stage 6"),
    7: ("implementation-review", "Stage 7"),
    8: ("implementation-review", "Stage 8"),
    9: ("completion", "Stage 9"),
}
TEMPLATE_PATHS = {
    name: TEMPLATE_HOME / "references" / (name + ".md")
    for name in ("intake-plan", "implementation-review", "completion",
                 "plan-approval", "design-approval", "done-report")
}
TEMPLATE_PATHS["dev-lead-templates"] = TEMPLATE_HOME / "SKILL.md"

# Location matters: these controls must remain resident in their owning stage.
# Recipe prose cannot satisfy this oracle by copying a lost gate into a reference.
STAGE_CONTROLS = {
    0: ("delegate to `bootstrapper`", "`Ready for delivery`",
        "**You may not enter Stage 1 until all six are populated.**",
        "derived list reach Stage 9 unconfirmed", "stop condition #10",
        "stop condition #12", "run_started_at", "never replace it",
        "external-project", "halt with `ask_user`", "USD as *unmetered*, never `0.00`"),
    1: ("**Entry:** Stage 0 passed", "Read-only", "Lightweight",
        "Delegate to `architect`", "Stage 1 blocker", "does not analyse data",
        "decision gap", "NFRs and security posture", "verified with a source",
        "one** corrective message", "stop and ask the human"),
    2: ("independently-implementable tasks", "feasibility goes first",
        "never bundled with a model task", "stop condition #3",
        "every requirement AC maps", "out-of-scope", "every step in the source plan",
        "never skip Review", "todo_deps", "tracker wins on conflict"),
    3: ("delegate to `backlog-manager`", "`TASKS PLANNED`",
        "`pending-approval`", "every task linked to the parent",
        "stop condition #11", "never silently fall back to file-only planning",
        "`backlog.create_tasks` is false", "`backlog.platform: none`"),
    4: ("**Entry:** Stage 3 passed", "**Approve**", "**Adjust**", "**Cancel**",
        "Stage 5 conditional design approval", "only after that gate passes",
        "No silent re-planning", "user cancelled at plan gate",
        "List ids that could not be cleaned up", "derived acceptance criteria"),
    5: ("after** the mandatory plan approval", "**before** coding",
        "Read this prompt only when the conditional gate triggers",
        "only when ALL apply", "`architect` actually ran",
        "new external dependency", "non-trivial", "decision gap",
        "**Approve**", "**Adjust**", "**Stop**",
        "architect stage's one corrective retry", "one Adjust round per run",
        "persisted across resume", "second Adjust is not allowed",
        "user stopped at design gate"),
    6: ("Stage 4 approved and Stage 5 passed", "`coding`", "`infrastructure`",
        "`data-scientist`", "scope question for the human",
        "no separate testing agent", "must never weaken a test",
        "all dependencies are `done`", "dependency cycle",
        "Deliver tasks sequentially", "do not dispatch implementation tasks in parallel",
        "safe only for **read-only** agents", "Existing tests modified",
        "deleted test", "newly-skipped test", "stop condition #9",
        "all three pass this gate", "Never send a corrective round asking for a better result",
        "baseline", "uncertainty", "split rule, seed and leakage checks",
        "Cohort breakdown", "Unmeasured risks", "Not verifiable from this diff",
        "Dataset status", "Code verification", "stop condition #3",
        "one** corrective message", "never start the next task",
        "Advance to Stage 7 only when every task is `done`"),
    7: ("every Stage 6 task is `done`", "Skip 7a only", "**run 7a**",
        "Missing or invalid configuration exits 2", "not a successful skip",
        "lint → typecheck → unit-test → smoke", "not_applicable", "undetermined",
        "staged and unstaged diffs", "content hashes of relevant untracked files",
        "before and after verification", "result is stale",
        "Only when 7a passed **and**", "`infrastructure.deploy_verify` is `dev`",
        "Never production", "per deterministic gate", "does **not reset**",
        "not itself a corrective retry", "3rd fail", "4th fail",
        "Halt the run", "Do not call reviewers", "quota, policy denial",
        "halts immediately with no retry"),
    8: ("**Delegate to:** `review-lead`", "quality and security unconditionally",
        "`review-lead` always invokes `security-reviewer`",
        "owns mandatory secret scanning", "all other applicable review lenses remain independent",
        "Existing tests modified", "Verdict is **✅ Approve**",
        "Zero 🔴 Critical", "Zero 🟠 Major",
        "only the finding ids that name it as owner", "Missing ids are a malformed hand-off",
        "Re-route anything marked `not mine`", "A `disputed` finding stays open",
        "Re-verify before re-review", "failed rerun prevents reviewer dispatch",
        "No-edit disputes retain valid evidence",
        "at most three corrective rounds", "does not reset this separate counter",
        "If a round closes nothing", "stop condition #7",
        "Only you write the session ledger", "a fixer's claim cannot close a finding",
        "separate review-round counter", "session DB",
        "spent Research/per-task/malformed hand-off corrective attempts"),
    9: ("Verify requirement coverage first", "delivered", "evidence",
        "Set `status = 'covered'` only with both", "task marked `done` is not evidence",
        "covered only by a task that ended `blocked`", "do not report ✅ Done",
        "out-of-scope", "never counted as covered", "only now",
        "explicit user approval", "human-only, always",
        "PR-open approval is per-run and explicit", "never infer it from silence",
        "except the last", "contains `prod`", "run_started_at",
        "payload.cost_summary", "collector JSON unchanged",
        "Never invent zero usage", "payload.termination_reason",
        "only a fully verified delivery may use `outcome=success`"),
}
RECIPE_CONTENT = {
    0: ("CREATE TABLE IF NOT EXISTS requirement_acs", "ac_id TEXT PRIMARY KEY",
        "covered_by TEXT", "evidence TEXT", "status TEXT DEFAULT 'uncovered'",
        "content, not its filename", "mark each **derived**", "UUIDv7",
        "payload.requirement_summary", "payload.profile_loaded",
        "max_aiu_per_run", "max_aiu_per_phase", "max_tokens_per_run"),
    1: ("context7/*", "read-repo-context", "facts verified with sources",
        "assumptions with impacts", "Key tradeoffs", "Open questions / risks",
        "Data questions to answer before building", "approach summary"),
    2: ("Clear title", "Acceptance criteria", "Approach note",
        "tech_stack.test_discipline == bdd", "assumes `<fact>`; unverified",
        "grain, keys, schema and freshness", "every step",
        "INSERT INTO todos", "INSERT INTO todo_deps", "tracker child items"),
    3: ("parent work-item id", "title + ACs + approach note",
        "team_communication.code_language", "entry state", "pending-approval",
        "comment on the parent", "does not progress state"),
    4: ("Approve and run autonomously", "Adjust plan", "Cancel",
        "Acceptance criteria I derived", "Changes I made to your plan",
        "What dies if a feasibility task returns ❌", "Return the selected choice"),
    5: ("Approve and continue", "Adjust design", "Stop",
        "Decision gaps", "explicitly waive each gap", "Return the selected choice"),
    6: ("SELECT t.* FROM todos t", "t.status = 'pending'",
        "td.depends_on = dep.id", "dep.status != 'done'",
        "Design constraints (locked by Stage 1)", "allowed dependencies",
        "Interface for coding", "that task's"),
    7: ("scripts/run-gate.sh", "quality_gates.test_bar.<check>.command",
        "testing.smoke.command", "content hashes of relevant untracked files",
        "before **and** after verification", "structured failure report"),
    8: ("git diff <base>...HEAD", "Existing tests modified",
        "CREATE TABLE IF NOT EXISTS findings", "id TEXT PRIMARY KEY",
        "severity TEXT", "owner TEXT", "summary TEXT", "status TEXT DEFAULT 'open'",
        "note TEXT", "SELECT id, owner FROM findings WHERE status = 'open'"),
    9: ("SELECT ac_id, text, covered_by, evidence, status FROM requirement_acs",
        "WHERE status = 'uncovered'", "every** criterion", "previously covered rows",
        "backlog.branch_naming", "backlog.commit_convention", "required_commit_trailers",
        "identity.repo_url", "az repos pr create", "gh pr create",
        "backlog.pr_link_pattern", "pr-description", "release-notes"),
}


def load_stage_files(core=CORE):
    return {name: (core / path).read_text(encoding="utf-8")
            for name, path in TEMPLATE_PATHS.items()}


def lead_stage_section(lead, stage):
    matches = re.findall(
        r"^### Stage " + str(stage) + r" — [^\n]+\n(.*?)(?=^#{1,3} |\Z)",
        lead, re.M | re.S)
    if len(matches) != 1:
        raise ValueError("missing or duplicate resident stage " + str(stage))
    return matches[0]


def resolve_stage_recipe(files, stage, core=CORE):
    resident = lead_stage_section(files["dev-lead"], stage)
    pointers = re.findall(
        r"\*\*Required read:\*\*\s+`([^`]+)`\s+→\s+\*\*([^*]+)\*\*", resident)
    name, heading = STAGE_RECIPES[stage]
    expected_path = "references/" + name + ".md"
    if pointers != [(expected_path, heading)]:
        raise ValueError("wrong or missing required read at Stage " + str(stage))
    # Resolve from the loaded skill, never from the agent or consumer cwd.
    home = (core / TEMPLATE_PATHS["dev-lead-templates"]).parent
    if (home / pointers[0][0]).resolve() != (core / TEMPLATE_PATHS[name]).resolve():
        raise ValueError("wrong stage file")
    if name not in files:
        raise ValueError("missing recipe file " + name)
    anchor = heading.lower().replace(" ", "-")
    link = "](" + expected_path + "#" + anchor + ")"
    if files["dev-lead-templates"].count(link) != 1:
        raise ValueError("missing or duplicate skill route at Stage " + str(stage))
    return named_contract_section(files[name], heading)


def stage_contract_errors(files, core=CORE):
    errors = []
    lead = " ".join(files["dev-lead"].split())
    for clause in ("at each stage entry or resume", "load `dev-lead-templates`",
                   "relative to the loaded skill's home",
                   "not the consumer repository's working directory",
                   "missing/mismatched section", "stop and surface it",
                   "do not reconstruct", "never override the transitions"):
        if clause not in lead:
            errors.append("stage loading guard missing " + clause)
    skill = " ".join(files["dev-lead-templates"].split())
    for clause in ("exact named level-two section", "do not preload all sections",
                   "Missing file", "stop and surface malformed contract/context"):
        if clause not in skill:
            errors.append("skill loading guard missing " + clause)
    for stage in STAGE_RECIPES:
        try:
            resident = " ".join(lead_stage_section(files["dev-lead"], stage).split())
            recipe = " ".join(resolve_stage_recipe(files, stage, core).split())
        except ValueError as error:
            errors.append(str(error))
            continue
        for clause in STAGE_CONTROLS[stage]:
            if clause not in resident:
                errors.append("Stage %s resident control missing %s" % (stage, clause))
        for clause in RECIPE_CONTENT[stage]:
            if clause not in recipe:
                errors.append("Stage %s recipe missing %s" % (stage, clause))
    # All thirteen stops must remain in the autonomy contract, not in a recipe
    # or a similarly worded entry condition elsewhere.
    autonomy = files["dev-lead"].split("### Autonomy contract", 1)[-1].split("### Stage 0", 1)[0]
    stops = [(number, " ".join(title.split())) for number, title in
             re.findall(r"^\s+(\d+)\.\s+\*\*([^*]+)\*\*", autonomy, re.M)]
    expected_stops = (
        "Ambiguity that changes what is being delivered",
        "Gate failure that survives its stated retry budget",
        "Scope-change required to deliver", "Destructive or irreversible action proposed",
        "Secret or credential needed", "Specialist review verdict ❌ Block",
        "Open 🟠 Major review findings after the review-loop budget is spent",
        "Malformed or missing hand-off block", "In-flight architecture escalation",
        "Missing parent work-item id", "Tracker-write failure",
        "Required profile field still empty after the Stage 0 interview",
        "PR not yet approved",
    )
    if stops != [(str(i), title) for i, title in enumerate(expected_stops, 1)]:
        errors.append("resident stop conditions drift")
    if "auto-loop **once**" not in " ".join(autonomy.split()):
        errors.append("Block stop budget hidden")
    if "```sql" in files["dev-lead"]:
        errors.append("SQL recipe still resident")
    for name in ("plan-approval", "design-approval"):
        template = files.get(name, "")
        if "## Handling the answer" in template or re.search(r"^- \*\*(Approve|Adjust|Cancel|Stop)\*\* →", template, re.M):
            errors.append(name + " owns transitions")
    for name in ("intake-plan", "implementation-review", "completion"):
        if re.search(r"(?:max \d+ retries|at most three corrective rounds|Cap: one Adjust)",
                     files.get(name, "")):
            errors.append(name + " owns retry budget")
    for name, heading, owner in (
        ("intake-plan", "Tracker mechanics", "## Tracker status"),
        ("done-report", "Report", "### Stage 9"),
        ("completion", "Stage 9", "## Output format"),
        ("done-report", "Report", "## Output format"),
    ):
        region = files["dev-lead"].split(owner, 1)[-1]
        region = " ".join(re.split(r"\n#{1,3} ", region, maxsplit=1)[0].split())
        pointer = "`references/%s.md` → **%s**" % (name, heading)
        if pointer not in region:
            errors.append(owner + " missing auxiliary read " + heading)
        link = "](references/%s.md#%s)" % (name, heading.lower().replace(" ", "-"))
        if files["dev-lead-templates"].count(link) != 1:
            errors.append("missing auxiliary skill route " + heading)
    try:
        report = " ".join(named_contract_section(files.get("done-report", ""), "Report").split())
        for phrase in ("Implementation + tests | coding", "Infrastructure + IaC tests | infrastructure",
                       "Analysis + evidence | data-scientist", "Review | review-lead",
                       "Evidence is a test name or a review finding", "collect-usage.py"):
            if phrase not in report:
                errors.append("report missing " + phrase)
        if re.search(r"\|\s*(?:Testing|testing)\s*\|", report):
            errors.append("retired testing agent in report")
        named_contract_section(files.get("intake-plan", ""), "Tracker mechanics")
    except ValueError as error:
        errors.append(str(error))
    return errors


class StageRecipeTests(unittest.TestCase):
    def setUp(self):
        self.files = {**load_handoff_files(), **load_stage_files()}

    def test_stage_routes_controls_and_recipes_match_independent_oracle(self):
        self.assertEqual(stage_contract_errors(self.files), [])
        self.assertEqual(handoff_contract_errors(self.files), [])

    def test_missing_recipe_file_fails_closed(self):
        for name in {name for name, _ in STAGE_RECIPES.values()}:
            with self.subTest(name=name):
                changed = dict(self.files)
                del changed[name]
                self.assertIn("missing recipe file " + name, stage_contract_errors(changed))

    def test_missing_wrong_or_duplicate_required_pointer_is_rejected(self):
        for stage, (name, heading) in STAGE_RECIPES.items():
            old = "**Required read:** `references/%s.md` → **%s**" % (name, heading)
            for replacement in ("", old + "\n" + old, old.replace(name, "missing"),
                                old.replace("**" + heading + "**", "**Wrong stage**")):
                with self.subTest(stage=stage, replacement=replacement):
                    changed = dict(self.files)
                    self.assertIn(old, changed["dev-lead"])
                    changed["dev-lead"] = changed["dev-lead"].replace(old, replacement, 1)
                    self.assertIn("wrong or missing required read at Stage " + str(stage),
                                  stage_contract_errors(changed))

    def test_valid_section_for_wrong_stage_is_rejected(self):
        changed = dict(self.files)
        changed["dev-lead"] = changed["dev-lead"].replace(
            "`references/intake-plan.md` → **Stage 0**",
            "`references/intake-plan.md` → **Stage 1**")
        self.assertIn("wrong or missing required read at Stage 0", stage_contract_errors(changed))

    def test_missing_duplicate_or_renamed_section_fails(self):
        for stage, (name, heading) in STAGE_RECIPES.items():
            for replacement in ("## Renamed", "## " + heading + "\n\n## " + heading):
                with self.subTest(stage=stage, replacement=replacement):
                    changed = dict(self.files)
                    changed[name] = changed[name].replace("## " + heading + "\n", replacement + "\n", 1)
                    self.assertIn("missing or duplicate section " + heading,
                                  stage_contract_errors(changed))

    def test_skill_link_must_resolve_to_the_expected_file_and_section(self):
        for stage, (name, heading) in STAGE_RECIPES.items():
            link = "](references/%s.md#%s)" % (name, heading.lower().replace(" ", "-"))
            for replacement in ("", link.replace(name, "missing"), link.replace("#", "#wrong-")):
                with self.subTest(stage=stage, replacement=replacement):
                    changed = dict(self.files)
                    changed["dev-lead-templates"] = changed["dev-lead-templates"].replace(link, replacement)
                    self.assertIn("missing or duplicate skill route at Stage " + str(stage),
                                  stage_contract_errors(changed))

    def test_each_resident_control_cannot_be_hidden_in_a_recipe(self):
        for stage, clauses in STAGE_CONTROLS.items():
            for clause in clauses:
                with self.subTest(stage=stage, clause=clause):
                    changed = dict(self.files)
                    section = lead_stage_section(changed["dev-lead"], stage)
                    pattern = re.escape(clause).replace(r"\ ", r"\s+")
                    self.assertRegex(section, pattern)
                    changed["dev-lead"] = changed["dev-lead"].replace(
                        section, re.sub(pattern, "removed control", section))
                    name, _ = STAGE_RECIPES[stage]
                    changed[name] += "\n" + clause
                    self.assertIn("Stage %s resident control missing %s" % (stage, clause),
                                  stage_contract_errors(changed))

    def test_each_recipe_obligation_must_stay_in_its_required_section(self):
        for stage, clauses in RECIPE_CONTENT.items():
            name, heading = STAGE_RECIPES[stage]
            for clause in clauses:
                with self.subTest(stage=stage, clause=clause):
                    changed = dict(self.files)
                    section = named_contract_section(changed[name], heading)
                    pattern = re.escape(clause).replace(r"\ ", r"\s+")
                    self.assertRegex(section, pattern)
                    changed[name] = changed[name].replace(
                        section, re.sub(pattern, "removed recipe", section))
                    changed[name] += "\n## Unloaded section\n" + clause
                    self.assertIn("Stage %s recipe missing %s" % (stage, clause),
                                  stage_contract_errors(changed))

    def test_every_stop_stays_in_resident_autonomy_contract(self):
        autonomy = self.files["dev-lead"].split("### Autonomy contract")[1].split("### Stage 0")[0]
        for line in re.findall(r"^  \d+\. .+$", autonomy, re.M):
            with self.subTest(stop=line[:100]):
                changed = dict(self.files)
                changed["dev-lead"] = changed["dev-lead"].replace(line, "")
                changed["completion"] += "\n" + line
                self.assertIn("resident stop conditions drift", stage_contract_errors(changed))

    def test_rendering_templates_cannot_take_over_transitions_or_budgets(self):
        for name in ("plan-approval", "design-approval"):
            changed = dict(self.files)
            changed[name] += "\n- **Approve** → proceed to Stage 6"
            with self.subTest(name=name):
                self.assertIn(name + " owns transitions", stage_contract_errors(changed))
        for name in ("intake-plan", "implementation-review", "completion"):
            changed = dict(self.files)
            changed[name] += "\nCap: one Adjust round per run"
            with self.subTest(name=name):
                self.assertIn(name + " owns retry budget", stage_contract_errors(changed))

    def test_loading_guards_cannot_be_removed(self):
        for source, clause in (
            ("dev-lead", "at each stage entry or resume"),
            ("dev-lead", "relative to the loaded skill's home"),
            ("dev-lead", "stop and surface it"),
            ("dev-lead-templates", "exact named level-two section"),
            ("dev-lead-templates", "do not preload all sections"),
        ):
            with self.subTest(source=source, clause=clause):
                changed = dict(self.files)
                pattern = re.escape(clause).replace(r"\ ", r"\s+")
                self.assertRegex(changed[source], pattern)
                changed[source] = re.sub(pattern, "removed", changed[source])
                self.assertTrue(stage_contract_errors(changed))

    def test_duplicate_shared_schema_in_recipe_is_rejected(self):
        for author, (sentinel, _) in HANDOFF_FIELDS.items():
            with self.subTest(author=author):
                changed = dict(self.files)
                changed["completion"] += "\n" + schema_block(
                    named_contract_section(changed["handoff-contracts"], sentinel), sentinel)
                self.assertIn(sentinel + " duplicate or missing definition",
                              handoff_contract_errors(changed))

    def test_obsolete_separate_testing_author_is_rejected(self):
        changed = dict(self.files)
        changed["done-report"] += "\n| Testing | testing | done |\n"
        self.assertIn("retired testing agent in report", stage_contract_errors(changed))

    def test_report_and_tracker_reads_are_explicit_in_their_callers(self):
        for name, heading, owner in (
            ("intake-plan", "Tracker mechanics", "## Tracker status"),
            ("done-report", "Report", "### Stage 9"),
            ("completion", "Stage 9", "## Output format"),
            ("done-report", "Report", "## Output format"),
        ):
            with self.subTest(owner=owner, heading=heading):
                changed = dict(self.files)
                before, region = changed["dev-lead"].split(owner, 1)
                pointer = "`references/%s.md` → **%s**" % (name, heading)
                self.assertIn(pointer, region)
                changed["dev-lead"] = before + owner + region.replace(pointer, "missing", 1)
                self.assertIn(owner + " missing auxiliary read " + heading,
                              stage_contract_errors(changed))

    def test_report_and_tracker_skill_links_cannot_be_broken(self):
        for name, heading in (("done-report", "Report"), ("intake-plan", "Tracker mechanics")):
            with self.subTest(heading=heading):
                changed = dict(self.files)
                link = "](references/%s.md#%s)" % (name, heading.lower().replace(" ", "-"))
                self.assertIn(link, changed["dev-lead-templates"])
                changed["dev-lead-templates"] = changed["dev-lead-templates"].replace(link, "")
                self.assertIn("missing auxiliary skill route " + heading, stage_contract_errors(changed))

    def test_prose_reflow_preserves_stage_contracts(self):
        changed = dict(self.files)
        for name in (*TEMPLATE_PATHS, "dev-lead"):
            # Preserve headings, pointers, tables, code and link destinations;
            # wrap ordinary prose without changing the contract's words.
            fenced = False
            lines = []
            for line in changed[name].splitlines():
                if line.startswith("```"):
                    fenced = not fenced
                if (not fenced and line and not line.startswith(("#", "|", "```"))
                        and "](references/" not in line and "**Required read:**" not in line):
                    line = line.replace(" ", " \n\t ")
                lines.append(line)
            changed[name] = "\n".join(lines)
        self.assertEqual(stage_contract_errors(changed), [])

    def test_installed_skill_home_not_consumer_controls_resolution(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp) / "installed/core"
            consumer = Path(temp) / "consumer"
            decoy = consumer / "references/intake-plan.md"
            decoy.parent.mkdir(parents=True)
            decoy.write_text("## Stage 0\nWrong recipe", encoding="utf-8")
            for name, path in TEMPLATE_PATHS.items():
                target = installed / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(self.files[name], encoding="utf-8")
            loaded = {**self.files, **load_stage_files(installed)}
            self.assertEqual(stage_contract_errors(loaded, installed), [])
            self.assertIn("requirement_acs", resolve_stage_recipe(loaded, 0, installed))
            self.assertNotIn("Wrong recipe", resolve_stage_recipe(loaded, 0, installed))

    def test_whole_resident_file_is_smaller_than_pre_extraction(self):
        # Whole UTF-8 source, not tokens, selected sections or a savings claim
        # about required references. 85,942 is task 1's measured working tree.
        self.assertLess(len((CORE / HANDOFF_PATHS["dev-lead"]).read_bytes()), 85942)


def contract_errors(files):
    """Bounded textual invariants, not a general Markdown or agent parser."""
    errors = handoff_contract_errors(files)
    lead = files["dev-lead"]
    schemas = {}
    for author, (sentinel, _) in HANDOFF_FIELDS.items():
        try:
            schemas[author] = resolve_handoff_section(files, author, sentinel)
        except ValueError:
            schemas[author] = ""
    for field in ("Behavior added/modified", "Existing tests modified"):
        if "- %s:" % field not in schemas["infrastructure"]:
            errors.append("infrastructure missing " + field)
    if "Unreviewed dimensions" in lead or "Not verifiable from this diff" not in lead:
        errors.append("analysis consumer field drift")
    if "- Not verifiable from this diff:" not in schemas["data-scientist"]:
        errors.append("analysis producer field drift")
    if "- Code verification:" not in schemas["data-scientist"] or "`Code verification`" not in lead:
        errors.append("analysis code evidence drift")
    for author in ("coding", "infrastructure", "architect", "data-scientist"):
        if "- Findings addressed:" not in schemas[author]:
            errors.append(author + " missing corrective accounting")
        if "exactly once" in files[author] or "one round —" in files[author]:
            errors.append(author + " stale retry count")
    # Answer handling now belongs to the resident supervisor, not its renderer.
    approve = " ".join(lead_stage_section(lead, 4).split()).split("- **Adjust**")[0]
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
        self.files = load_handoff_files()
        self.files.update(load_stage_files())
        self.files["cost-budget"] = (CORE / "skills/cost-budget/SKILL.md").read_text(encoding="utf-8")

    def test_contracts_match(self):
        self.assertEqual(contract_errors(self.files), [])

    def test_known_contradictions_are_detected(self):
        mutations = [
            ("handoff-contracts", "- Existing tests modified:", "- Removed test field:"),
            ("handoff-contracts", "- Behavior added/modified:", "- Removed behavior field:"),
            ("dev-lead", "Not verifiable from this diff", "Unreviewed dimensions"),
            ("handoff-contracts", "- Code verification:", "- Removed code field:"),
            ("handoff-contracts", "- Findings addressed:", "- Removed corrective field:"),
            ("coding", "`dev-lead` owns the", "one round — `dev-lead` owns the"),
            ("dev-lead", "Stage 5 conditional", "Stage 6 unconditional"),
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
