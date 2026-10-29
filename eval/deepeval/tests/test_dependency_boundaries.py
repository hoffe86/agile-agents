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
        "_console": set(),
        "adapters.copilot_trace": set(),
        "metrics.local_model": set(),
        "custom_eval.expectations": set(),
        "custom_eval.trajectory": {"adapters.copilot_trace"},
        "custom_eval.judges": {"custom_eval.expectations"},
        "custom_eval.checks": {"custom_eval.expectations", "custom_eval.judges"},
        "custom_eval.metrics": {
            "adapters.copilot_trace", "custom_eval.expectations",
            "custom_eval.trajectory", "metrics.local_model",
        },
        "custom_eval.runner": {
            "_console", "adapters.copilot_trace", "custom_eval.checks",
            "custom_eval.expectations", "custom_eval.trajectory",
        },
        "custom_eval.scorer": {
            "_console", "adapters.copilot_trace", "custom_eval.checks",
            "custom_eval.expectations",
            "custom_eval.judges", "custom_eval.metrics", "custom_eval.runner",
        },
        "report_skill_usage": {"_console", "adapters.copilot_trace", "metrics.local_model"},
    }
    assert graph == {
        f"agile_eval.{module}": {f"agile_eval.{name}" for name in dependencies}
        for module, dependencies in expected.items()
    }


@pytest.mark.parametrize("reciprocal", [
    "from agile_eval.report_skill_usage import score_logs",
    "from agile_eval import report_skill_usage as shared",
    "import agile_eval.report_skill_usage as shared",
    "from ..report_skill_usage import score_logs",
])
def test_dependency_check_rejects_reciprocal_import_even_inside_function(reciprocal):
    graph = import_graph({
        "agile_eval.report_skill_usage": "from agile_eval.adapters import copilot_trace",
        "agile_eval.adapters.copilot_trace": f"def delayed():\n    {reciprocal}\n",
    })
    with pytest.raises(AssertionError, match="import cycle:"):
        assert_acyclic(graph)


def isolated(script, tmp_path, *args):
    return subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script, str(SOURCE), *args],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


@pytest.mark.parametrize("order", list(permutations(
    ("report_skill_usage", "adapters.copilot_trace", "metrics.local_model"),
)))
def test_clean_process_import_order_preserves_contract_identity_without_optional_dependencies(tmp_path, order):
    script = """
import importlib
import os
import sys
sys.path.insert(0, sys.argv[1])
before_path, before_env = list(sys.path), dict(os.environ)
for name in sys.argv[2:]:
    importlib.import_module('agile_eval.' + name)
from agile_eval import report_skill_usage
from agile_eval.adapters import copilot_trace
assert report_skill_usage.Trace is copilot_trace.Trace
assert report_skill_usage.parse_log is copilot_trace.parse_log
assert report_skill_usage.verify_schema is copilot_trace.verify_schema
assert not any(name.split('.')[0] in {'deepeval', 'copilot', 'yaml'} for name in sys.modules)
assert sys.path == before_path
assert dict(os.environ) == dict(
    before_env, DEEPEVAL_TELEMETRY_OPT_OUT='1',
    DEEPEVAL_DISABLE_PROGRESS_BAR=before_env.get('DEEPEVAL_DISABLE_PROGRESS_BAR', '1'),
)
"""
    result = isolated(script, tmp_path, *order)
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
