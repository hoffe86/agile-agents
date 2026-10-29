"""Offline instruction contracts, not evidence of native model dispatch behavior."""

from pathlib import Path
import re
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "plugins/agile-agents-core"
REFERENCE = CORE / "skills/cost-budget/references/tier-defaults.md"
ENTRY_POINTS = (
    CORE / "agents/bootstrapper.agent.md",
    CORE / "skills/solution-profile-interview/SKILL.md",
    CORE / "skills/cost-budget/SKILL.md",
)
PROFILES = (
    ROOT / ".github/solution-profile.yaml",
    CORE / "skills/solution-profile-interview/references/solution-profile.template.yaml",
)


def normalized(text):
    return " ".join(text.lower().replace("`", "").replace("*", "").split())


def setup_errors(text):
    """Independent guard categories; tolerate layout, not removal of safeguards."""
    text = normalized(text.split("## Historical recommendations")[0])
    guards = {
        "proposal only": r"proposal-only.{0,100}not a runtime tier resolver",
        "map and approval intersection": r"propose only choices from the matching "
                                        r"profile tier.{0,40}in the approved list",
        "preserve overrides": r"preserve explicit user choices and per-agent overrides",
        "missing map": r"missing or empty map.{0,60}leave settings untouched",
        "missing tier": r"no entry for that tier.{0,40}leave settings untouched",
        "no forced inheritance": r"not force inheritance or clear overrides",
        "manual approval": r"user explicitly approves.{0,50}configures it manually"
                           r".{0,40}/subagents",
        "no settings writes": r"must never write user/global configuration",
        "separate approval": r"plugin-install approval is not model-setup approval",
        "no task override": r"never set a task's model from the profile",
        "unavailable choice": r"unavailable.{0,60}report it and let the user choose",
        "no substitution": r"do not silently substitute.{0,55}approved list",
        "no availability assumption": r"do not assume availability",
        "honest outcome": r"user confirmation is not execution evidence",
        "not ordered fallback": r"not a native ordered-fallback guarantee",
        "fallback outside approval": r"preferred fallback may leave ai_copilot.approved_models",
        "static only": r"ci checks only static.{0,80}not runtime",
        "unmet governance": r"report that unmet governance requirement",
        "version uncertainty": r"required-policy and auto.{0,40}unverified on cli 1\.0\.98",
        "preserve policy": r"do not change a user's existing policy or auto choice",
    }
    return [name for name, pattern in guards.items() if not re.search(pattern, text)]


def false_selection_claims(text):
    """Catch contradictory positive claims even when the guards are still present."""
    patterns = (
        r"automatically (?:resolve|map) (?:the )?(?:model )?tiers",
        r"set (?:the )?task(?:'s)? model (?:to|=) .{0,40}model_tiers",
        r"(?:missing|no|empty) (?:tier )?map (?:forces|resets).{0,25}inherit",
        r"silently substitute (?:the next|an approved) model",
        r"preferred fallback (?:always )?stays (?:in|within) the approved list",
        r"(?:ci|the profile|preferred setup) enforces runtime (?:model )?(?:governance|authorization)",
        r"profile (?:list )?order guarantees native (?:ordered[- ])?fallback",
        r"(?:required-policy|auto) .{0,25}\b(?:verified|guaranteed) on cli 1\.0\.98",
    )
    text = normalized(text)
    return [pattern for pattern in patterns if re.search(pattern, text)]


def native_pins(frontmatter):
    return {"model", "models", "modelPolicy", "model-policy"} & frontmatter.keys()


