#!/usr/bin/env python3
"""Fail the build when a skill or agent has frontmatter the CLI cannot parse.

Why this exists
---------------
Invalid YAML frontmatter does not produce an error anywhere. The Copilot CLI
simply **drops the artifact**, and from inside a session a dropped skill is
indistinguishable from one that was never a good match. Measured on the
installed `agile-agents-core` v0.8.0: 36 skills on disk, 35 offered to the
session, and the one missing was the single skill whose frontmatter did not
parse (`artifact-coverage`). `ado-work-items` was likewise absent. Both had the
same defect and nothing in CI noticed.

The defect is easy to reintroduce and invisible on review: a *plain* (unquoted)
YAML scalar may not contain a colon-space, so a perfectly reasonable-looking
description such as

    description: ... Load only when `solution-profile.yaml: backlog.platform == x`.

is invalid YAML. Use a block scalar (`>-`) — the house style — and it is legal.

Checks (all fatal):
  1. A `---` frontmatter block exists.
  2. It parses as YAML, strictly.
  3. It is a mapping with non-empty `name` and `description`.
  4. Skills: `name` matches the containing directory (the CLI addresses skills
     by directory name; a mismatch makes the skill unaddressable).
  5. Skills: `applies_to` is present — repo convention states a missing value
     is a defect, not a default.

Usage:
  check-skill-frontmatter.py [repo-root]
  check-skill-frontmatter.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
import tempfile

try:
    import yaml
except ImportError:  # pragma: no cover - environment problem, not a repo defect
    print("error: PyYAML is required (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(3)

FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def inspect(path: str, kind: str, dirname: str | None = None) -> list[str]:
    """Return a list of defect messages for one artifact ("" list == clean)."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    match = FRONTMATTER.match(text)
    if not match:
        return ["no `---` frontmatter block"]

    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")[:160]
        hint = ""
        if "mapping values are not allowed" in detail:
            hint = ("  -> a plain scalar cannot contain ': '; "
                    "use a block scalar (description: >-)")
        return ["frontmatter is not valid YAML: %s%s" % (detail, hint)]

    if not isinstance(data, dict):
        return ["frontmatter is not a YAML mapping"]

    defects = []
    for field in ("name", "description"):
        value = data.get(field)
        if not (isinstance(value, str) and value.strip()):
            defects.append("missing or empty `%s`" % field)

    if kind == "skill":
        name = data.get("name")
        if isinstance(name, str) and dirname and name.strip() != dirname:
            defects.append("`name: %s` does not match its directory `%s`"
                           % (name.strip(), dirname))
        if not data.get("applies_to"):
            defects.append("missing `applies_to` (required on every skill)")

    return defects


def scan(repo_root: str):
    """Yield (kind, label, path, defects) for every artifact under plugins/."""
    plugins = os.path.join(repo_root, "plugins")
    if not os.path.isdir(plugins):
        raise SystemExit("error: no plugins/ directory under %s" % repo_root)

    for plugin in sorted(os.listdir(plugins)):
        skills = os.path.join(plugins, plugin, "skills")
        if os.path.isdir(skills):
            for name in sorted(os.listdir(skills)):
                path = os.path.join(skills, name, "SKILL.md")
                if os.path.isfile(path):
                    yield "skill", name, path, inspect(path, "skill", name)

        agents = os.path.join(plugins, plugin, "agents")
        if os.path.isdir(agents):
            for filename in sorted(os.listdir(agents)):
                if filename.endswith(".agent.md"):
                    path = os.path.join(agents, filename)
                    label = filename[: -len(".agent.md")]
                    yield "agent", label, path, inspect(path, "agent")


def run(repo_root: str) -> int:
    total, failures = 0, []
    for kind, label, path, defects in scan(repo_root):
        total += 1
        for defect in defects:
            failures.append((kind, label, path, defect))

    if failures:
        print("Frontmatter check failed:\n")
        for kind, label, path, defect in failures:
            rel = os.path.relpath(path, repo_root)
            print("  [%s] %-34s %s" % (kind, label, defect))
            print("        %s" % rel)
        print("\n%d defect(s) across %d artifact(s)." % (len(failures), total))
        print("A skill whose frontmatter does not parse is silently dropped by the "
              "CLI — it can never be invoked.")
        return 1

    print("Frontmatter check passed: %d artifacts, all frontmatter valid." % total)
    return 0


# --- self-test ---------------------------------------------------------------
# The repo's doctrine: a green check nobody has tried to falsify is not evidence.
# Each case plants one defect and asserts it is caught.

SELF_TEST_CASES = [
    ("valid", "---\nname: demo\ndescription: A fine description.\napplies_to: all\n---\n\nbody\n", 0),
    ("colon-space in plain scalar",
     "---\nname: demo\ndescription: Load when `profile.yaml: key == x`.\napplies_to: all\n---\n\nbody\n", 1),
    ("no frontmatter", "# just a heading\n", 1),
    ("empty description", "---\nname: demo\ndescription: ''\napplies_to: all\n---\n\nbody\n", 1),
    ("missing applies_to", "---\nname: demo\ndescription: Fine.\n---\n\nbody\n", 1),
    ("name/dir mismatch",
     "---\nname: other\ndescription: Fine.\napplies_to: all\n---\n\nbody\n", 1),
    ("not a mapping", "---\n- just\n- a list\n---\n\nbody\n", 1),
]


def self_test() -> int:
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        for label, content, expected in SELF_TEST_CASES:
            skill_dir = os.path.join(tmp, "plugins", "p", "skills", "demo")
            os.makedirs(skill_dir, exist_ok=True)
            path = os.path.join(skill_dir, "SKILL.md")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            defects = inspect(path, "skill", "demo")
            got = 1 if defects else 0
            status = "PASS" if got == expected else "FAIL"
            if got != expected:
                ok = False
            print("  %s  %-32s %s" % (status, label,
                                      defects[0] if defects else "(clean)"))
    print("self-test: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--self-test" in args:
        raise SystemExit(self_test())
    root = args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(run(root))
