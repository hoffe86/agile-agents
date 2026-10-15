"""Offline regressions for informational minutes and bounded deployment waits."""

import ast
import importlib.util
from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "plugins" / "agile-agents-core" / "skills"
PROFILES = (
    ROOT / ".github" / "solution-profile.yaml",
    SKILLS / "solution-profile-interview/references/solution-profile.template.yaml",
)
COST = SKILLS / "cost-budget/SKILL.md"
DEPLOY = SKILLS / "deploy-verify/SKILL.md"
STOP_REPORT = SKILLS / "cost-budget/references/cost-stop-report.md"
ADR = ROOT / "docs/adr/0004-cost-envelope-thresholds-and-stop-on-breach.md"
COLLECTOR = SKILLS / "cost-budget/scripts/collect-usage.py"
GATE_FLAGS = {"--max-tokens", "--max-aiu", "--max-usd", "--usd-per-aiu",
              "--since", "--event-log", "--phase", "--max-phase-aiu"}


def normalized(text):
    return " ".join(text.lower().replace("`", "").replace("*", "").split())


def deadline_claims(text):
    """Catch known false enforcement claims, independently of positive guidance."""
    text = normalized(text)
    patterns = (
        r"wall[- ]clock cap\b",
        r"three orthogonal hard caps",
        r"all three together catch",
        r"bounded by (?:cost_envelope\.)?max_minutes_per_run",
        r"honou?r\w* the remaining max_minutes_per_run",
        r"max_minutes_per_run.{0,80}\b(?:is|are|now actually) enforceable",
        r"max_minutes_per_run.{0,80}\b(?:is|as) (?:an? )?(?:enforced|hard) deadline",
        r"enforce (?:the )?(?:cost_envelope\.)?max_minutes_per_run",
    )
    return [pattern for pattern in patterns if re.search(pattern, text)]


def planning_guidance(text):
    return bool(re.search(
        r"max_minutes_per_run.{0,140}\binformational\b|"
        r"\binformational\b.{0,100}max_minutes_per_run", normalized(text)))


def polling_errors(text):
    procedure = re.search(r"(?ms)^##\s+Procedure\s+(.*?)(?=^##\s)", text)
    match = re.search(r"(?ms)^4\.\s+(.*?)(?=^5\.\s)",
                      procedure[1] if procedure else "")
    if not match:
        return ["missing polling step"]
    step = normalized(match[1])
    requirements = {
        "established timeout": r"(?:operation|polling) timeout.{0,30}before polling",
        "explicit source": r"(?:project|pipeline).{0,40}(?:user|operator)",
        "fixed deadline": r"source.{0,30}duration.{0,30}fixed deadline"
                          r".{0,40}(?:first poll|polling)",
        "queued time": r"include.{0,20}queued time",
        "bounded requests": r"bound.{0,20}status request.{0,20}sleep.{0,30}time left",
        "no reset": r"(?:do not|never) reset.{0,20}deadline",
        "missing bound stops": r"if no bound is established,.+timeout_not_configured"
                              r".+stop verification without polling",
        "expiry stops": r"on expiry:.+reason=timeout.+stop polling",
        "no cancellation": r"do not cancel the pipeline",
    }
    return [name for name, pattern in requirements.items()
            if not re.search(pattern, step)]


