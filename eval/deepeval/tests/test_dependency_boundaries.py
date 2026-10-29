"""Offline checks for the evaluation package's one-way ownership boundaries."""

import ast
import importlib.util
from itertools import permutations
from pathlib import Path
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "python"
PACKAGE = SOURCE / "agile_eval"


def import_graph(sources):
    """Include function-local imports: delaying a reciprocal import is still a cycle."""
    graph = {name: set() for name in sources}
    for name, source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                graph[name].update(alias.name for alias in node.names if alias.name in sources)
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = importlib.util.resolve_name("." * node.level + base, name.rpartition(".")[0])
                for alias in node.names:
                    candidate = f"{base}.{alias.name}"
                    if candidate in sources:
                        graph[name].add(candidate)
                    elif base in sources:
                        graph[name].add(base)
    return graph


def assert_acyclic(graph):
    visited = set()

    def visit(name, ancestors):
        assert name not in ancestors, "import cycle: " + " -> ".join((*ancestors, name))
        if name in visited:
            return
        for dependency in sorted(graph[name]):
            visit(dependency, (*ancestors, name))
        visited.add(name)

    for name in sorted(graph):
        visit(name, ())


def test_firstparty_imports_follow_approved_ownership_without_delayed_cycles():
    for initializer in PACKAGE.rglob("__init__.py"):
        body = ast.parse(initializer.read_text(encoding="utf-8")).body
        assert not body or (
            len(body) == 1 and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str)
        ), f"package initializer must remain inert: {initializer}"
    sources = {
        "agile_eval." + ".".join(path.relative_to(PACKAGE).with_suffix("").parts):
        path.read_text(encoding="utf-8")
        for path in PACKAGE.rglob("*.py") if path.name != "__init__.py"
    }
    graph = import_graph(sources)
    assert_acyclic(graph)
    expected = {
        "grading_contract": set(),
        "file_io": set(),
        "workspace_inputs": {"file_io"},
        "provenance": {"file_io", "workspace_inputs", "grading_contract"},
        "grading": {"grading_contract", "workspace_inputs", "provenance"},
    }
    for module, dependencies in expected.items():
        assert graph[f"agile_eval.{module}"] == {f"agile_eval.{name}" for name in dependencies}


@pytest.mark.parametrize("reciprocal", [
    "from agile_eval.grading import held_workspace_result",
    "from agile_eval import grading as shared",
    "import agile_eval.grading as shared",
    "from .grading import held_workspace_result",
])
def test_dependency_check_rejects_reciprocal_import_even_inside_function(reciprocal):
    graph = import_graph({
        "agile_eval.grading": "from agile_eval import provenance",
        "agile_eval.provenance": f"def delayed():\n    {reciprocal}\n",
    })
    with pytest.raises(AssertionError, match="import cycle:"):
        assert_acyclic(graph)


def isolated(script, tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script, str(SOURCE), *args],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


@pytest.mark.parametrize("order", list(permutations(("grading", "provenance", "workspace_inputs"))))
def test_clean_process_import_order_preserves_contract_identity_without_optional_dependencies(tmp_path, order):
    script = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
loaded = set()
for name in sys.argv[2:]:
    module = importlib.import_module('agile_eval.' + name)
    if name != 'grading' and 'grading' not in loaded:
        assert 'agile_eval.grading' not in sys.modules
    loaded.add(name)
from agile_eval import grading, grading_contract, provenance, workspace_inputs, file_io
assert grading.grading_contract is provenance.grading_contract is grading_contract
assert grading.workspace_inputs is provenance.workspace_inputs is workspace_inputs
assert workspace_inputs.file_io is provenance.file_io is file_io
assert grading_contract.parse_result('1. PASS - ok\\nVERDICT: RESOLVED', 1).verdict is grading_contract.Verdict.RESOLVED
assert not any(name.split('.')[0] in {'deepeval', 'copilot', 'yaml'} for name in sys.modules)
assert 'agile_eval.prepare_inputs' not in sys.modules
assert not any(hasattr(grading, name) for name in (
    'JudgeResult', 'Verdict', 'parse_result', 'immutable_inputs', 'write_result', 'result_status'))
