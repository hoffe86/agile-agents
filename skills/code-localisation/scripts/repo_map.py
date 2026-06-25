#!/usr/bin/env python3
"""Tree-sitter-based repo-map for the `code-localisation` skill.

Returns a ranked JSON list of files most likely to be relevant to a natural-
language task description. Designed for the *default* backend of the
`code-localisation` skill (see ../SKILL.md and ../references/localisation-backends.md).

Approach (Aider-inspired, see https://aider.chat/docs/repomap.html):
  1. Walk the repo, skipping .git, node_modules, venv, build outputs, and
     anything in .gitignore (best-effort; we don't pull in a full ignore parser).
  2. Parse each source file with `tree_sitter_languages` to extract top-level
     symbol names (functions, classes, methods). If the package isn't
     installed, fall back to a path-only heuristic and emit a stderr note.
  3. Score each file by:
        a) symbol-name term overlap with the query   (weight 0.55)
        b) path-component term overlap with the query (weight 0.30)
        c) recency (mtime) as a small tiebreaker      (weight 0.15 max)
  4. Emit the top-K as JSON to stdout.

References:
  - tree-sitter:        https://tree-sitter.github.io/
  - Aider repo-map:     https://aider.chat/docs/repomap.html
  - Agentless paper:    https://arxiv.org/abs/2407.01489
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterable

SOURCE_EXTS = {
    ".cs", ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt",
    ".rs", ".rb", ".php", ".cpp", ".cc", ".c", ".h", ".hpp", ".swift",
    ".scala", ".m", ".mm", ".fs", ".vb",
}
SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "out", "bin", "obj", "target", ".next", ".nuxt",
    ".terraform", ".gradle", ".idea", ".vs", ".vscode", "coverage",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def tokenize(text: str) -> set[str]:
    """Lower-case word tokens, splitting CamelCase and snake_case."""
    raw = TOKEN_RE.findall(text)
    out: set[str] = set()
    for w in raw:
        for piece in CAMEL_RE.split(w):
            for sub in piece.split("_"):
                if len(sub) >= 3:
                    out.add(sub.lower())
    return out


def iter_source_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix.lower() in SOURCE_EXTS:
                yield p


def try_load_tree_sitter():
    try:
        from tree_sitter_languages import get_parser  # type: ignore
        return get_parser
    except Exception:
        print(
            "[repo_map] tree_sitter_languages not available; falling back to path-only heuristic.",
            file=sys.stderr,
        )
        return None


EXT_TO_LANG = {
    ".py": "python", ".cs": "c_sharp", ".ts": "typescript", ".tsx": "tsx",
    ".js": "javascript", ".jsx": "javascript", ".go": "go", ".java": "java",
    ".kt": "kotlin", ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".cpp": "cpp", ".cc": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp",
}


def extract_symbols(path: Path, get_parser) -> set[str]:
    """Best-effort extraction of top-level identifier names. Empty set on failure."""
    if get_parser is None:
        return set()
    lang = EXT_TO_LANG.get(path.suffix.lower())
    if not lang:
        return set()
    try:
        parser = get_parser(lang)
        src = path.read_bytes()
        tree = parser.parse(src)
    except Exception:
        return set()
    names: set[str] = set()

    def walk(node):
        # Heuristic: any "identifier" child of a definition-like node is a symbol.
        if node.type in {"function_definition", "method_definition", "class_definition",
                         "function_declaration", "method_declaration", "class_declaration",
                         "interface_declaration", "type_declaration", "struct_declaration",
                         "enum_declaration"}:
            for child in node.children:
                if child.type in {"identifier", "name", "type_identifier", "property_identifier"}:
                    names.add(src[child.start_byte:child.end_byte].decode("utf-8", "ignore"))
                    break
        for child in node.children:
            walk(child)

    try:
        walk(tree.root_node)
    except Exception:
        pass
    return names


def score_file(path: Path, root: Path, query_terms: set[str], symbols: set[str],
               mtime: float, now: float) -> tuple[float, str]:
    rel = path.relative_to(root).as_posix()
    path_terms = tokenize(rel)
    sym_terms = set()
    for s in symbols:
        sym_terms |= tokenize(s)

    sym_overlap = len(query_terms & sym_terms)
    path_overlap = len(query_terms & path_terms)
    sym_norm = sym_overlap / max(1, len(query_terms))
    path_norm = path_overlap / max(1, len(query_terms))

    age_days = max(0.0, (now - mtime) / 86400.0)
    recency = max(0.0, 1.0 - min(age_days, 180.0) / 180.0)  # 0..1

    score = 0.55 * sym_norm + 0.30 * path_norm + 0.15 * recency

    why_bits = []
    if sym_overlap:
        hits = sorted((query_terms & sym_terms))[:3]
        why_bits.append(f"symbol terms match: {', '.join(hits)}")
    if path_overlap:
        hits = sorted((query_terms & path_terms))[:3]
        why_bits.append(f"path terms match: {', '.join(hits)}")
    if not why_bits:
        why_bits.append("recency-only candidate (no term overlap; degraded mode)")
    return score, "; ".join(why_bits)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Rank files in a repo by likely relevance to a task description.",
        epilog="See ../SKILL.md and ../references/localisation-backends.md for context.",
    )
    ap.add_argument("--root", required=True, help="Repository root path")
    ap.add_argument("--query", required=True, help="Natural-language task description")
    ap.add_argument("--max-files", type=int, default=10, help="Cap on returned files (default 10)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[repo_map] --root is not a directory: {root}", file=sys.stderr)
        return 2

    query_terms = tokenize(args.query)
    if not query_terms:
        print("[]")
        return 0

    get_parser = try_load_tree_sitter()
    now = time.time()

    scored: list[tuple[float, str, str]] = []
    for path in iter_source_files(root):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        symbols = extract_symbols(path, get_parser)
        score, why = score_file(path, root, query_terms, symbols, mtime, now)
        if score > 0:
            scored.append((score, path.relative_to(root).as_posix(), why))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[: max(1, args.max_files)]

    out = [{"path": p, "score": round(s, 4), "why": w} for (s, p, w) in top]
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
