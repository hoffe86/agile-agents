"""Runtime tool grants needed by the harness's documented agent contracts."""

from pathlib import Path
import unittest

import yaml


AGENTS = Path(__file__).resolve().parents[2] / "plugins" / "agile-agents-core" / "agents"
REVIEW_ONLY = (
    "architecture-reviewer",
    "code-reviewer",
    "data-reviewer",
    "infrastructure-reviewer",
    "security-reviewer",
    "test-reviewer",
    "review-lead",
)
READ_ONLY_CONTRACT = (
    "Tool availability is not authorization.",
    "Read-only is effect-based:",
    "cause a write indirectly through any tool, command, script, browser action, "
    "skill workflow or delegation",
    "Refuse write requests even when explicitly authorized by the user",
)


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---", 2)[1])


class AgentToolGrantTests(unittest.TestCase):
    def test_every_shipped_agent_grants_all_tools(self):
        agents = sorted(AGENTS.glob("*.agent.md"))
        self.assertTrue(agents)
        for path in agents:
            with self.subTest(agent=path.name):
                data = frontmatter(path)
                self.assertEqual(data["tools"], ["*"])
                self.assertNotIn("tools", data["metadata"])
                self.assertNotIn("allowed-tools", data)

    def test_review_roles_remain_effect_based_read_only(self):
        skill = (AGENTS.parent / "skills" / "reviewer-read-only-rules" / "SKILL.md").read_text(
            encoding="utf-8")
        for marker in READ_ONLY_CONTRACT:
            with self.subTest(source="reviewer-read-only-rules", marker=marker):
                self.assertIn(marker, skill)

        for name in REVIEW_ONLY:
            prompt = (AGENTS / f"{name}.agent.md").read_text(encoding="utf-8")
            self.assertIn("reviewer-read-only-rules", prompt)
            for marker in READ_ONLY_CONTRACT:
                with self.subTest(agent=name, marker=marker):
                    self.assertIn(marker, prompt)
        self.assertIn(
            'agents: ["code-reviewer", "security-reviewer", "test-reviewer", '
            '"data-reviewer", "architecture-reviewer", "infrastructure-reviewer"]',
            (AGENTS / "review-lead.agent.md").read_text(encoding="utf-8"),
        )

    def test_capability_scout_remains_proposal_only_with_all_tools_granted(self):
        prompt = (AGENTS / "capability-scout.agent.md").read_text(encoding="utf-8")
        self.assertIn("tools: [\"*\"]", prompt)
        self.assertIn("Tool availability is not authorization.", prompt)
        self.assertIn("Read-only is effect-based:", prompt)
        self.assertIn("human approval is required before adoption or installation.", prompt)
        self.assertIn(
            "Never adopt, install,\nedit instructions or change settings yourself.", prompt)

    def test_wildcard_grant_does_not_imply_runtime_availability_or_authorization(self):
        skills = AGENTS.parent / "skills"
        context = " ".join(
            (skills / "read-repo-context" / "SKILL.md").read_text(encoding="utf-8").split())
        for marker in (
            "a tool may be absent from runtime",
            "`tools: [\"*\"]` covers the agent-level",
            "it does not register servers, authorize use, or bypass host permissions",
            "workspace/global restrictions",
            "a skill's `allowed-tools` grants nothing",
        ):
            with self.subTest(source="read-repo-context", marker=marker):
                self.assertIn(marker, context)

        backlog = " ".join((AGENTS / "backlog-manager.agent.md").read_text(encoding="utf-8").split())
        self.assertIn("`[\"*\"]` covers the agent-grant check", backlog)
        self.assertIn("host, workspace or global permissions", backlog)
        self.assertNotIn("a tracker server that is not listed here is unreachable", backlog)

        other_guidance = {
            AGENTS / "bootstrapper.agent.md": (
                '`tools: ["*"]` covers only the agent-grant check',
                "host/workspace/global permissions may still deny use",
                "A skill's allowed-tools field grants nothing",
            ),
            AGENTS / "capability-scout.agent.md": (
                '`tools: ["*"]` covers only tools available to the runtime',
                "Host, workspace or global permissions may still deny use",
            ),
            AGENTS / "infrastructure.agent.md": (
                "a wildcard grant does not establish server registration",
                "override host/workspace/global permissions",
            ),
            skills / "artifact-coverage" / "SKILL.md": (
                '`tools: ["*"]` covers only the grant check',
                "does not authorize use or bypass host/workspace/global restrictions",
            ),
            skills / "solution-profile-interview" / "references" / "discovery-signals.md": (
                '`tools: skill` or `tools: ["*"]`',
                "host/workspace/global restrictions may still deny use",
            ),
        }
        for path, markers in other_guidance.items():
            text = " ".join(path.read_text(encoding="utf-8").split())
            for marker in markers:
                with self.subTest(source=path.name, marker=marker):
                    self.assertIn(marker, text)


if __name__ == "__main__":
    unittest.main()
