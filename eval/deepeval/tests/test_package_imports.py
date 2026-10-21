"""Canonical package identity and executable compatibility, without live evaluation."""

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


def test_canonical_imports_share_types_exceptions_and_have_no_module_aliases(deepeval_module):
    from agile_eval import authorization, grading_contract, native_controller, prepare_inputs
    from agile_eval.metrics import acceptance

    assert native_controller.InvalidRecord is authorization.InvalidRecord
    assert native_controller.JobAuthorization is authorization.JobAuthorization
    assert acceptance.JudgeResult is grading_contract.JudgeResult
    assert acceptance.Verdict is grading_contract.Verdict
    assert importlib.import_module("agile_eval.prepare_inputs").SetupError is prepare_inputs.SetupError
    assert importlib.import_module("agile_eval.authorization").InvalidRecord is authorization.InvalidRecord
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
    for name in ("sitecustomize", "authorization", "grading", "provenance",
                 "native_controller", "run_eval", "prepare_inputs"):
        (tmp_path / f"{name}.py").write_text(poison, encoding="utf-8")
    script = """
import importlib.util
from pathlib import Path
import sys
source = Path(sys.argv[1])
assert Path.cwd().as_posix() not in sys.path
sys.path.insert(0, str(source))
before = list(sys.path)
from agile_eval import authorization, grading, native_controller, provenance, run_eval, score_workspace
from agile_eval import grading_contract
from agile_eval.adapters import copilot_trace
assert sys.path == before
assert importlib.util.find_spec('deepeval') is None
assert importlib.util.find_spec('yaml') is None
assert not any(n.split('.')[0] in {'yaml', 'deepeval', 'copilot', 'sitecustomize'} for n in sys.modules)
assert 'agile_eval.prepare_inputs' not in sys.modules
assert native_controller.InvalidRecord is authorization.InvalidRecord
assert grading_contract.parse_result('1. PASS - ok\\nVERDICT: RESOLVED', 1).verdict is grading_contract.Verdict.RESOLVED
assert provenance.ROOT == run_eval.ROOT == source.parent.parent
"""
    proc = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script, str(SOURCE)],
        cwd=tmp_path, env=dict(os.environ, PYTHONPATH=str(tmp_path)),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not marker.exists()


@pytest.mark.parametrize("entry", [
    "eval/authorization.py", "eval/grading.py", "eval/provenance.py",
    "eval/pipeline/run_eval.py", "eval/pipeline/shell_judge.py",
    "eval/deepeval/score_workspace.py", "eval/deepeval/report_skill_usage.py",
    "eval/pipeline/custom-eval/prepare_inputs.py",
])
def test_existing_python_entrypoints_still_offer_help_from_unrelated_cwd(entry, tmp_path):
    # Preparation intentionally needs the selected interpreter's PyYAML. Its
    # historical direct entrypoint does not promise -S dependency bootstrapping.
    proc = subprocess.run(
        [sys.executable, "-B", str(ROOT / entry), "--help"], cwd=tmp_path,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "usage:" in proc.stdout


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
