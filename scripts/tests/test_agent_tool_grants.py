"""Runtime tool grants needed by the harness's documented agent contracts."""

from pathlib import Path
import unittest

import yaml


AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "agile-agents-core" / "agents"


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


class AgentToolGrantTests(unittest.TestCase):
    def test_every_agent_can_load_its_required_skills(self):
        agents = sorted(AGENTS.glob("*.agent.md"))
        self.assertTrue(agents)
        for path in agents:
            with self.subTest(agent=path.name):
                self.assertIn("skill", frontmatter(path)["tools"])

    def test_dev_lead_can_ask_for_the_mandatory_plan_approval(self):
        self.assertIn("ask_user", frontmatter(AGENTS / "dev-lead.agent.md")["tools"])


if __name__ == "__main__":
    unittest.main()
