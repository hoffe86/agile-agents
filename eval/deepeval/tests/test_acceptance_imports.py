"""Import the acceptance contract in fresh, dependency-free child interpreters."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


METRICS_ROOT = Path(__file__).resolve().parents[1]


def import_acceptance(tmp_path, package_files=None):
    """-I -S excludes installed packages/PYTHONPATH without altering the real venv."""
    for name, source in (package_files or {}).items():
        path = tmp_path / "deepeval" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    script = """
import sys
sys.path[:0] = sys.argv[1:]
from metrics.acceptance import AcceptanceMetric, parse_verdict, Verdict
assert parse_verdict("1. PASS - ok\\nVERDICT: RESOLVED") is Verdict.RESOLVED
print(AcceptanceMetric.__bases__[0].__name__)
"""
    return subprocess.run(
        [sys.executable, "-I", "-S", "-X", "utf8", "-c", script,
         str(tmp_path), str(METRICS_ROOT)],
        cwd=tmp_path, env=dict(os.environ, DEEPEVAL_TELEMETRY_OPT_OUT="1"),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )


def test_genuinely_absent_deepeval_keeps_pure_parsing_importable(tmp_path):
    proc = import_acceptance(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "object"


def test_available_metric_base_is_used_without_fallback(tmp_path):
    proc = import_acceptance(tmp_path, {
        "__init__.py": "",
        "metrics.py": "class BaseMetric: pass\n",
    })
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "BaseMetric"


@pytest.mark.parametrize("package_files,error", [
    ({"__init__.py": ""}, "ModuleNotFoundError: No module named 'deepeval.metrics'"),
    ({"__init__.py": "", "metrics.py": "import missing_metric_dependency\n"},
     "ModuleNotFoundError: No module named 'missing_metric_dependency'"),
    ({"__init__.py": "import missing_root_dependency\n"},
     "ModuleNotFoundError: No module named 'missing_root_dependency'"),
    ({"__init__.py": "", "metrics.py": ""},
     "ImportError: cannot import name 'BaseMetric'"),
    ({"metrics.py": ""}, "ImportError: cannot import name 'BaseMetric'"),
    ({"__init__.py": "", "metrics.py": "raise ImportError('incompatible dependency')\n"},
     "ImportError: incompatible dependency"),
    ({"__init__.py": "", "metrics.py": "raise RuntimeError('broken initialization')\n"},
     "RuntimeError: broken initialization"),
    ({"__init__.py": "raise ModuleNotFoundError('broken root', name='deepeval')\n"},
     "ModuleNotFoundError: broken root"),
])
def test_installed_but_broken_deepeval_fails_loudly(tmp_path, package_files, error):
    proc = import_acceptance(tmp_path, package_files)
    assert proc.returncode != 0
    assert error in proc.stderr
    assert "object" not in proc.stdout
