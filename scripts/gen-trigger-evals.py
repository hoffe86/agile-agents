"""Generate/check current S0 routing suites; no model calls or calibrated gate.

The authored prompts are the asset. Each retained target has positive cases and
a plausible near-miss. Removed distribution targets are not consumer fixtures.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import textwrap

REPO = Path(__file__).resolve().parents[1]
EVALS = Path("eval/skills/s0-routing")
SKILL_PATHS = {
    name: f"plugins/agile-agents-core/skills/{name}/SKILL.md"
    for name in (
        "engineering-judgement", "testing-practices", "development-practices",
        "read-repo-context", "test-bar-gate",
    )
}

# (skill, task-id, kind, prompt, why)
CASES = [
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


def block(text: str) -> str:
    return textwrap.indent(textwrap.fill(text, 84), "    ")


def rendered_files() -> dict[Path, str]:
    files = {EVALS / skill / "eval.yaml": EVAL_TEMPLATE.format(skill=skill)
             for skill in SKILL_PATHS}
    for skill, task_id, kind, prompt, why in CASES:
        path = EVALS / skill / "tasks" / f"{task_id}.yaml"
        if path in files:
            raise ValueError(f"duplicate S0 case: {path}")
        files[path] = TASK_TEMPLATE.format(
            task_id=f"{skill}-{task_id}",
            name=("Should route to %s" if kind == "positive"
                  else "Should NOT route to %s") % skill,
            why=block(why), kind=kind, prompt=block(prompt),
            should="true" if kind == "positive" else "false",
            grader_name=("routes-to-%s" if kind == "positive"
                         else "stays-out-of-%s") % skill,
            skill_path=SKILL_PATHS[skill],
        )
    return files


def inventory_errors(root: Path) -> list[str]:
    errors = [f"missing skill: {path}" for path in SKILL_PATHS.values()
              if not (root / path).is_file()]
    for skill in SKILL_PATHS:
        kinds = {case[2] for case in CASES if case[0] == skill}
        if kinds != {"positive", "negative"}:
            errors.append(f"{skill}: positive and negative cases required")
    expected = set(rendered_files())
    actual = {p.relative_to(root) for p in (root / EVALS).rglob("*.yaml")}
    errors.extend(f"orphan suite file: {p}" for p in sorted(actual - expected))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check without writing")
    args = parser.parse_args()
    errors = inventory_errors(REPO)
    if errors:
        print("\n".join(errors))
        return 1
    files = rendered_files()
    for relative, content in files.items():
        path = REPO / relative
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                errors.append(f"generated content drift: {relative}")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
    if errors:
        print("\n".join(errors))
        return 1
    print(f"{'checked' if args.check else 'wrote'} {len(files)} files across "
          f"{len(SKILL_PATHS)} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
