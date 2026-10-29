"""Offline infrastructure tests: pip locks, real closure, CI gates, hash failures.

Run in the locked environment. The synthetic wheel contains metadata only; pip
never builds or executes generated package code, and every pip test uses no index.
"""
from __future__ import annotations

from collections import deque
import hashlib
import importlib.metadata as metadata
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.utils import canonicalize_name
import yaml


ROOT = Path(__file__).resolve().parents[3]
EVAL = ROOT / "eval/deepeval"
LOCK = EVAL / "requirements.lock.txt"


def read_lock(path=LOCK):
    """Read this repo's ordinary one-requirement-per-line pip files, not a schema."""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            entries = read_lock(path.parent / line[3:])
        else:
            text, *options = line.split(" --hash=sha256:")
            requirement = Requirement(text)
            assert options and all(re.fullmatch(r"[a-f0-9]{64}", h) for h in options), line
            assert len(options) == len(set(options)), line
            assert not requirement.url and not requirement.extras, line
            pins = list(requirement.specifier)
            assert len(pins) == 1 and pins[0].operator == "==" and "*" not in pins[0].version, line
            entries = {canonicalize_name(requirement.name): (requirement, set(options))}
        assert not result.keys() & entries.keys(), "duplicate lock requirement"
        result.update(entries)
    return result


