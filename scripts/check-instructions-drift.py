#!/usr/bin/env python3
"""Fail the build when `.github/copilot-instructions.md` misstates the roster.

Why this exists
---------------
That file steers every agent run — `read-repo-context` loads it first and treats it
as binding. Its counts are maintained by hand and have gone stale repeatedly: at the
time this check was written it claimed 38 core skills (there were 40), 5 dotnet
skills (6), 4 python (5), 2 bicep (3), 4 workflows (5), and an ADR range ending at
0008 (0014 existed). `AGENTS.md` has had `check-agents-md-in-sync` guarding it since
ADR 0005; this is the equivalent for the instructions file.

Deliberately narrow. It checks only claims that are **mechanically countable** —
counts and ranges — and says nothing about prose. Trying to validate narrative
guidance would be brittle and would fail for the wrong reasons.

Usage:
  check-instructions-drift.py [repo-root]
  check-instructions-drift.py --self-test
"""
from __future__ import annotations

import os
import re
import sys

DOC = os.path.join(".github", "copilot-instructions.md")


def _count_dirs(path: str) -> int:
    return len([d for d in os.listdir(path)
                if os.path.isdir(os.path.join(path, d))]) if os.path.isdir(path) else 0


def actual_facts(repo: str) -> dict:
    """Count what the repository actually contains."""
    plugins = os.path.join(repo, "plugins")
    facts = {}

    core_agents = os.path.join(plugins, "agile-agents-core", "agents")
    facts["agents"] = len([f for f in os.listdir(core_agents)
                           if f.endswith(".agent.md")]) if os.path.isdir(core_agents) else 0

    per_plugin = {}
    total_skills = 0
    for name in sorted(os.listdir(plugins)):
        sdir = os.path.join(plugins, name, "skills")
        n = _count_dirs(sdir)
        if n:
            per_plugin[name] = n
            total_skills += n
    facts["per_plugin"] = per_plugin
    facts["total_skills"] = total_skills
    facts["core_skills"] = per_plugin.get("agile-agents-core", 0)

    wf = os.path.join(repo, ".github", "workflows")
    facts["workflows"] = len([f for f in os.listdir(wf)
                              if f.endswith((".yml", ".yaml"))]) if os.path.isdir(wf) else 0

    adr = os.path.join(repo, "docs", "adr")
    nums = []
    if os.path.isdir(adr):
        for f in os.listdir(adr):
            m = re.match(r"(\d{4})-", f)
            if m:
                nums.append(int(m.group(1)))
    facts["adr_max"] = max(nums) if nums else 0

    # Vendored skills: ONLY the rows under `## Skill → Upstream`. VENDORED.md has
    # three tables — upstream, "Adopted (no longer upstream)", and "Suggested upstream
    # contributions" — and counting rows from all of them over-reports. `polyglot-test-agent`
    # sits in the adopted table and is deliberately counted as hand-written; a skill may
    # also appear again under suggestions. The header row is skipped by requiring a
    # lowercase first character (`Skill` is the header).
    vend = set()
    vpath = os.path.join(plugins, "VENDORED.md")
    if os.path.isfile(vpath):
        in_section = False
        for line in open(vpath, encoding="utf-8"):
            if line.startswith("## "):
                in_section = line.strip().startswith("## Skill")
                continue
            if not in_section:
                continue
            m = re.match(r"\s*\|\s*([a-z0-9][a-z0-9-]+)\s*\|", line)
            if m:
                vend.add(m.group(1))
    facts["vendored"] = len(vend)
    facts["handwritten"] = total_skills - len(vend)
    return facts


def claimed_facts(text: str) -> dict:
    """Pull the countable claims out of the document."""
    claims = {}

    def one(pattern, key, group=1):
        m = re.search(pattern, text)
        if m:
            claims[key] = int(m.group(group))

    one(r"(\d+)\s+\*\.agent\.md", "agents")
    one(r"(\d+)\s+repo-scope skills", "core_skills")
    one(r"(\d+)\s+workflows", "workflows")
    one(r"Architecture decision records \(0001[–-](\d{4})\)", "adr_max")
    one(r"(\d+) of the (\d+) skills are unmodified copies", "vendored", 1)
    one(r"(\d+) of the (\d+) skills are unmodified copies", "total_skills", 2)
    one(r"(?m)^(\d+) are hand-written or adopted", "handwritten")

    per_plugin = {}
    for m in re.finditer(r"agile-agents-([a-z]+)/\s+(\d+)\s+skills?\s+—", text):
        per_plugin["agile-agents-" + m.group(1)] = int(m.group(2))
    if per_plugin:
        claims["per_plugin"] = per_plugin
    return claims


