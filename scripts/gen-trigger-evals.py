"""Generate the S0 routing (trigger-accuracy) eval corpus.

The prompts below are the asset; the YAML around them is mechanical, so it is
generated rather than hand-copied 18 times. Regenerate with:

    python scripts/gen-trigger-evals.py

Design notes
------------
* `executor: mock` — the `trigger` grader is a pure offline heuristic (keyword and
  USE-FOR phrase overlap against the skill's own description), so no model is called
  and these run in the free S0 tier alongside the token ratchet.
* Every skill gets **near-miss negatives**, not absurd ones. "Tell me a joke" proves
  nothing; a prompt that shares vocabulary with the skill but belongs to a different
  skill is what actually catches a description that over-reaches.
* Thresholds are deliberately uniform for now. They are **not calibrated**, which is
  why this suite reports a baseline and does not gate — see docs/adr/0014.
"""
from __future__ import annotations

import os
import textwrap

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVALS = os.path.join(REPO, "evals")

SKILL_PATHS = {
    "engineering-judgement": "plugins/agile-agents-core/skills/engineering-judgement/SKILL.md",
    "testing-practices": "plugins/agile-agents-core/skills/testing-practices/SKILL.md",
    "development-practices": "plugins/agile-agents-core/skills/development-practices/SKILL.md",
    "read-repo-context": "plugins/agile-agents-core/skills/read-repo-context/SKILL.md",
    "test-bar-gate": "plugins/agile-agents-core/skills/test-bar-gate/SKILL.md",
    "csharp-testing": "plugins/agile-agents-dotnet/skills/csharp-testing/SKILL.md",
}

# (skill, task-id, kind, prompt, why)
CASES = [
    # --- engineering-judgement: posture, not a technique -----------------------
    ("engineering-judgement", "positive-1", "positive",
     "The ticket doesn't say what should happen when the upload fails. Should I stop "
     "and ask, or make the sensible call and carry on?",
     "The skill's core case: under-specification, decide-vs-escalate."),
    ("engineering-judgement", "positive-2", "positive",
     "We need to change the persisted event schema. Is that something I can just "
     "decide, or does it need sign-off first?",
     "Reversibility x blast radius — the escalation test the skill defines."),
    ("engineering-judgement", "negative-1", "negative",
     "Write the xUnit test cases covering the null and empty-string branches of "
     "this parser.",
     "Near-miss: concrete test authoring belongs to testing-practices."),

    # --- testing-practices: the verification half ------------------------------
    ("testing-practices", "positive-1", "positive",
     "This test is failing after my change. Can I relax the assertion so the suite "
     "goes green again?",
     "The never-weaken-a-test boundary is this skill's load-bearing rule."),
    ("testing-practices", "positive-2", "positive",
     "How much of this new behaviour needs test coverage, and which edge cases "
     "actually matter?",
     "Coverage-of-the-change judgement."),
    ("testing-practices", "negative-1", "negative",
     "Provision the storage account and wire up its private endpoint in Bicep.",
     "Near-miss on 'coverage'/'check' vocabulary but squarely infrastructure."),

    # --- development-practices: the implementation half ------------------------
    ("development-practices", "positive-1", "positive",
     "I'm about to add a retry wrapper around this HTTP call. What's the smallest "
     "correct change here?",
     "Smallest-change bias plus cloud-native defaults."),
    ("development-practices", "positive-2", "positive",
     "Should this new service emit traces and structured logs before I call it done?",
     "Observability is part of done (§5)."),
    ("development-practices", "negative-1", "negative",
     "Review this diff and tell me whether the error handling is good enough.",
     "Near-miss: reviewing a diff is a reviewer's job, not the authoring bar."),

    # --- read-repo-context: the preamble ---------------------------------------
    ("read-repo-context", "positive-1", "positive",
     "Before you start, what conventions does this repository already declare that "
     "I have to follow?",
     "The preamble's whole purpose."),
    ("read-repo-context", "positive-2", "positive",
     "Which solution-profile fields should shape how I approach this task?",
     "Profile loading is step 2 of the skill."),
    ("read-repo-context", "negative-1", "negative",
     "Summarise what this 400-line function does.",
     "Near-miss on 'read' — code comprehension, not repo conventions."),

    # --- test-bar-gate: the deterministic gate ---------------------------------
    ("test-bar-gate", "positive-1", "positive",
     "Implementation is finished. Run lint, type-check and the unit tests, and "
     "confirm the app still starts before review.",
     "Exactly the gate's job, including the smoke slot."),
    ("test-bar-gate", "positive-2", "positive",
     "What has to pass before this change is allowed to reach the reviewers?",
     "The gate's placement between Implement and Review."),
    ("test-bar-gate", "negative-1", "negative",
     "Write a new integration test for the checkout flow.",
     "Near-miss: authoring tests is coding/testing-practices, not the gate."),

    # --- csharp-testing: a companion-plugin, language-scoped skill -------------
    ("csharp-testing", "positive-1", "positive",
     "Add xUnit tests for this C# service class and get the coverage up.",
     "Directly the skill's scope."),
    ("csharp-testing", "positive-2", "positive",
     "Our .NET solution uses NUnit. Extend the fixtures to cover the new handler.",
     "Framework detection within the same ecosystem."),
    ("csharp-testing", "negative-1", "negative",
     "Add pytest cases for this Python module and raise coverage.",
     "The sharpest near-miss in the repo: identical intent, wrong ecosystem. "
     "csharp-testing and python-testing score 0.53 description similarity."),
]

EVAL_TEMPLATE = """\
name: {skill}-trigger
description: >-
  Routing (trigger-accuracy) eval for the {skill} skill. Scores whether a prompt
  should activate it, using Waza's offline `trigger` grader — keyword and USE-FOR
  phrase overlap against the skill's own description. No model is called, so this
  runs in the free S0 tier.
skill: {skill}
version: "1.0"
config:
  trials_per_task: 1
  timeout_seconds: 60
  parallel: false
  executor: mock
tasks:
  - "tasks/*.yaml"
"""

TASK_TEMPLATE = """\
id: {task_id}
name: {name}
description: >-
{why}
tags:
  - {kind}-trigger
inputs:
  prompt: >-
{prompt}
expected:
  should_trigger: {should}
graders:
  - type: trigger
    name: {grader_name}
    config:
      skill_path: {skill_path}
      mode: {kind}
      threshold: 0.6
"""


def block(text: str, indent: str = "    ") -> str:
    return textwrap.indent(textwrap.fill(text, 84), indent)


def main() -> None:
    written = 0
    for skill, path in SKILL_PATHS.items():
        d = os.path.join(EVALS, skill, "tasks")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(EVALS, skill, "eval.yaml"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write(EVAL_TEMPLATE.format(skill=skill))
        written += 1

    for skill, task_id, kind, prompt, why in CASES:
        name = ("Should route to %s" if kind == "positive"
                else "Should NOT route to %s") % skill
        body = TASK_TEMPLATE.format(
            task_id="%s-%s" % (skill, task_id),
            name=name,
            why=block(why),
            kind=kind,
            prompt=block(prompt),
            should="true" if kind == "positive" else "false",
            grader_name=("routes-to-%s" if kind == "positive"
                         else "stays-out-of-%s") % skill,
            skill_path=SKILL_PATHS[skill],
        )
        out = os.path.join(EVALS, skill, "tasks", "%s.yaml" % task_id)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        written += 1

    print("wrote %d files across %d skills" % (written, len(SKILL_PATHS)))


if __name__ == "__main__":
    main()