assert not any(hasattr(provenance, name) for name in ('read_bytes', 'write_json', 'checked_path'))
"""
    result = isolated(script, tmp_path, *order)
    assert result.returncode == 0, result.stdout + result.stderr


def test_pure_contract_import_and_parsing_have_no_io_or_optional_dependency_effects(tmp_path):
    script = """
import builtins
import dataclasses
import enum
import re
import logging
import os
import sys
from contextlib import ExitStack
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
before_path, before_env = list(sys.path), dict(os.environ)
forbidden = []
def deny(*args, **kwargs):
    forbidden.append('effect')
    raise AssertionError('pure contract must not perform I/O')
original_import = builtins.__import__
def limited_import(name, *args, **kwargs):
    # CPython's source loader imports _io to read module bytes, not contract code.
    if name == '_io' and sys._getframe(1).f_code.co_filename.startswith('<frozen importlib.'):
        return original_import(name, *args, **kwargs)
    if name.split('.')[0] not in {'agile_eval', '__future__', 'dataclasses', 'enum', 're'}:
        forbidden.append(name)
        raise AssertionError('unexpected contract dependency: ' + name)
    return original_import(name, *args, **kwargs)
def audit(event, args):
    if event == 'open' or event.startswith(('os.', 'socket.', 'subprocess.', 'shutil.', 'sqlite3.')):
        # Normal import must read its source/bytecode and discover module files.
        # No application reads or writes are permitted, including reads of itself.
        caller = sys._getframe(1).f_code.co_filename
        if caller.startswith('<frozen importlib.') and event in {'open', 'os.listdir'}:
            if event != 'open' or not args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
                return
        forbidden.append(event)
        raise AssertionError('pure contract effect: ' + event)
with ExitStack() as stack:
    stack.enter_context(patch.object(builtins, '__import__', limited_import))
    stack.enter_context(patch.object(logging.Logger, '_log', deny))
    stack.enter_context(patch.object(logging, 'basicConfig', deny))
    for stream in (sys.stdout, sys.stderr):
        stack.enter_context(patch.object(stream, 'write', deny))
        stack.enter_context(patch.object(stream, 'reconfigure', deny))
    sys.addaudithook(audit)
    from agile_eval import grading_contract as contract
    result = contract.parse_result('1. PASS - checked\\n2. UNVERIFIED - unavailable\\nVERDICT: RESOLVED', 2)
    assert result.verdict is contract.Verdict.UNVERIFIED and result.score == 0
    assert result.to_dict()['schema_version'] == 2
    assert contract.verification_disabled(1).exit_code == 3
    assert contract.environment_error('private detail', 'setup').exit_code == 4
assert not forbidden, forbidden
assert sys.path == before_path and dict(os.environ) == before_env
assert not any(name.split('.')[0] in {'yaml', 'deepeval', 'copilot'} for name in sys.modules)
assert not any(name in sys.modules for name in (
    'agile_eval.file_io', 'agile_eval.workspace_inputs', 'agile_eval.provenance', 'agile_eval.grading'))
"""
    result = isolated(script, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reporting_import_does_not_reconfigure_streams_but_main_still_does(tmp_path):
    script = """
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from agile_eval import _console
streams = sys.stdout, sys.stderr
with (
    patch.object(_console, 'use_utf8_stdio', side_effect=AssertionError('import configured streams')),
    patch.object(sys.stdout, 'reconfigure', side_effect=AssertionError('import reconfigured stdout')),
    patch.object(sys.stderr, 'reconfigure', side_effect=AssertionError('import reconfigured stderr')),
):
    from agile_eval import report_skill_usage
assert (sys.stdout, sys.stderr) == streams
with patch.object(report_skill_usage, 'use_utf8_stdio') as configure:
    with patch.object(sys, 'argv', ['report_skill_usage.py', 'missing-logs']):
        assert report_skill_usage.main() == 1
    configure.assert_called_once_with()
"""
    result = isolated(script, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no logs found under missing-logs" in result.stdout
