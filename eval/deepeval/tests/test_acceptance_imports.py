"""Native metrics require the real dependency; held CLI preflight does not."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "python"


@pytest.mark.parametrize("files,error", [
    ({}, None),
    ({"__init__.py": ""}, "No module named 'deepeval.metrics'"),
    ({"__init__.py": "", "metrics.py": "import missing_metric_dependency\n"},
     "No module named 'missing_metric_dependency'"),
    ({"__init__.py": "import missing_root_dependency\n"}, "No module named 'missing_root_dependency'"),
    ({"__init__.py": "", "metrics.py": ""}, "cannot import name 'BaseMetric'"),
    ({"metrics.py": ""}, "cannot import name 'BaseMetric'"),
    ({"__init__.py": "", "metrics.py": "raise ImportError('incompatible dependency')\n"},
     "incompatible dependency"),
    ({"__init__.py": "", "metrics.py": "raise RuntimeError('broken initialization')\n"},
     "broken initialization"),
    ({"__init__.py": "raise ModuleNotFoundError('broken root', name='deepeval')\n"}, "broken root"),
])
def test_missing_or_broken_deepeval_is_actionable_without_fallback(tmp_path, files, error):
    for name, content in files.items():
        path = tmp_path / "deepeval" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
    script = """
import sys
sys.path[:0] = sys.argv[1:]
def deny(event, args):
    if event.startswith(('socket.connect', 'socket.getaddrinfo', 'subprocess.')):
        raise AssertionError(event)
sys.addaudithook(deny)
from agile_eval.metrics.acceptance import AcceptanceMetric
raise AssertionError('must not substitute an object base')
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(tmp_path), str(PACKAGE_ROOT)],
        cwd=tmp_path, env={"SystemRoot": os.environ.get("SystemRoot", ""),
                          "DEEPEVAL_TELEMETRY_OPT_OUT": "1"},
        text=True, capture_output=True, timeout=30,
    )
    assert proc.returncode != 0
    assert "Native acceptance metrics require DeepEval 4.1.8" in proc.stderr
    assert "No fallback backend" in proc.stderr
    if error:
        assert error in proc.stderr


def test_pure_grading_remains_importable_without_site_or_deepeval(tmp_path):
    script = """
import sys
sys.path.insert(0, sys.argv[1])
from agile_eval.grading_contract import parse_result, Verdict
assert parse_result('1. PASS - ok\\nVERDICT: RESOLVED', 1).verdict is Verdict.RESOLVED
assert not any(name.startswith(('deepeval', 'copilot')) for name in sys.modules)
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(PACKAGE_ROOT)],
        cwd=tmp_path, text=True, capture_output=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