class ModelSetupInstructionTests(unittest.TestCase):
    def test_manual_setup_carries_every_safety_guard(self):
        self.assertEqual(setup_errors(REFERENCE.read_text(encoding="utf-8")), [])

    def test_removing_each_guard_is_detected(self):
        text = REFERENCE.read_text(encoding="utf-8")
        mutations = (
            ("proposal-only", "automatic", "proposal only"),
            ("matching profile tier", "historical table", "map and approval intersection"),
            ("Preserve explicit", "Replace explicit", "preserve overrides"),
            ("leave settings untouched", "reset settings", "missing map"),
            ("no entry for that tier", "tier entry present", "missing tier"),
            ("not force inheritance", "force inheritance", "no forced inheritance"),
            ("user explicitly approves", "agent automatically approves", "manual approval"),
            ("must never write", "may write", "no settings writes"),
            ("is not model-setup approval", "is model-setup approval", "separate approval"),
            ("Never set a task's", "Set a task's", "no task override"),
            ("report it and let the user", "hide it and let the agent", "unavailable choice"),
            ("do not silently substitute", "silently substitute", "no substitution"),
            ("Do not assume availability", "Assume availability", "no availability assumption"),
            ("is not execution", "is execution", "honest outcome"),
            ("not a native ordered-fallback", "a native ordered-fallback", "not ordered fallback"),
            ("preferred fallback may leave", "preferred fallback stays in", "fallback outside approval"),
            ("CI checks only static", "CI enforces runtime", "static only"),
            ("report that unmet", "hide that unmet", "unmet governance"),
            ("unverified on CLI", "verified on CLI", "version uncertainty"),
            ("Do not change a user's", "Change a user's", "preserve policy"),
        )
        for old, new, guard in mutations:
            with self.subTest(guard=guard):
                self.assertIn(old, text)
                self.assertIn(guard, setup_errors(text.replace(old, new)))

    def test_guards_tolerate_whitespace_and_emphasis(self):
        text = REFERENCE.read_text(encoding="utf-8").replace("**", "")
        self.assertEqual(setup_errors(re.sub(r" +", "   ", text)), [])

    def test_all_runtime_entry_points_require_the_bounded_reference(self):
        for path in ENTRY_POINTS:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertRegex(normalized(text), r"first read.{0,110}manual native setup")
                self.assertIn("preference is not governance", normalized(text))
                links = re.findall(r"\]\(([^)]+tier-defaults\.md)(?:#[^)]*)?\)", text)
                self.assertTrue(links)
                self.assertEqual({(path.parent / link).resolve() for link in links},
                                 {REFERENCE.resolve()})
                self.assertIn("/subagents", text)

    def test_bootstrap_reports_setup_without_claiming_runtime_verification(self):
        text = normalized(ENTRY_POINTS[0].read_text(encoding="utf-8"))
        self.assertIn("proposed/configured/skipped/unavailable", text)
        self.assertIn("not runtime verification", text)
        self.assertIn("bootstrap complete", text)

    def test_live_guidance_has_no_contradictory_selection_claims(self):
        paths = set((ROOT / "plugins").rglob("*.md"))
        paths.update((*PROFILES, ROOT / "README.md", ROOT / ".github/copilot-instructions.md"))
        for path in sorted(paths):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertEqual(false_selection_claims(path.read_text(encoding="utf-8")), [])

    def test_injected_automatic_selection_and_governance_claims_are_rejected(self):
        claims = (
            "Automatically resolve the model tiers.",
            "Set the task model to cost_envelope.model_tiers.heavy.",
            "Missing map forces inheritance.",
            "Silently substitute the next model.",
            "Preferred fallback always stays within the approved list.",
            "CI enforces runtime model governance.",
            "Profile list order guarantees native ordered fallback.",
            "Required-policy is verified on CLI 1.0.98.",
            "Auto is guaranteed on CLI 1.0.98.",
        )
        text = REFERENCE.read_text(encoding="utf-8")
        for claim in claims:
            with self.subTest(claim=claim):
                self.assertTrue(false_selection_claims(text + "\n" + claim))

    def test_setup_has_no_native_config_snippet_or_live_probe(self):
        text = REFERENCE.read_text(encoding="utf-8").split("## Historical recommendations")[0]
        self.assertNotIn("```", text)
        self.assertIn("Use the native UI, not a copied settings snippet", text)
        self.assertIn("or test it with a live model call", text)
        self.assertIn("cli-command-reference#custom-agent-frontmatter-fields", text)
        self.assertIn("cli-config-dir-reference#configuration-file-settings", text)
        self.assertIn("changelog.md#1083", text)


class ModelSetupStructuralTests(unittest.TestCase):
    def test_shipped_agents_have_advisory_tiers_but_no_native_model_pins(self):
        agents = list((ROOT / "plugins").rglob("*.agent.md"))
        self.assertEqual(len(agents), 15)
        for path in agents:
            with self.subTest(agent=path.stem):
                data = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
                self.assertIn(data["metadata"]["model_tier"], {"heavy", "mid", "light"})
                self.assertEqual(native_pins(data), set())

    def test_native_pin_injection_is_detected_independently_of_tier(self):
        for key in ("model", "models", "modelPolicy", "model-policy"):
            with self.subTest(key=key):
                data = {"metadata": {"model_tier": "heavy"}, key: "example"}
                self.assertEqual(native_pins(data), {key})

    def test_root_choices_are_unchanged_and_template_is_generic(self):
        profile, template = (yaml.safe_load(path.read_text(encoding="utf-8"))
                             for path in PROFILES)
        tiers = {
            "heavy": ["gpt-6-astra", "claude-opus-5.5"],
            "mid": ["gpt-6.1-sol", "claude-sonnet-5.5"],
            "light": ["gpt-6-luna", "claude-haiku-5.5", "mai-code-1.1-flash"],
        }
        self.assertEqual(profile["cost_envelope"]["model_tiers"], tiers)
        self.assertEqual(profile["ai_copilot"]["approved_models"],
                         [model for models in tiers.values() for model in models])
        self.assertEqual(template["cost_envelope"]["model_tiers"], {})
        self.assertEqual(template["ai_copilot"]["approved_models"], [])

    def test_no_executable_tier_resolver_is_added(self):
        # The existing static checker is intentionally the sole executable consumer.
        # This is a source guard, not a claim to detect arbitrary obfuscated code.
        checker = ROOT / "scripts/check-skill-frontmatter.py"
        for folder in (ROOT / "plugins", ROOT / "scripts"):
            for path in folder.rglob("*"):
                if path.suffix not in {".py", ".ps1", ".sh"} or "tests" in path.parts:
                    continue
                if path == checker:
                    continue
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertNotRegex(path.read_text(encoding="utf-8"),
                                        r"\bmodel_tiers\b|\bmetadata[.\[]['\"]?model_tier\b")


if __name__ == "__main__":
    unittest.main()
