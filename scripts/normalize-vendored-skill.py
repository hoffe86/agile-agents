#!/usr/bin/env python3
"""Compare vendored text, removing only our frontmatter scope annotation.

stdin/stdout are JSON objects with ``local`` and ``upstream`` strings. This is
also the offline test seam for check-vendored-drift.ps1. No YAML reserialization:
unrelated whitespace, comments, native fields and the entire body remain visible.
Only CRLF versus LF is normalized on both sides.
"""
from __future__ import annotations

import importlib
import json
import re
import sys

import yaml

checker = importlib.import_module("check-skill-frontmatter")
FRONTMATTER = re.compile(r"\A---\n(?P<yaml>.*?)^---(?:\n|\Z)", re.M | re.S)


def parse(text: str) -> tuple[re.Match[str], dict]:
    match = FRONTMATTER.match(text)
    if not match:
        raise ValueError("missing frontmatter delimiters")
    source = match.group("yaml")
    data = yaml.load(source, Loader=checker.ProfileLoader)
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise ValueError("metadata must be a mapping")
    return match, data


def comparable(local: str, upstream: str) -> tuple[str, str]:
    """Fail closed on collisions or ambiguous syntax; never mask upstream scope."""
    local = local.replace("\r\n", "\n")
    upstream = upstream.replace("\r\n", "\n")
    match, data = parse(local)
    _, remote = parse(upstream)
    if "applies_to" in remote or "applies_to" in remote.get("metadata", {}):
        raise ValueError("upstream applies_to collision; manual triage required")
    defects = checker.inspect_skill_scope(data)
    if defects:
        raise ValueError("; ".join(defects))

    # Source marks locate the exact entry inside the frontmatter, never the body.
    # Validation above rejects duplicate keys before composing nodes.
    node = yaml.compose(match.group("yaml"))
    entries = [(k, v) for k, v in node.value if k.value == "metadata"]
    if len(entries) != 1:
        raise ValueError("metadata must be an explicit block mapping, not merged")
    metadata_key, metadata = entries[0]
    entries = [(k, v) for k, v in metadata.value if k.value == "applies_to"]
    if len(entries) != 1:
        raise ValueError("scope annotation must be explicit, not merged")
    scope_key, scope = entries[0]
    lines = match.group("yaml").splitlines(keepends=True)
    start = scope_key.start_mark.line
    end = scope.end_mark.line
    if (metadata.flow_style or metadata.start_mark.line <= metadata_key.start_mark.line
            or scope_key.start_mark.line <= metadata_key.start_mark.line
            or scope.style in ("|", ">")
            or start != end or scope_key.start_mark.column != 2
            or not lines[start].startswith("  applies_to: ")
            or lines[start][scope.end_mark.column:] != "\n"):
        raise ValueError("scope annotation must be a standalone two-space-indented scalar line")
    del lines[start]

    # Only remove a bare wrapper absent upstream, introduced solely for our entry.
    # Comments/blank lines in the wrapper are meaningful drift, not disposable YAML.
    wrapper = metadata_key.start_mark.line
    if ("metadata" not in remote and len(metadata.value) == 1
            and lines[wrapper] == "metadata:\n"
            and start == wrapper + 1):
        # Comments immediately after the annotation must not vanish with a wrapper.
        following = lines[wrapper + 1] if wrapper + 1 < len(lines) else ""
        if not following or (following[0] not in " #\t\n"):
            del lines[wrapper]
    normalized = local[:match.start("yaml")] + "".join(lines) + local[match.end("yaml"):]
    return normalized, upstream


def main() -> int:
    try:
        request = json.load(sys.stdin)
        local, upstream = comparable(request["local"], request["upstream"])
    except (ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"vendored comparison failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"local": local, "upstream": upstream}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
