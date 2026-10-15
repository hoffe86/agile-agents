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
  5. Skills: `metadata.applies_to` is a nonempty string; legacy placement,
     duplicate keys, and nested native fields fail.
  6. Agents: `metadata` is a string-to-string mapping containing `model_tier`
     (light / mid / heavy). Legacy top-level tiers and nested native fields fail.
  7. Core agents: the ADR 0007 inventory and tier assignments are preserved.
  8. Root profile and shipped template: advisory model lists are well formed and
     reference only declared approved models (not runtime model enforcement).

Agent annotations are advisory. These checks neither select a runtime model nor
enforce runtime approved-model selection. Skill metadata validation covers only
the locally owned scope annotation, not full AgentSkills string-map conformance:
inherited metadata (including upstream enhancement lists) is preserved.

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

# ADR 0007's approved preferences, not a model resolver.
CORE_MODEL_TIERS = {
    "architect": "heavy",
    "architecture-reviewer": "heavy",
    "backlog-manager": "mid",
    "bootstrapper": "mid",
    "capability-scout": "heavy",
    "code-reviewer": "heavy",
    "coding": "mid",
    "data-reviewer": "heavy",
    "data-scientist": "heavy",
    "dev-lead": "heavy",
    "infrastructure-reviewer": "heavy",
    "infrastructure": "mid",
    "review-lead": "heavy",
    "security-reviewer": "heavy",
    "test-reviewer": "heavy",
}
NATIVE_AGENT_FIELDS = {
    "name", "description", "model", "tools", "agents", "argument-hint",
    "handoffs", "target", "infer", "user-invocable", "disable-model-invocation",
    "mcp-servers",
}
NATIVE_SKILL_FIELDS = {
    "name", "description", "license", "compatibility", "allowed-tools",
    "argument-hint", "user-invocable", "disable-model-invocation",
}


def inspect_skill_scope(data: dict) -> list[str]:
    """Validate our annotation without imposing a schema on inherited metadata."""
    defects = []
    if "applies_to" in data:
        defects.append("legacy top-level `applies_to`; use `metadata.applies_to`")
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        defects.append("missing or non-mapping `metadata`")
    else:
        scope = metadata.get("applies_to")
        if not isinstance(scope, str) or not scope.strip():
            defects.append("missing or invalid `metadata.applies_to` (expected a nonempty string)")
        for field in sorted(NATIVE_SKILL_FIELDS.intersection(metadata)):
            defects.append("native `%s` must remain top-level, not in `metadata`" % field)
    return defects


def inspect(path: str, kind: str, dirname: str | None = None,
            expected_tier: str | None = None) -> list[str]:
    """Return a list of defect messages for one artifact ("" list == clean)."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    match = FRONTMATTER.match(text)
    if not match:
        return ["no `---` frontmatter block"]

    try:
        if kind == "skill":
            data = yaml.load(match.group(1), Loader=ProfileLoader)
        else:
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
        defects.extend(inspect_skill_scope(data))

    if kind == "agent":
        if "model_tier" in data:
            defects.append("legacy top-level `model_tier`; use `metadata.model_tier`")
        metadata = data.get("metadata")
        if not isinstance(metadata, dict):
            defects.append("missing or non-mapping `metadata` (expected a string-to-string map)")
        else:
            if any(not isinstance(key, str) or not isinstance(value, str)
                   for key, value in metadata.items()):
                defects.append("`metadata` keys and values must be strings")
            for field in sorted(NATIVE_AGENT_FIELDS.intersection(metadata)):
                defects.append("native `%s` must remain top-level, not in `metadata`" % field)
            tier = metadata.get("model_tier")
            if not isinstance(tier, str) or tier not in ("light", "mid", "heavy"):
                defects.append("missing or invalid `metadata.model_tier` (expected light / mid / heavy)")
            elif expected_tier is not None and tier != expected_tier:
                defects.append("expected `metadata.model_tier: %s` (ADR 0007)" % expected_tier)

    return defects


class ProfileLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently discarding profile policy."""

    def __init__(self, stream):
        super().__init__(stream)
        self._checked_mappings = set()

    def flatten_mapping(self, node):
        if not isinstance(node, yaml.MappingNode):
            raise yaml.constructor.ConstructorError(
                None, None, "expected a mapping node", node.start_mark)
        # PyYAML calls this recursively for inline and sequence merge sources.
        # Aliases can revisit nodes already flattened; their inherited keys must
        # not be mistaken for duplicate explicit keys.
        if node in self._checked_mappings:
            return
        keys = set()
        for key_node, _ in node.value:
            key = (key_node.value if key_node.tag == "tag:yaml.org,2002:merge"
                   else self.construct_object(key_node))
            try:
                if key in keys:
                    raise yaml.constructor.ConstructorError(
                        None, None, f"duplicate key: {key!r}", key_node.start_mark)
                keys.add(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    None, None, "mapping key must be hashable", key_node.start_mark) from exc
        self._checked_mappings.add(node)
        super().flatten_mapping(node)

    def construct_object(self, node, deep=False):
        try:
            return super().construct_object(node, deep=deep)
        except ValueError as exc:
            # PyYAML's numeric and timestamp constructors can raise ValueError
            # for invalid scalar values rather than a YAML diagnostic.
            if not isinstance(node, yaml.ScalarNode) or node.tag not in (
                    "tag:yaml.org,2002:int", "tag:yaml.org,2002:float",
                    "tag:yaml.org,2002:timestamp"):
                raise
            raise yaml.constructor.ConstructorError(
                None, None, f"invalid {node.tag.rsplit(':', 1)[-1]}: {exc}",
                node.start_mark) from exc