LABELS = {
    "agents": "core agents (*.agent.md)",
    "core_skills": "core repo-scope skills",
    "total_skills": "total skills across plugins",
    "workflows": "CI workflows",
    "adr_max": "highest ADR number",
    "vendored": "vendored skills",
    "handwritten": "hand-written skills",
}


def compare(actual: dict, claimed: dict) -> list[str]:
    problems = []
    for key, label in LABELS.items():
        if key not in claimed:
            problems.append("no claim found for %s — the doc no longer states it, "
                            "or its wording changed and this check needs updating" % label)
        elif claimed[key] != actual[key]:
            problems.append("%s: doc says %s, actual is %s"
                            % (label, claimed[key], actual[key]))

    for name, n in sorted(actual["per_plugin"].items()):
        if name == "agile-agents-core":
            continue  # covered by core_skills
        got = claimed.get("per_plugin", {}).get(name)
        if got is None:
            problems.append("%s: no skill count in the tree diagram" % name)
        elif got != n:
            problems.append("%s: doc says %s skills, actual is %s" % (name, got, n))
    return problems


def run(repo: str) -> int:
    path = os.path.join(repo, DOC)
    if not os.path.isfile(path):
        print("error: %s not found" % DOC, file=sys.stderr)
        return 2

    text = open(path, encoding="utf-8").read()
    problems = compare(actual_facts(repo), claimed_facts(text))

    if problems:
        print("copilot-instructions.md is out of sync with the repository:\n")
        for p in problems:
            print("  %s" % p)
        print("\nThis file is binding — `read-repo-context` loads it first and every agent")
        print("treats it as repo convention, so a stale count misinforms every run.")
        print("Update %s and commit." % DOC)
        return 1

    print("copilot-instructions.md is in sync with the repository.")
    return 0


# --- self-test ---------------------------------------------------------------
# Same doctrine as check-skill-frontmatter.py: prove each assertion trips.

def self_test() -> int:
    actual = {
        "agents": 15, "core_skills": 41, "total_skills": 61, "workflows": 5,
        "adr_max": 14, "vendored": 20, "handwritten": 41,
        "per_plugin": {"agile-agents-core": 41, "agile-agents-dotnet": 6},
    }
    base = {
        "agents": 15, "core_skills": 41, "total_skills": 61, "workflows": 5,
        "adr_max": 14, "vendored": 20, "handwritten": 41,
        "per_plugin": {"agile-agents-core": 41, "agile-agents-dotnet": 6},
    }

    cases = [
        ("in sync", base, 0),
        ("stale agent count", {**base, "agents": 14}, 1),
        ("stale core skill count", {**base, "core_skills": 38}, 1),
        ("stale workflow count", {**base, "workflows": 4}, 1),
        ("stale ADR range", {**base, "adr_max": 8}, 1),
        ("stale vendored count", {**base, "vendored": 19}, 1),
        ("stale companion count",
         {**base, "per_plugin": {"agile-agents-core": 41, "agile-agents-dotnet": 5}}, 1),
        ("missing companion entry",
         {**base, "per_plugin": {"agile-agents-core": 41}}, 1),
        ("claim removed entirely", {k: v for k, v in base.items() if k != "workflows"}, 1),
    ]

    ok = True
    for label, claimed, expected in cases:
        got = 1 if compare(actual, claimed) else 0
        status = "PASS" if got == expected else "FAIL"
        if got != expected:
            ok = False
        detail = (compare(actual, claimed) or ["(clean)"])[0]
        print("  %s  %-26s %s" % (status, label, detail))

    print("self-test: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--self-test" in args:
        raise SystemExit(self_test())
    root = args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(run(root))
