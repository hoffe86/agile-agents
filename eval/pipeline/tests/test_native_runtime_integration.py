"""Offline entrypoint/timeout contracts, NOT evidence of native enforcement."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import native_runtime_integration as native


class NativeEntrypointTests(unittest.TestCase):
    def test_import_does_not_import_sdk_or_create_event_loop(self):
        code = (
            "import builtins, runpy\n"
            "original = builtins.__import__\n"
            "def guarded(name, *args, **kwargs):\n"
            "    if name.split('.')[0] in ('copilot', 'asyncio'):\n"
            "        raise AssertionError('runtime import during discovery')\n"
            "    return original(name, *args, **kwargs)\n"
            "builtins.__import__ = guarded\n"
            f"runpy.run_path({str(Path(native.__file__).resolve())!r})\n"
        )
        result = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_execution_requires_both_explicit_gate_and_runtime_path(self):
        with patch.object(native, "check_prerequisites") as prerequisites:
            with self.assertRaises(SystemExit) as error:
                native.main(["--runtime-path", "/not/executed"])
        self.assertEqual(error.exception.code, 2)
        prerequisites.assert_not_called()

    def test_missing_runtime_path_fails_before_prerequisites(self):
        with patch.object(native, "check_prerequisites") as prerequisites:
            with self.assertRaises(SystemExit) as error:
                native.main(["--run-native"])
        self.assertEqual(error.exception.code, 2)
        prerequisites.assert_not_called()

    def test_explicit_execution_on_non_linux_fails_without_sdk_lookup(self):
        with patch.object(native.sys, "platform", "win32"):
            with patch.object(native.metadata, "distribution") as distribution:
                with self.assertRaisesRegex(native.CheckFailure, "hosted_linux_required"):
                    native.check_prerequisites(Path("/not/executed"))
        distribution.assert_not_called()

    def test_missing_sdk_is_failure_not_skip(self):
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution",
                              side_effect=native.metadata.PackageNotFoundError):
                with self.assertRaisesRegex(native.CheckFailure, "sdk_not_installed"):
                    native.check_prerequisites(Path("/not/executed"))

    def test_wrong_sdk_version_fails_before_reading_publisher_pin(self):
        distribution = Mock(version="1.0.22")
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution", return_value=distribution):
                with self.assertRaisesRegex(native.CheckFailure, "sdk_version_mismatch"):
                    native.check_prerequisites(Path("/not/executed"))
        distribution.locate_file.assert_not_called()

    def test_publisher_pin_mismatch_fails_without_starting_runtime(self):
        distribution = Mock(version=native.SDK_VERSION)
        distribution.locate_file.return_value.read_text.return_value = (
            'CLI_VERSION: str | None = "1.0.100"\n'
        )
        with patch.object(native.sys, "platform", "linux"):
            with patch.object(native.metadata, "distribution", return_value=distribution):
                with self.assertRaisesRegex(native.CheckFailure, "publisher_cli_pin_mismatch"):
                    native.check_prerequisites(Path("/not/executed"))

    def test_runtime_environment_does_not_inherit_credentials_or_canary(self):
        with patch.dict(native.os.environ, {"GITHUB_TOKEN": "synthetic-not-a-token",
                                           native.CANARY_NAME: "synthetic-canary"}):
            env = native.isolated_environment(Path("/synthetic"))
        self.assertNotIn("GITHUB_TOKEN", env)
        self.assertNotIn(native.CANARY_NAME, env)
        self.assertEqual(env["COPILOT_SKIP_CLI_DOWNLOAD"], "1")
        self.assertEqual(env["HOME"], "/synthetic/home".replace("/", native.os.sep))

    def test_only_explicit_native_denial_counts_as_denial(self):
        native.require_denial({"resultType": "denied"})
        native.require_denial(SimpleNamespace(result_type="rejected"))
        with self.assertRaisesRegex(native.CheckFailure, "explicit_native_denial_required"):
            native.require_denial({"resultType": "failure", "error": "missing auth"})
        with self.assertRaises(native.CheckFailure):
            native.require_denial({"resultType": "success"})
        with self.assertRaises(native.CheckFailure):
            native.require_denial({})

    def test_outer_timeout_kills_only_owned_group_and_returns_failure(self):
        process = Mock(pid=12345)
        process.communicate.side_effect = [
            subprocess.TimeoutExpired("synthetic", native.OUTER_TIMEOUT), ("", None),
        ]
        with patch.object(native.subprocess, "Popen", return_value=process) as launch:
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["check"], "outer_timeout")
        kill.assert_called_once_with(process)
        self.assertTrue(launch.call_args.kwargs["start_new_session"])
        self.assertEqual(process.communicate.call_args_list[0].kwargs,
                         {"timeout": native.OUTER_TIMEOUT})
        self.assertEqual(process.communicate.call_args_list[1].kwargs, {"timeout": 5})

    def test_success_requires_every_native_stage_and_child_zero_exit(self):
        report = {"status": "pass", "check": "bounded_cleanup",
                  "sdk": native.SDK_VERSION, "publisher_cli": native.CLI_VERSION,
                  "runtime": native.CLI_VERSION, "protocol": 1, "passed": list(native.CHECKS)}
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps(report), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group") as kill:
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 0)
        kill.assert_called_once_with(process)

    def test_zero_exit_with_incomplete_checks_is_not_green(self):
        process = Mock(pid=12345, returncode=0)
        process.communicate.return_value = (json.dumps({
            "status": "pass", "check": "runtime_identity", "passed": ["runtime_identity"],
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)

    def test_nonzero_exit_overrides_a_complete_success_report(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps({
            "status": "pass", "check": "bounded_cleanup", "sdk": native.SDK_VERSION,
            "publisher_cli": native.CLI_VERSION, "runtime": native.CLI_VERSION,
            "protocol": 1, "passed": list(native.CHECKS),
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()):
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)

    def test_native_failure_is_nonzero_with_only_allowlisted_diagnostics(self):
        process = Mock(pid=12345, returncode=1)
        process.communicate.return_value = (json.dumps({
            "status": "fail", "check": "session_startup",
            "reason": "authentication_required", "passed": ["runtime_identity"],
            "error": "synthetic-sensitive-runtime-diagnostic",
        }), None)
        with patch.object(native.subprocess, "Popen", return_value=process):
            with patch.object(native, "kill_owned_group"):
                with redirect_stdout(io.StringIO()) as output:
                    status = native.run_bounded(Path("/synthetic/runtime"))
        self.assertEqual(status, 1)
        self.assertNotIn("sensitive", output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["reason"], "authentication_required")

    def test_malformed_output_is_not_relayed(self):
        self.assertEqual(native.safe_failure_report("synthetic-sensitive-diagnostic"), {
            "status": "fail", "check": "invalid_child_report",
        })


if __name__ == "__main__":
    unittest.main()