class CostTimeInstructionTests(unittest.TestCase):
    def test_live_surfaces_do_not_claim_a_global_deadline(self):
        paths = set((ROOT / "plugins").rglob("*.md"))
        paths.update((*PROFILES, ADR, ROOT / "README.md",
                      ROOT / ".github/copilot-instructions.md"))
        for path in sorted(paths):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(deadline_claims(path.read_text(encoding="utf-8")), [])

    def test_minutes_are_explicitly_informational_on_each_affected_surface(self):
        for path in (*PROFILES, COST, DEPLOY, STOP_REPORT, ADR):
            text = path.read_text(encoding="utf-8")
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertTrue(planning_guidance(text))
                self.assertFalse(planning_guidance(re.sub(
                    r"\binformational\b", "mandatory", text, flags=re.I)))

    def test_reintroduced_hard_deadline_claims_are_rejected(self):
        claims = (
            "max_minutes_per_run: 60 # Wall-clock cap.",
            "Three orthogonal hard caps are enforced per run.",
            "All three together catch the realistic failure modes.",
            "Poll, bounded by `cost_envelope.max_minutes_per_run`.",
            "Honouring the remaining `max_minutes_per_run` when polling.",
            "`max_tokens_per_run` and `max_minutes_per_run` are unchanged "
            "and now actually enforceable.",
            "Use max_minutes_per_run as a hard deadline.",
            "Enforce cost_envelope.max_minutes_per_run.",
        )
        baseline = COST.read_text(encoding="utf-8")
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertTrue(deadline_claims(baseline + "\n" + claim))

    def test_elapsed_time_is_distinguished_from_call_duration(self):
        for path in (COST, STOP_REPORT, ADR):
            with self.subTest(path=path.relative_to(ROOT)):
                text = normalized(path.read_text(encoding="utf-8"))
                self.assertRegex(text, r"duration_ms.{0,40}\bis not elapsed")
                self.assertRegex(text, r"overlap")
                self.assertRegex(text, r"idle time")

    def test_deployment_polling_requires_an_explicit_finite_bound(self):
        self.assertEqual(polling_errors(DEPLOY.read_text(encoding="utf-8")), [])

    def test_removing_any_polling_guard_is_detected(self):
        text = DEPLOY.read_text(encoding="utf-8")
        mutations = (
            ("operation timeout before polling", "timeout later", "established timeout"),
            ("project/pipeline or supplied by", "runtime or guessed by", "explicit source"),
            ("fixed deadline", "sliding deadline", "fixed deadline"),
            ("Include queued", "Exclude queued", "queued time"),
            ("bound each status request", "make each status request", "bounded requests"),
            ("Do not reset", "Reset", "no reset"),
            ("stop\n   verification without polling", "keep polling", "missing bound stops"),
            ("stop polling and report", "keep polling and report", "expiry stops"),
            ("Do not cancel", "Cancel", "no cancellation"),
        )
        for old, new, expected in mutations:
            with self.subTest(guard=expected):
                self.assertIn(old, text)
                self.assertIn(expected, polling_errors(text.replace(old, new)))

    def test_polling_checks_tolerate_whitespace_and_markdown_emphasis(self):
        text = DEPLOY.read_text(encoding="utf-8").replace("**", "")
        text = re.sub(r"(?<=\S) +", "   ", text)
        self.assertEqual(polling_errors(text), [])
        self.assertEqual(deadline_claims(text), [])

    def test_documented_cost_command_retains_actual_gate_flags(self):
        text = COST.read_text(encoding="utf-8")
        command = re.search(r"```[ \n]+(python scripts/collect-usage.py.*?)```",
                            text, re.S).group(1)
        flags = set(re.findall(r"--[\w-]+", command))
        self.assertTrue(GATE_FLAGS <= flags)
        self.assertFalse(any("minute" in flag or "duration" in flag for flag in flags))
        for flag in GATE_FLAGS:
            with self.subTest(flag=flag):
                mutated = set(re.findall(r"--[\w-]+", command.replace(flag, "--removed")))
                self.assertFalse(GATE_FLAGS <= mutated)


class CostTimeRuntimeTests(unittest.TestCase):
    def test_native_profile_values_and_enforced_caps_are_retained(self):
        expected = {
            "enabled": True, "tier": "medium", "max_usd_per_run": 25.00,
            "max_aiu_per_run": 30000, "max_aiu_per_phase": 8000,
            "max_aiu_per_phase_overrides": {}, "usd_per_aiu": None,
            "max_tokens_per_run": 2000000, "max_minutes_per_run": 60,
            "stop_on_breach": True,
        }
        for path in PROFILES:
            with self.subTest(path=path.relative_to(ROOT)):
                envelope = yaml.safe_load(path.read_text(encoding="utf-8"))["cost_envelope"]
                self.assertEqual({key: envelope[key] for key in expected}, expected)
                self.assertIs(type(envelope["max_minutes_per_run"]), int)

    def test_actual_collector_cli_has_cost_flags_but_no_time_gate(self):
        tree = ast.parse(COLLECTOR.read_text(encoding="utf-8"))
        flags = {arg.value for call in ast.walk(tree)
                 if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                 and call.func.attr == "add_argument"
                 for arg in call.args if isinstance(arg, ast.Constant)
                 and isinstance(arg.value, str) and arg.value.startswith("--")}
        self.assertTrue(GATE_FLAGS <= flags)
        self.assertFalse(any(re.search(r"minute|duration|timeout|deadline", flag)
                             for flag in flags))

    def test_call_duration_sums_even_when_calls_overlap(self):
        spec = importlib.util.spec_from_file_location("cost_time_usage", COLLECTOR)
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        bucket = collector.blank()
        row = {"input_tokens": 1, "output_tokens": 1, "reasoning_tokens": 0,
               "cache_read_tokens": 0, "total_nano_aiu": 1, "duration_ms": 60000,
               "created_at": "2026-10-15T12:00:00Z", "model": "fixture"}
        # Two simultaneous one-minute calls accumulate two minutes, not elapsed time.
        collector.add(bucket, row)
        collector.add(bucket, row)
        self.assertEqual(bucket["calls"], 2)
        self.assertEqual(bucket["duration_ms"], 120000)


if __name__ == "__main__":
    unittest.main()
