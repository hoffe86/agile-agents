"""Canonical offline package identity and removal of the legacy execution surface."""

import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "eval/python"
PACKAGE = SOURCE / "agile_eval"


def test_canonical_imports_share_trace_types_and_have_no_module_aliases(deepeval_module):
    from agile_eval import report_skill_usage
    from agile_eval.adapters import copilot_trace

    assert report_skill_usage.Trace is copilot_trace.Trace
    assert report_skill_usage.parse_log is copilot_trace.parse_log
    assert not Path(deepeval_module.__file__).resolve().is_relative_to(SOURCE)

    # Discover the real package, rather than maintaining a second source inventory.
    # Every source file has exactly its canonical name in the interpreter cache.
    for source in sorted(PACKAGE.rglob("*.py")):
        parts = source.relative_to(SOURCE).with_suffix("").parts
        name = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        module = importlib.import_module(name)
        assert Path(module.__file__).resolve() == source.resolve()
        identities = [
            key for key, loaded in tuple(sys.modules.items())
            if getattr(loaded, "__file__", None)
            and Path(loaded.__file__).resolve() == source.resolve()
        ]
        assert identities == [name], (source, identities)


def test_isolated_library_imports_ignore_ambient_modules_and_do_not_expose_dependencies(tmp_path):
    marker = tmp_path / "ambient-imported"
    poison = f"from pathlib import Path\nPath({str(marker)!r}).touch()\nraise AssertionError('ambient')\n"
    for name in ("sitecustomize", "report_skill_usage", "copilot_trace", "local_model"):
        (tmp_path / f"{name}.py").write_text(poison, encoding="utf-8")
    script = """
import importlib.util
from pathlib import Path
import sys
source = Path(sys.argv[1])
assert Path.cwd().as_posix() not in sys.path
sys.path.insert(0, str(source))
before = list(sys.path)
from agile_eval import report_skill_usage
from agile_eval.metrics import local_model
from agile_eval.adapters import copilot_trace
assert sys.path == before
assert importlib.util.find_spec('deepeval') is None
assert importlib.util.find_spec('yaml') is None
assert not any(n.split('.')[0] in {'yaml', 'deepeval', 'copilot', 'sitecustomize'} for n in sys.modules)
assert report_skill_usage.Trace is copilot_trace.Trace
assert report_skill_usage.parse_log is copilot_trace.parse_log
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script, str(SOURCE)],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(tmp_path)),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not marker.exists()


RETIRED_ENTRIES = [
    "eval/authorization.py", "eval/grading.py", "eval/provenance.py",
    "eval/pipeline/run_eval.py", "eval/pipeline/shell_judge.py",
    "eval/deepeval/score_workspace.py",
    "eval/pipeline/custom-eval/prepare_inputs.py",
    "eval/pipeline/run-eval.ps1", "eval/pipeline/run-eval.sh",
    "eval/pipeline/score-judge.ps1", "eval/pipeline/score-judge.sh",
]


@pytest.mark.parametrize("module", [
    "authorization", "grading", "grading_contract", "provenance", "prepare_inputs",
    "run_eval", "score_workspace", "workspace_inputs", "file_io", "metrics.acceptance",
])
def test_retired_modules_cannot_be_imported(module, tmp_path):
    script = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
try:
    importlib.import_module(sys.argv[2])
except ModuleNotFoundError as exc:
    assert exc.name == sys.argv[2], exc
else:
    raise AssertionError('retired module is importable')
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", script, str(SOURCE), f"agile_eval.{module}"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("entry", RETIRED_ENTRIES)
def test_retired_entrypoints_are_absent(entry):
    assert not (ROOT / entry).exists()


@pytest.mark.parametrize("entry", [entry for entry in RETIRED_ENTRIES if entry.endswith(".py")])
def test_retired_python_entrypoints_cannot_run(entry, tmp_path):
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(ROOT / entry), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "can't open file" in proc.stderr


def test_report_entrypoint_offers_help_from_unrelated_cwd(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-B", str(ROOT / "eval/deepeval/report_skill_usage.py"), "--help"], cwd=tmp_path,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "usage:" in proc.stdout


def test_offline_model_module_exposes_no_live_provider_factory():
    from agile_eval.metrics import local_model

    assert not hasattr(local_model, "azure_openai_model")


@pytest.mark.parametrize("option", [
    "--live", "--dry-run", "--suite", "--scorer", "--pass-threshold", "--no-isolation",
])
def test_report_rejects_legacy_or_live_options_instead_of_scoring(option, tmp_path):
    output = tmp_path / "summary.json"
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", str(ROOT / "eval/deepeval/report_skill_usage.py"),
         str(ROOT / "eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl"),
         "--score", "--expect-skill", "fixture-skill-a", "--output", str(output), option],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "unrecognized arguments" in proc.stderr
    assert not output.exists()


def test_report_cli_preserves_unicode_and_literal_metacharacter_arguments(tmp_path):
    log = tmp_path / "Grüße 東京 ; & $ [literal].log"
    shutil.copyfile(ROOT / "eval/deepeval/tests/fixtures/copilot-session.jsonl", log)
    expected = """Grüße 東京 '"; & | < > $HOME `echo` * ? [literal]"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8",
         str(ROOT / "eval/deepeval/report_skill_usage.py"), str(log),
         "--expect-skill", expected], cwd=tmp_path, capture_output=True,
        text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert log.name in proc.stdout
    assert f"expected '{expected}': BYPASSED" in proc.stdout
