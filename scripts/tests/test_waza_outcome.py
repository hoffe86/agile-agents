"""Owned Waza outcome-suite configuration and benchmark expectations."""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "eval/skills/outcome/plan"
GOOD_PLAN = """\
T1 | data-scientist | feasibility | depends: none
T2 | coding | implementation | depends: T1
AC1 | T1
AC2 | T2
approval | required before implementation
T1 acceptance | Determine whether the dataset exists and its use is permitted, including no.
T2 acceptance | Deliver the feature with tests.
"""


class OutcomeSuiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = yaml.safe_load((SUITE / "eval.yaml").read_text(encoding="utf-8"))
        cls.task = yaml.safe_load(
            (SUITE / "tasks/feasibility.yaml").read_text(encoding="utf-8"))
        cls.patterns = cls.spec["graders"][0]["config"]["content_patterns"][0]["must_match"]

    def test_suite_targets_current_skill_and_grades_output_not_selection(self):
        config = self.spec["config"]
        self.assertEqual(self.spec["skill"], "plan")
        self.assertTrue(config["inject_skill_body"])
        self.assertEqual(config["required_skills"], ["plan"])
        self.assertEqual(
            (SUITE / config["skill_directories"][0] / "SKILL.md").resolve(),
            ROOT / "plugins/agile-agents-core/skills/plan/SKILL.md")
        self.assertEqual(config["executor"], "copilot-sdk")
        profile = yaml.safe_load((ROOT / ".github/solution-profile.yaml").read_text())
        self.assertIn(config["model"], profile["ai_copilot"]["approved_models"])
        self.assertEqual(self.spec["tasks"], ["tasks/*.yaml"])
        self.assertTrue(self.task["inputs"]["prompt"])
        self.assertIn("data_science.enabled is true", self.task["inputs"]["prompt"])
        self.assertIn("data-scientist agent is available and active", self.task["inputs"]["prompt"])
        self.assertEqual([grader["type"] for grader in self.spec["graders"]], ["file"])
        self.assertEqual(self.spec["graders"][0]["config"]["must_exist"], ["plan.md"])
        self.assertEqual(
            yaml.safe_load((ROOT / ".waza.yaml").read_text())["paths"]["evals"],
            "eval/skills/outcome")

    def test_complete_plan_matches_all_owned_outcome_requirements(self):
        for pattern in self.patterns:
            with self.subTest(pattern=pattern):
                self.assertRegex(GOOD_PLAN, pattern)

    def test_missing_feasibility_dependency_and_approval_fail(self):
        for old, new in (
            ("T1 | data-scientist", "T1 | coding"),
            ("depends: T1", "depends: none"),
            ("AC1 | T1", "AC1 | T2"),
            ("approval | required before implementation", "approval | not required"),
            ("dataset exists and its use is permitted", "analysis completed"),
            ("feature with tests", "feature"),
        ):
            with self.subTest(old=old):
                bad_plan = GOOD_PLAN.replace(old, new)
                self.assertTrue(any(re.search(pattern, bad_plan) is None
                                    for pattern in self.patterns))

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell required")
    def test_coverage_invocation_includes_current_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "scripts/check-skill-tokens.ps1"
            script.parent.mkdir()
            shutil.copyfile(ROOT / "scripts/check-skill-tokens.ps1", script)
            (root / "plugins/core/skills").mkdir(parents=True)
            fake = root / "waza.ps1"
            token_result = {"results": [
                {"file": "plugins/core/skills/demo/SKILL.md", "exceeded": False}]}
            coverage = {"covered": 0, "partial": 1, "total_skills": 25}
            fake.write_text(
                "if ($args[0] -eq 'tokens') {\n"
                f"    '{json.dumps(token_result)}'\n"
                "} else {\n"
                "    $expected = @('coverage', '--no-update-check', '-f', 'json', "
                "'--path', 'plugins/core/skills', '--path', 'eval/skills/outcome')\n"
                "    if (($args -join '|') -cne ($expected -join '|')) "
                "{ throw 'Unexpected coverage arguments' }\n"
                f"    '{json.dumps(coverage)}'\n"
                "}\n", encoding="utf-8")
            completed = subprocess.run(
                ["pwsh", "-NoProfile", "-File", str(script), "-WazaPath", str(fake)],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertIn("Eval coverage: 1/25 skills", completed.stdout)
            self.assertIn("suite inventory only, not a quality score", completed.stdout)


if __name__ == "__main__":
    unittest.main()