def roots():
    return [
        Requirement(line) for line in (EVAL / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def active_requirements(lock, environment):
    return {
        name: req for name, (req, _) in lock.items()
        if not req.marker or req.marker.evaluate(dict(environment, extra=""))
    }


def verify_installed_closure(lock):
    """Check actual installed METADATA, including extras, against the active lock."""
    environment = default_environment()
    active = active_requirements(lock, environment)
    pending = deque((req, "") for req in roots())
    visited = set()
    while pending:
        requirement, extra = pending.popleft()
        if requirement.marker and not requirement.marker.evaluate(dict(environment, extra=extra)):
            continue
        name = canonicalize_name(requirement.name)
        assert name in active, f"missing transitive pin: {name}"
        dist = metadata.distribution(name)
        assert dist.version in active[name].specifier, f"installed version differs: {name}"
        assert dist.version in requirement.specifier, f"incompatible transitive pin: {requirement}"
        assert environment["python_full_version"] in SpecifierSet(
            dist.metadata.get("Requires-Python", "")
        ), f"unsupported Python: {name}"
        for context in {""} | set(requirement.extras):
            if (name, context) in visited:
                continue
            visited.add((name, context))
            pending.extend((Requirement(dep), context) for dep in dist.requires or [])
    assert {name for name, _ in visited} == set(active), "lock has unreachable packages"


class LockTests(unittest.TestCase):
    def test_exact_roots_and_shared_yaml(self):
        lock = read_lock()
        self.assertEqual(
            {canonicalize_name(req.name): str(req.specifier) for req in roots()},
            {"deepeval": "==4.1.8", "pytest": "==9.1.1", "pyyaml": "==6.0.3"},
        )
        for req in roots():
            self.assertEqual(lock[canonicalize_name(req.name)][0].specifier, req.specifier)
        self.assertEqual(set(read_lock(EVAL / "requirements-yaml.lock.txt")), {"pyyaml"})
        self.assertIn("-r requirements-yaml.lock.txt", LOCK.read_text())

    def test_platform_markers_select_windows_only_colorama(self):
        lock = read_lock()
        for version in ("3.11", "3.12"):
            for platform, system in (("win32", "Windows"), ("linux", "Linux")):
                with self.subTest(python=version, platform=platform):
                    env = dict(default_environment(), python_version=version,
                               python_full_version=version + ".0",
                               sys_platform=platform, platform_system=system)
                    active = active_requirements(lock, env)
                    self.assertEqual("colorama" in active, platform == "win32")
                    self.assertEqual(set(active), set(lock) - ({"colorama"} if platform == "linux" else set()))

    def test_real_installed_transitive_closure_is_complete_and_consistent(self):
        verify_installed_closure(read_lock())

    def test_missing_transitive_pin_is_detected(self):
        lock = read_lock()
        del lock["idna"]
        with self.assertRaisesRegex(AssertionError, "missing transitive pin: idna"):
            verify_installed_closure(lock)

    def test_incompatible_transitive_pin_is_detected(self):
        lock = read_lock()
        lock["idna"] = (Requirement("idna==0.0.0"), lock["idna"][1])
        with self.assertRaisesRegex(AssertionError, "installed version differs: idna"):
            verify_installed_closure(lock)


class HashEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eval-pip-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.wheel = self.root / "offline_hash_fixture-1.0-py3-none-any.whl"
        prefix = "offline_hash_fixture-1.0.dist-info/"
        with zipfile.ZipFile(self.wheel, "w") as archive:
            for name, content in {
                "METADATA": "Metadata-Version: 2.1\nName: offline-hash-fixture\nVersion: 1.0\n",
                "WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                "RECORD": "",
            }.items():
                archive.writestr(zipfile.ZipInfo(prefix + name, (2020, 1, 1, 0, 0, 0)), content)
        self.digest = hashlib.sha256(self.wheel.read_bytes()).hexdigest()

    def install(self, *, hashed=True):
        requirement = self.root / "requirements.txt"
        requirement.write_text(
            "offline-hash-fixture==1.0"
            + (f" --hash=sha256:{self.digest}" if hashed else "") + "\n",
            encoding="utf-8",
        )
        return subprocess.run(
            [sys.executable, "-m", "pip", "--isolated", "--disable-pip-version-check",
             "install", "--no-index", "--no-cache-dir", "--find-links", str(self.root),
             "--only-binary=:all:", "--require-hashes", "--ignore-installed",
             "--no-deps", "--target", str(self.root / "installed"), "-r", str(requirement)],
            capture_output=True, text=True, timeout=60,
        )

    def test_correct_hash_installs_metadata_only_wheel(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.root / "installed/offline_hash_fixture-1.0.dist-info/METADATA").is_file())

    def test_tampered_artifact_is_rejected(self):
        with self.wheel.open("ab") as wheel:
            wheel.write(b"tampered")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DO NOT MATCH THE HASHES", result.stderr)

    def test_missing_hash_is_rejected(self):
        result = self.install(hashed=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Hashes are required", result.stderr)

    def test_missing_artifact_is_rejected_without_resolution_fallback(self):
        self.wheel.unlink()
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No matching distribution found", result.stderr)


class RequiredImportTests(unittest.TestCase):
    def test_real_deepeval_contract_gate(self):
        result = subprocess.run(
            [sys.executable, str(EVAL / "check_environment.py")],
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ, DEEPEVAL_TELEMETRY_OPT_OUT="1"),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("real import and offline metric OK", result.stdout)

    def test_absent_dependency_fails_required_gate(self):
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(EVAL / "check_environment.py")],
            capture_output=True, text=True, timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No module named 'deepeval'", result.stderr)

    def test_required_fixture_raises_instead_of_skipping_absent_or_broken_import(self):
        spec = importlib.util.spec_from_file_location("eval_conftest", EVAL / "tests/conftest.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for error in (ModuleNotFoundError("missing deepeval"), ImportError("broken dependency")):
            with self.subTest(error=error), mock.patch.dict(os.environ, EVAL_REQUIRE_DEEPEVAL="1"):
                with mock.patch.object(module.importlib, "import_module", side_effect=error):
                    with self.assertRaises(type(error)):
                        module.deepeval_module.__wrapped__()


class WorkflowTests(unittest.TestCase):
    def test_surviving_workflow_suites_run_separately_on_both_operating_systems(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/eval-skills.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["runtime-contracts"]
        self.assertEqual(job["strategy"]["matrix"]["os"], ["ubuntu-latest", "windows-latest"])
        self.assertEqual(job["runs-on"], "${{ matrix.os }}")
        self.assertNotIn("if", job)
        steps = job["steps"]
        for module in ("test_dependency_environment.py", "test_eval_pipeline_workflow.py"):
            with self.subTest(module=module):
                command = f"python -m unittest discover -s eval/pipeline/tests -p {module} -v"
                matches = [step for step in steps if step.get("run") == command]
                self.assertEqual(len(matches), 1)
                step = matches[0]
                self.assertNotIn("if", step)
                self.assertFalse(step.get("continue-on-error", False))

    def test_both_native_lanes_use_clean_hash_installs_and_required_gate(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/eval-skills.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["runtime-contracts"]
        self.assertEqual(job["strategy"]["matrix"]["os"], ["ubuntu-latest", "windows-latest"])
        self.assertEqual(job["env"]["EVAL_REQUIRE_DEEPEVAL"], "1")
        self.assertEqual(job["env"]["DEEPEVAL_TELEMETRY_OPT_OUT"], "1")
        steps = job["steps"]
        setup = next(s for s in steps if s.get("uses", "").startswith("actions/setup-python@"))
        self.assertEqual(setup["with"]["python-version"], "3.12")
        runs = [s["run"] for s in steps if "run" in s]
        create = next(i for i, r in enumerate(runs) if "python -m venv" in r)
        download = next(i for i, r in enumerate(runs) if "pip --isolated download" in r)
        install = next(i for i, r in enumerate(runs) if "pip --isolated install" in r)
        check = runs.index("python -m pip check")
        gate = runs.index("python eval/deepeval/check_environment.py")
        tests = next(i for i, r in enumerate(runs) if "python -m pytest" in r)
        self.assertTrue(create < download < install < check < gate < tests)
        for i in (download, install):
            self.assertIn("--require-hashes", runs[i])
            self.assertIn("--only-binary=:all:", runs[i])
            self.assertIn("eval/deepeval/requirements.lock.txt", runs[i])
            self.assertNotIn("--no-deps", runs[i])  # pip must validate closure too
        self.assertIn("--no-index", runs[install])
        self.assertIn("--find-links", runs[install])
        for run in runs:
            self.assertNotIn("requirements.txt", run)
            self.assertNotIn("--upgrade", run)
            self.assertNotIn("||", run)
        self.assertTrue(all(not s.get("continue-on-error", False) for s in steps))

    def test_lightweight_lane_reuses_yaml_lock_only(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/eval-skills.yml").read_text(encoding="utf-8"))
        runs = [s["run"] for s in workflow["jobs"]["skill-quality"]["steps"] if "run" in s]
        provision = [r for r in runs if "pip " in r]
        self.assertEqual(len(provision), 2)
        for run in provision:
            self.assertIn("requirements-yaml.lock.txt", run)
            self.assertIn("--require-hashes", run)
            self.assertIn("--only-binary=:all:", run)
        self.assertIn("--no-index", provision[1])
        self.assertIn("--force-reinstall", provision[1])  # do not trust a runner's preinstalled copy


if __name__ == "__main__":
    unittest.main()