def inspect_profile(path: str) -> list[str]:
    """Validate only the advisory model policy, not a general profile schema."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=ProfileLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        return ["profile could not be read as valid YAML: " + str(exc)]
    if not isinstance(data, dict):
        return ["profile must be a YAML mapping"]

    for section in ("cost_envelope", "ai_copilot"):
        if section in data and not isinstance(data[section], dict):
            return [f"`{section}` must be a mapping"]
    tiers = data.get("cost_envelope", {}).get("model_tiers", {})
    if not isinstance(tiers, dict):
        return ["`cost_envelope.model_tiers` must be a mapping (or omitted)"]
    approved = data.get("ai_copilot", {}).get("approved_models", [])
    if not isinstance(approved, list) or any(
            not isinstance(model, str) or not model.strip() for model in approved):
        return ["`ai_copilot.approved_models` must be a list of nonempty model strings"]
    defects = []
    if len(approved) != len(set(approved)):
        defects.append("duplicate model in `ai_copilot.approved_models`")
    seen = set()
    for tier, models in tiers.items():
        label = f"cost_envelope.model_tiers.{tier}"
        if tier not in ("heavy", "mid", "light"):
            defects.append(f"invalid tier {tier!r}; expected heavy / mid / light")
        if isinstance(models, str):
            models = [models]  # Legacy single-string tier; no coercion of other types.
        if not isinstance(models, list) or not models or any(
                not isinstance(model, str) or not model.strip() for model in models):
            defects.append(f"`{label}` must be a nonempty model string or nonempty list of strings")
            continue
        for model in models:
            if model in seen:
                defects.append(f"duplicate model {model!r} in `{label}`")
            seen.add(model)
            if model not in approved:
                defects.append(f"`{label}` model {model!r} is not in `ai_copilot.approved_models`")
    return defects


def scan(repo_root: str):
    """Inspect artifacts and two explicit profiles, never consumer fixtures."""
    plugins = os.path.join(repo_root, "plugins")
    if not os.path.isdir(plugins):
        raise SystemExit("error: no plugins/ directory under %s" % repo_root)

    for relative in (
        ".github/solution-profile.yaml",
        "plugins/agile-agents-core/skills/solution-profile-interview/"
        "references/solution-profile.template.yaml",
    ):
        path = os.path.join(repo_root, relative)
        if os.path.exists(path):
            yield "profile", relative, path, inspect_profile(path)

    core_path = os.path.join(plugins, "agile-agents-core")
    if not os.path.isdir(core_path):
        yield "plugin", "agile-agents-core", core_path, [
            "missing core plugin (ADR 0007 inventory)"]

    for plugin in sorted(os.listdir(plugins)):
        skills = os.path.join(plugins, plugin, "skills")
        if os.path.isdir(skills):
            for name in sorted(os.listdir(skills)):
                path = os.path.join(skills, name, "SKILL.md")
                if os.path.isfile(path):
                    yield "skill", name, path, inspect(path, "skill", name)

        agents = os.path.join(plugins, plugin, "agents")
        core = plugin == "agile-agents-core"
        found = set()
        if os.path.isdir(agents):
            for filename in sorted(os.listdir(agents)):
                if filename.endswith(".agent.md"):
                    path = os.path.join(agents, filename)
                    label = filename[: -len(".agent.md")]
                    found.add(label)
                    expected = CORE_MODEL_TIERS.get(label) if core else None
                    defects = inspect(path, "agent", expected_tier=expected)
                    if core and label not in CORE_MODEL_TIERS:
                        defects.append("unexpected core agent (update the approved ADR 0007 inventory)")
                    yield "agent", label, path, defects
        if core:
            for label in sorted(CORE_MODEL_TIERS.keys() - found):
                path = os.path.join(agents, label + ".agent.md")
                yield "agent", label, path, ["missing core agent (ADR 0007 inventory)"]


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
    ("valid", "---\nname: demo\ndescription: A fine description.\nmetadata:\n  applies_to: all\n---\n\nbody\n", 0),
    ("colon-space in plain scalar",
     "---\nname: demo\ndescription: Load when `profile.yaml: key == x`.\nmetadata:\n  applies_to: all\n---\n\nbody\n", 1),
    ("no frontmatter", "# just a heading\n", 1),
    ("empty description", "---\nname: demo\ndescription: ''\nmetadata:\n  applies_to: all\n---\n\nbody\n", 1),
    ("missing metadata", "---\nname: demo\ndescription: Fine.\n---\n\nbody\n", 1),
    ("missing scope", "---\nname: demo\ndescription: Fine.\nmetadata: {}\n---\n\nbody\n", 1),
    ("legacy scope", "---\nname: demo\ndescription: Fine.\napplies_to: all\n---\n\nbody\n", 1),
    ("duplicate scope", "---\nname: demo\ndescription: Fine.\nmetadata:\n  applies_to: all\n  applies_to: python\n---\n", 1),
    ("name/dir mismatch",
     "---\nname: other\ndescription: Fine.\nmetadata:\n  applies_to: all\n---\n\nbody\n", 1),
    ("not a mapping", "---\n- just\n- a list\n---\n\nbody\n", 1),
]

# Inline fixtures deliberately separate agent annotations from skill metadata.
AGENT_SELF_TEST_CASES = [
    ("nested light", "metadata:\n  model_tier: light\n", None, None),
    ("nested mid", "metadata:\n  model_tier: mid\n", "mid", None),
    ("nested heavy", "metadata:\n  model_tier: heavy\n", None, None),
    ("native model independent",
     "model: any-runtime-model\ntools: [read]\nmetadata:\n  model_tier: light\n",
     None, None),
    ("string annotations", "metadata:\n  model_tier: heavy\n  owner: team\n", None, None),
    ("missing metadata", "", None, "non-mapping `metadata`"),
    ("null metadata", "metadata:\n", None, "non-mapping `metadata`"),
    ("scalar metadata", "metadata: heavy\n", None, "non-mapping `metadata`"),
    ("list metadata", "metadata: [heavy]\n", None, "non-mapping `metadata`"),
    ("numeric metadata", "metadata: 42\n", None, "non-mapping `metadata`"),
    ("boolean metadata", "metadata: true\n", None, "non-mapping `metadata`"),
    ("missing tier", "metadata: {}\n", None, "invalid `metadata.model_tier`"),
    ("unknown tier", "metadata:\n  model_tier: huge\n", None, "invalid `metadata.model_tier`"),
    ("case-sensitive tier", "metadata:\n  model_tier: Heavy\n", None, "invalid `metadata.model_tier`"),
    ("null tier", "metadata:\n  model_tier:\n", None, "invalid `metadata.model_tier`"),
    ("numeric tier", "metadata:\n  model_tier: 1\n", None, "invalid `metadata.model_tier`"),
    ("boolean tier", "metadata:\n  model_tier: true\n", None, "invalid `metadata.model_tier`"),
    ("list tier", "metadata:\n  model_tier: [heavy]\n", None, "invalid `metadata.model_tier`"),
    ("mapping tier", "metadata:\n  model_tier: {value: heavy}\n", None, "invalid `metadata.model_tier`"),
    ("legacy only", "model_tier: heavy\n", None, "legacy top-level"),
    ("legacy and nested", "model_tier: heavy\nmetadata:\n  model_tier: heavy\n",
     None, "legacy top-level"),
    ("changed assignment", "metadata:\n  model_tier: light\n", "mid", "expected `metadata.model_tier: mid`"),
    ("non-string annotation", "metadata:\n  model_tier: heavy\n  owner: [team]\n",
     None, "keys and values must be strings"),
    ("non-string key", "metadata:\n  model_tier: heavy\n  1: team\n",
     None, "keys and values must be strings"),
    # Independent contract fixtures: removing a production field must not remove its test.
    ("nested native agents", "metadata:\n  model_tier: heavy\n  agents: value\n",
     None, "native `agents` must remain top-level"),
    ("nested native argument-hint", "metadata:\n  model_tier: heavy\n  argument-hint: value\n",
     None, "native `argument-hint` must remain top-level"),
    ("nested native description", "metadata:\n  model_tier: heavy\n  description: value\n",
     None, "native `description` must remain top-level"),
    ("nested native disable-model-invocation",
     "metadata:\n  model_tier: heavy\n  disable-model-invocation: value\n",
     None, "native `disable-model-invocation` must remain top-level"),
    ("nested native handoffs", "metadata:\n  model_tier: heavy\n  handoffs: value\n",
     None, "native `handoffs` must remain top-level"),
    ("nested native infer", "metadata:\n  model_tier: heavy\n  infer: value\n",
     None, "native `infer` must remain top-level"),
    ("nested native mcp-servers", "metadata:\n  model_tier: heavy\n  mcp-servers: value\n",
     None, "native `mcp-servers` must remain top-level"),
    ("nested native model", "metadata:\n  model_tier: heavy\n  model: value\n",
     None, "native `model` must remain top-level"),
    ("nested native name", "metadata:\n  model_tier: heavy\n  name: value\n",
     None, "native `name` must remain top-level"),
    ("nested native target", "metadata:\n  model_tier: heavy\n  target: value\n",
     None, "native `target` must remain top-level"),
    ("nested native tools", "metadata:\n  model_tier: heavy\n  tools: value\n",
     None, "native `tools` must remain top-level"),
    ("nested native user-invocable", "metadata:\n  model_tier: heavy\n  user-invocable: value\n",
     None, "native `user-invocable` must remain top-level"),
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
        path = os.path.join(tmp, "demo.agent.md")
        for label, fields, expected_tier, expected_defect in AGENT_SELF_TEST_CASES:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("---\nname: demo\ndescription: Fine.\n" + fields + "---\n\nbody\n")
            defects = inspect(path, "agent", expected_tier=expected_tier)
            passed = (not defects if expected_defect is None else
                      any(expected_defect in defect for defect in defects))
            ok = ok and passed
            print("  %s  %-32s %s" % ("PASS" if passed else "FAIL", label,
                                      "; ".join(defects) if defects else "(clean)"))
        # Skill-standard metadata is not an agent schema; no model tier is required.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("---\nname: demo\ndescription: Fine.\n"
                         "metadata:\n  applies_to: all\n  author: team\n"
                         "  version: '1.3'\n  enhancements: [inherited]\n---\n\nbody\n")
        defects = inspect(path, "skill", "demo")
        ok = ok and not defects
        print("  %s  skill metadata without tier" % ("FAIL" if defects else "PASS"))
    print("self-test: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--self-test" in args:
        raise SystemExit(self_test())
    root = args[0] if args else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    raise SystemExit(run(root))
