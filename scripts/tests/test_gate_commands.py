"""Real runner subprocess contracts; absent shell/parser dependencies are explicit skips."""

import csv
import http.server
import json
import os
from pathlib import Path
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request


ROOT = Path(__file__).resolve().parents[2]
RUNNERS = ROOT / "plugins/agile-agents-core/skills/test-bar-gate/scripts"
FIXTURE = Path(__file__).parent / "fixtures/gate_child.py"
CHECKS = ("lint", "typecheck", "unit_test", "integration_test", "coverage", "mutation")


def ps_yaml_available():
    if not shutil.which("pwsh"):
        return False
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command",
         "if (Get-Command ConvertFrom-Yaml -ErrorAction SilentlyContinue) { exit 0 }; exit 1"],
        capture_output=True, timeout=20,
    )
    return result.returncode == 0


def process_alive(pid):
    if os.name == "nt":
        # os.kill(pid, 0) calls TerminateProcess on Windows. tasklist is a
        # read-only query; CSV avoids localized column headings/status text.
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        return any(len(row) > 1 and row[1] == str(pid)
                   for row in csv.reader(result.stdout.splitlines()))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=5).stdout.strip()
    return bool(state) and not state.startswith("Z")


def assert_process_stopped(case, path, output="", timeout=3):
    case.assertTrue(path.exists(), output)
    pid = int(path.read_text())
    deadline = time.monotonic() + timeout
    while process_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    case.assertFalse(process_alive(pid), f"leaked process {pid}\n{output}")


class ProcessObserverTests(unittest.TestCase):
    def test_windows_query_is_read_only_and_distinguishes_absent_process(self):
        with patch.object(os, "name", "nt"), patch.object(
                os, "kill", side_effect=AssertionError("observer must not signal")), patch.object(
                subprocess, "run") as query:
            query.return_value.stdout = '"python.exe","123","Console","1","12,345 K"\n'
            self.assertTrue(process_alive(123))
            query.assert_called_once_with(
                ["tasklist", "/FI", "PID eq 123", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5, check=True)
            query.return_value.stdout = "INFO: No tasks match the specified criteria.\n"
            self.assertFalse(process_alive(123))
            query.side_effect = subprocess.CalledProcessError(1, ["tasklist"])
            with self.assertRaises(subprocess.CalledProcessError):
                process_alive(123)

    def test_observing_live_fixture_neither_kills_it_nor_passes_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "live.pid"
            process = subprocess.Popen(
                [sys.executable, str(FIXTURE), "wait", str(pid_path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 5
                while not pid_path.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pid_path.exists())
                self.assertTrue(process_alive(process.pid))
                self.assertIsNone(process.poll())
                with self.assertRaisesRegex(AssertionError, f"leaked process {process.pid}"):
                    assert_process_stopped(self, pid_path, timeout=0.1)
                self.assertTrue(process_alive(process.pid))
                self.assertIsNone(process.poll())
            finally:
                process.kill()
                process.wait(timeout=5)
            assert_process_stopped(self, pid_path)


class GateCases:
    shell = ""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gate contract ")
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.profile = {"quality_gates": {"test_bar": {
            check: {"enabled": False} for check in CHECKS}}}
        self.gate = self.profile["quality_gates"]["test_bar"]

    def command(self, *args):
        return [sys.executable, str(FIXTURE), *args]

    def prepare(self, status, detail, extra=()):
        profile_path = self.cwd / "profile.yaml"
        profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        if self.shell == "pwsh":
            cmd = ["pwsh", "-NoProfile", "-File", str(RUNNERS / "run-gate.ps1"),
                   "-ProfilePath", str(profile_path)]
            if status is not None:
                cmd += ["-SmokeStatus", status, "-SmokeDetail", detail]
        else:
            cmd = [os.environ.get("RUNTIME_GATE_BASH", "bash"), str(RUNNERS / "run-gate.sh"),
                   "--profile", str(profile_path)]
            if status is not None:
                cmd += ["--smoke-status", status, "--smoke-detail", detail]
        env = os.environ.copy()
        env.pop("COPILOT_EVENT_LOG", None)  # Test evidence never reaches the parent run log.
        return cmd + list(extra), env

    def invoke(self, *, status="not_applicable", detail="Inspected library; no entry point",
               extra=(), timeout=20):
        cmd, env = self.prepare(status, detail, extra)
        result = subprocess.run(cmd, cwd=self.cwd, env=env,
                                capture_output=True, text=True, timeout=timeout)
        self.output = result.stdout + result.stderr
        self.events = []
        for line in result.stdout.splitlines():
            if line.startswith("{"):
                event = json.loads(line)
                if event.get("event_type") == "gate_check":
                    self.events.append(event)
        return result.returncode

    def event(self, check):
        return next(e for e in self.events if e["check"] == check)

    def assert_no_success_summary(self):
        self.assertFalse(any(e["check"] == "summary" and e["outcome"] == "success"
                             for e in self.events), self.output)

    def smoke(self, mode="serve", timeout=3):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.pid_file = self.cwd / "smoke.pid"
        self.profile["testing"] = {"smoke": {
            "command": self.command(mode, str(port), str(self.pid_file)),
            "url": f"http://127.0.0.1:{port}/health",
            "timeout_s": timeout,
        }}
        self.addCleanup(self.cleanup_pids)

    def cleanup_pids(self):
        # Assertion failures must not leak fixture processes either.
        for path in (self.pid_file, self.pid_file.with_suffix(".child")):
            if path.exists():
                pid = int(path.read_text())
                if process_alive(pid):
                    os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))

    def assert_stopped(self, path):
        assert_process_stopped(self, path, self.output)

    def test_explicit_argv_runs_once_without_palette_or_stack(self):
        self.profile["tech_stack"] = {"primary_languages": ["unknown"],
                                      "lint_format_tools": ["ruff", "dotnet"]}
        self.gate["lint"] = {"command": self.command("check", "0", "two words", "", 'a"b', "c\\d")}
        self.assertEqual(self.invoke(), 0, self.output)
        self.assertIn('["0", "two words", "", "a\\"b", "c\\\\d"]', self.output)
        self.assertEqual(sum(e["check"] == "lint" for e in self.events), 1)
        self.assertEqual(self.event("summary")["outcome"], "success")
        self.assertIsInstance(self.event("lint")["duration_ms"], int)
        self.assertNotIn("stack", self.event("lint"))
        self.assertNotIn("stack", self.event("summary"))

    def test_plain_string_command_uses_whitespace_separated_argv(self):
        self.gate["lint"] = {"command": f"{sys.executable} -V"}
        self.assertEqual(self.invoke(), 0, self.output)
        self.assertEqual(self.event("lint")["outcome"], "success")

    def test_removed_skill_root_flag_is_rejected(self):
        flag = "-SkillRoot" if self.shell == "pwsh" else "--skill-root"
        self.assertNotEqual(self.invoke(extra=(flag, "absent")), 0, self.output)
        self.assert_no_success_summary()

    def test_removed_stacks_setting_is_rejected(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                self.gate.update(stacks=[], enabled=enabled)
                self.assertEqual(self.invoke(), 2, self.output)
                self.assertIn("stacks is unsupported", self.output)
                self.assert_no_success_summary()

    def test_enabled_missing_command_is_configuration_gap(self):
        self.gate["lint"] = {"enabled": True}
        self.assertEqual(self.invoke(), 2, self.output)
        self.assertEqual(self.event("lint")["reason"], "configuration_gap")
        self.assertIn("quality_gates.test_bar.lint.command", self.output)
        self.assert_no_success_summary()

    def test_unknown_language_does_not_skip_default_required_checks(self):
        self.profile = {"tech_stack": {"primary_languages": ["unknown"]}}
        self.assertEqual(self.invoke(), 2, self.output)
        self.assertEqual(self.event("lint")["reason"], "configuration_gap")
        self.assert_no_success_summary()

    def test_opt_in_required_command_cannot_silently_disappear(self):
        self.gate["coverage"] = {"enabled": True, "command": ""}
        self.assertEqual(self.invoke(), 2, self.output)
        self.assertEqual(self.event("coverage")["reason"], "configuration_gap")

    def test_disabled_checks_are_visible_and_never_execute(self):
        self.gate["lint"]["command"] = ["missing-must-not-run"]
        self.assertEqual(self.invoke(), 0, self.output)
        self.assertEqual(self.event("lint")["reason"], "disabled_by_profile")
        self.assertEqual(self.event("summary")["outcome"], "skipped")

    def test_master_disable_needs_neither_palette_nor_smoke(self):
        self.profile = {"quality_gates": {"test_bar": {"enabled": False}}}
        self.assertEqual(self.invoke(status=None), 0, self.output)
        self.assertEqual(self.event("resolve")["reason"], "disabled_by_profile")
        self.assert_no_success_summary()

    def test_invalid_gate_switches_emit_configuration_evidence(self):
        for key in ("enabled", "fail_fast"):
            with self.subTest(key=key):
                self.gate[key] = "false"
                try:
                    self.assertEqual(self.invoke(), 2, self.output)
                    self.assertEqual(self.event("resolve")["reason"], "configuration_gap")
                    self.assertIn(f"quality_gates.test_bar.{key}", self.output)
                    self.assert_no_success_summary()
                finally:
                    del self.gate[key]

    def test_default_opt_in_checks_are_visible_skips(self):
        for check in ("integration_test", "coverage", "mutation"):
            del self.gate[check]
        self.assertEqual(self.invoke(), 0, self.output)
        for check in ("integration_test", "coverage", "mutation"):
            self.assertEqual(self.event(check)["reason"], "disabled_by_default")

    def test_child_failure_preserves_exit_stderr_and_fail_fast(self):
        self.gate["lint"] = {"command": self.command("check", "7")}
        self.gate["unit_test"] = {"command": ["must-not-run"]}
        self.assertEqual(self.invoke(), 1, self.output)
        self.assertEqual(self.event("lint")["exit_code"], 7)
        self.assertIn("gate diagnostic", self.event("lint")["stderr_tail"])
        self.assertFalse(any(e["check"] == "unit_test" for e in self.events))
        self.assert_no_success_summary()

    def test_aggregate_reports_both_execution_failure_and_configuration_gap(self):
        self.gate.update(fail_fast=False, lint={"command": self.command("check", "7")},
                         unit_test={"enabled": True})
        self.assertEqual(self.invoke(), 2, self.output)
        self.assertEqual(self.event("lint")["exit_code"], 7)
        self.assertEqual(self.event("unit_test")["reason"], "configuration_gap")
        self.assert_no_success_summary()

    def test_missing_tool_is_execution_failure_not_skip(self):
        self.gate["lint"] = {"command": ["gate-tool-does-not-exist"]}
        self.assertEqual(self.invoke(), 1, self.output)
        self.assertEqual(self.event("lint")["exit_code"], 127)
        self.assertEqual(self.event("lint")["reason"], "command_not_found")

    def test_malformed_commands_fail_configuration(self):
        for value in (42, True, {"bad": "command"}, [sys.executable, None],
                      [sys.executable, 3], [sys.executable, "line\nbreak"]):
            with self.subTest(value=value):
                self.gate["lint"] = {"command": value}
                self.assertEqual(self.invoke(), 2, self.output)
                self.assert_no_success_summary()

    def test_string_false_cannot_disable_a_required_check(self):
        for value in ("false", "", "null", 0):
            with self.subTest(value=value):
                self.gate["lint"] = {"enabled": value}
                self.assertEqual(self.invoke(), 2, self.output)
                self.assert_no_success_summary()

    def test_missing_smoke_setup_is_unverified(self):
        self.assertEqual(self.invoke(status=None), 2, self.output)
        self.assertEqual(self.event("smoke")["reason"], "needs_discovery")
        self.assert_no_success_summary()

    def test_undetermined_smoke_is_unverified(self):
        self.assertEqual(self.invoke(status="undetermined", detail="README and CI lack run setup"),
                         2, self.output)
        self.assertEqual(self.event("smoke")["reason"], "undetermined")
        self.assert_no_success_summary()

    def test_not_applicable_requires_evidence(self):
        self.assertEqual(self.invoke(detail=""), 2, self.output)
        self.assertEqual(self.event("smoke")["reason"], "configuration_gap")

    def test_not_applicable_cannot_bypass_configured_smoke(self):
        self.smoke()
        self.assertEqual(self.invoke(), 2, self.output)
        self.assertEqual(self.event("smoke")["reason"], "configuration_gap")
        self.assertFalse(self.pid_file.exists())

    def test_smoke_success_cleans_up_process_tree(self):
        self.smoke("tree")
        self.assertEqual(self.invoke(status=None), 0, self.output)
        self.assertEqual(self.event("smoke")["outcome"], "success")
        self.assert_stopped(self.pid_file)
        self.assert_stopped(self.pid_file.with_suffix(".child"))

    def test_smoke_timeout_is_bounded_and_cleans_up(self):
        self.smoke(timeout=1)
        self.profile["testing"]["smoke"]["command"] = self.command("wait", str(self.pid_file))
        started = time.monotonic()
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("no response", self.event("smoke")["reason"])
        self.assertIn("waiting diagnostic", self.event("smoke")["stderr_tail"])
        self.assert_stopped(self.pid_file)

    def test_smoke_early_exit_preserves_startup_evidence(self):
        self.smoke()
        self.profile["testing"]["smoke"]["command"] = self.command("exit")
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertEqual(self.event("smoke")["exit_code"], 7)
        self.assertIn("process exited", self.event("smoke")["reason"])
        self.assertIn("startup diagnostic", self.event("smoke")["stderr_tail"])
        self.assert_no_success_summary()

    def test_smoke_launcher_exit_with_inherited_pipes_is_bounded_and_cleans_up(self):
        self.smoke(timeout=3)
        self.profile["testing"]["smoke"]["command"] = self.command("orphan", str(self.pid_file))
        started = time.monotonic()
        self.assertEqual(self.invoke(status=None, timeout=12), 1, self.output)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(self.event("smoke")["exit_code"], 7)
        self.assertIn("process exited", self.event("smoke")["reason"])
        self.assertIn("launcher stdout without newline", self.event("smoke")["stderr_tail"])
        self.assertIn("launcher stderr without newline", self.event("smoke")["stderr_tail"])
        self.assert_no_success_summary()
        self.assert_stopped(self.pid_file)
        self.assert_stopped(self.pid_file.with_suffix(".child"))

    def test_smoke_clean_exit_without_readiness_is_still_failure(self):
        self.smoke()
        self.profile["testing"]["smoke"]["command"] = self.command("exit", "0")
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertEqual(self.event("smoke")["outcome"], "fail")
        self.assertEqual(self.event("smoke")["exit_code"], 0)
        self.assertIn("process exited", self.event("smoke")["reason"])
        self.assert_no_success_summary()

    def test_invalid_smoke_timeout_does_not_start_process(self):
        self.smoke(timeout=0)
        self.assertEqual(self.invoke(status=None), 2, self.output)
        self.assertFalse(self.pid_file.exists())

    def test_blank_or_literal_null_smoke_timeout_is_not_a_default(self):
        self.smoke()
        for timeout in ("", "null", " ", False, -1):
            with self.subTest(timeout=timeout):
                self.profile["testing"]["smoke"]["timeout_s"] = timeout
                self.assertEqual(self.invoke(status=None), 2, self.output)
                self.assertEqual(self.event("smoke")["reason"], "configuration_gap")
                self.assertFalse(self.pid_file.exists())
                self.assert_no_success_summary()

    def test_absent_smoke_timeout_uses_default(self):
        self.smoke()
        del self.profile["testing"]["smoke"]["timeout_s"]
        self.assertEqual(self.invoke(status=None), 0, self.output)
        self.assertIn("timeout 60s", self.output)
        self.assert_stopped(self.pid_file)

    def test_missing_health_url_does_not_start_process(self):
        self.smoke()
        del self.profile["testing"]["smoke"]["url"]
        self.assertEqual(self.invoke(status=None), 2, self.output)
        self.assertFalse(self.pid_file.exists())

    def test_smoke_command_override_keeps_profile_health_url(self):
        self.smoke()
        command = " ".join(self.profile["testing"]["smoke"]["command"])
        # CLI strings split whitespace, so use a relative PID path in this test.
        command = command.replace(str(self.pid_file), "smoke.pid")
        self.profile["testing"]["smoke"]["command"] = ["must-not-run"]
        flag = "-SmokeCommand" if self.shell == "pwsh" else "--smoke-command"
        self.assertEqual(self.invoke(status=None, extra=(flag, command)), 0, self.output)
        self.assert_stopped(self.pid_file)

    def test_smoke_url_override_wins_without_command_override(self):
        self.smoke()
        url = self.profile["testing"]["smoke"]["url"]
        self.profile["testing"]["smoke"]["url"] = "http://127.0.0.1:1/health"
        flag = "-SmokeUrl" if self.shell == "pwsh" else "--smoke-url"
        self.assertEqual(self.invoke(status=None, extra=(flag, url)), 0, self.output)
        self.assert_stopped(self.pid_file)

    def test_smoke_missing_executable_is_not_a_skip(self):
        self.smoke()
        self.profile["testing"]["smoke"]["command"] = ["gate-tool-does-not-exist"]
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertEqual(self.event("smoke")["exit_code"], 127)
        self.assertEqual(self.event("smoke")["reason"], "command_not_found")
        self.assert_no_success_summary()

    def test_smoke_redirect_proves_reachability_without_following_it(self):
        self.smoke("redirect")
        self.assertEqual(self.invoke(status=None), 0, self.output)
        self.assert_stopped(self.pid_file)

    def test_smoke_server_error_cannot_pass(self):
        self.smoke("unhealthy", timeout=2)
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertEqual(self.event("smoke")["outcome"], "fail")
        self.assert_no_success_summary()
        self.assert_stopped(self.pid_file)

    def test_unresponsive_health_request_obeys_smoke_deadline(self):
        self.smoke("hang", timeout=1)
        started = time.monotonic()
        self.assertEqual(self.invoke(status=None), 1, self.output)
        self.assertLess(time.monotonic() - started, 10)
        self.assert_stopped(self.pid_file)

    @unittest.skipIf(os.name == "nt", "POSIX termination signal test")
    def test_termination_cleans_up_smoke_process_tree(self):
        self.smoke("tree", timeout=30)
        # A nonresponsive URL leaves time to interrupt after child creation.
        self.profile["testing"]["smoke"]["url"] = "http://127.0.0.1:1/health"
        cmd, env = self.prepare(None, "")
        runner = subprocess.Popen(cmd, cwd=self.cwd, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            deadline = time.monotonic() + 8
            child_path = self.pid_file.with_suffix(".child")
            while not child_path.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertTrue(child_path.exists(), "smoke child did not start")
            runner.terminate()
            stdout, stderr = runner.communicate(timeout=10)
            self.output = stdout + stderr
            self.assertNotEqual(runner.returncode, 0)
            self.assert_stopped(self.pid_file)
            self.assert_stopped(child_path)
        finally:
            if runner.poll() is None:
                runner.kill()
            runner.communicate(timeout=5)


@unittest.skipUnless(ps_yaml_available(), "PowerShell/powershell-yaml unavailable")
class PowerShellGateTests(GateCases, unittest.TestCase):
    shell = "pwsh"

    def test_private_smoke_directory_setup_failure_is_closed(self):
        self.smoke()
        url, requests = self.reachable_url()
        self.profile["testing"]["smoke"]["url"] = url
        # A regular file cannot hold a private rendezvous directory.
        blocked = self.cwd / "not-a-directory"
        blocked.write_text("do not remove", encoding="utf-8")
        _, env = self.prepare(None, "")
        quoted_blocked = str(blocked).replace("'", "''")
        quoted_runner = str(RUNNERS / "run-gate.ps1").replace("'", "''")
        quoted_profile = str(self.cwd / "profile.yaml").replace("'", "''")
        # Set the invalid temp path AFTER CoreCLR boots: .NET 6 itself needs a
        # valid temp directory on startup. Exercise the gate, not a host failure.
        cmd = ["pwsh", "-NoProfile", "-Command",
               f"$env:TMPDIR = $env:TMP = $env:TEMP = '{quoted_blocked}'; "
               f"& '{quoted_runner}' -ProfilePath '{quoted_profile}'; exit $LASTEXITCODE"]
        with patch.object(self, "prepare", return_value=(cmd, env)):
            code = self.invoke(status=None)
        self.assertEqual(code, 1, self.output)
        self.assertEqual(self.event("smoke")["outcome"], "fail")
        self.assertEqual(self.event("smoke")["reason"], "smoke_setup_failed")
        self.assertIn("Smoke setup failed", self.event("smoke")["stderr_tail"])
        self.assert_no_success_summary()
        self.assertEqual(requests, ["/health"])
        self.assertFalse(self.pid_file.exists(), "security setup must precede launch")
        self.assertEqual(blocked.read_text(), "do not remove")

    @unittest.skipUnless(os.name == "nt", "requires native Windows directory ACLs")
    def test_unprotected_smoke_directory_acl_readback_is_rejected_and_removed(self):
        self.smoke()
        url, requests = self.reachable_url()
        self.profile["testing"]["smoke"]["url"] = url
        runners, helper_pid = self.controlled_smoke_helper()
        runner_path = runners / "run-gate.ps1"
        source = runner_path.read_text(encoding="utf-8")
        readback = (
            "var actual = new DirectoryInfo(directory).GetAccessControl(AccessControlSections.Access);")
        self.assertEqual(source.count(readback), 1, "ACL readback injection must hit exactly once")
        # Create the real private directory and read its real ACL, then change
        # only the in-memory readback. Keep the verification and cleanup intact;
        # never relax the directory's on-disk permissions for this fixture.
        source = source.replace(readback, readback + """
                    File.WriteAllText("acl-directory.path", directory);
                    actual.SetAccessRuleProtection(false, false);
""")
        runner_path.write_text(source, encoding="utf-8")
        with patch(f"{__name__}.RUNNERS", runners):
            code = self.invoke(status=None)
        self.assertEqual(code, 1, self.output)
        self.assertEqual(self.event("smoke")["outcome"], "fail")
        self.assertEqual(self.event("smoke")["reason"], "smoke_setup_failed")
        self.assertIn("Private smoke directory ACL was not preserved.",
                      self.event("smoke")["stderr_tail"])
        self.assert_no_success_summary()
        self.assertEqual(requests, ["/health"], "only the independent reachability probe may run")
        self.assertFalse(helper_pid.exists(), "ACL rejection must precede helper launch")
        self.assertFalse(self.pid_file.exists(), "ACL rejection must precede command launch")
        recorded = self.cwd / "acl-directory.path"
        self.assertTrue(recorded.exists(), "fixture never reached post-creation ACL readback")
        directory = Path(recorded.read_text(encoding="utf-8"))
        self.assertTrue(directory.is_absolute(), "fixture must record the created directory")
        self.assertFalse(directory.exists(), "rejected private directory leaked")

    def test_smoke_rendezvous_is_private_before_launch_and_removed(self):
        self.smoke()
        runners, helper_pid = self.controlled_smoke_helper(before_launch=(
            "[System.IO.File]::WriteAllText('rendezvous.path.staging', $ReadyFile)\n"
            "[System.IO.File]::Move('rendezvous.path.staging', 'rendezvous.path')\n"
            "while (-not (Test-Path 'release-launch')) { Start-Sleep -Milliseconds 20 }"))
        with patch(f"{__name__}.RUNNERS", runners):
            cmd, env = self.prepare(None, "")
        runner = subprocess.Popen(cmd, cwd=self.cwd, env=env, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            path_file = self.cwd / "rendezvous.path"
            deadline = time.monotonic() + 8
            while not path_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(path_file.exists(), "helper never reached launch barrier")
            ready = Path(path_file.read_text())
            if os.name == "nt":
                quoted_path = str(ready.parent).replace("'", "''")
                acl = subprocess.run(
                    ["pwsh", "-NoProfile", "-Command",
                     f"$acl = Get-Acl -LiteralPath '{quoted_path}'; "
                     "$sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
                     "$rules = @($acl.GetAccessRules($true, $true, "
                     "[System.Security.Principal.SecurityIdentifier])); "
                     "if (-not $acl.AreAccessRulesProtected -or $rules.Count -ne 1 -or "
                     "$rules[0].IdentityReference -ne $sid -or "
                     "$rules[0].FileSystemRights -ne 'FullControl' -or "
                     "$rules[0].InheritanceFlags -ne 'ContainerInherit, ObjectInherit') { exit 1 }"],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(acl.returncode, 0, acl.stdout + acl.stderr)
            else:
                self.assertEqual(ready.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(ready.parent.stat().st_uid, os.geteuid())
            self.assertFalse(self.pid_file.exists(), "command must still be withheld")
            (self.cwd / "release-launch").touch()
            stdout, stderr = runner.communicate(timeout=12)
            self.output = stdout + stderr
            self.assertEqual(runner.returncode, 0, self.output)
            events = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
            self.assertTrue(any(e["check"] == "smoke" and e["outcome"] == "success" for e in events))
            self.assertTrue(any(e["check"] == "summary" and e["outcome"] == "success" for e in events))
            self.assertFalse(ready.parent.exists(), "private rendezvous directory leaked")
            self.assert_stopped(self.pid_file)
            assert_process_stopped(self, helper_pid, self.output)
        finally:
            if runner.poll() is None:
                runner.kill()
            runner.communicate(timeout=5)

    @unittest.skipUnless(sys.platform == "linux" and os.geteuid() == 0,
                         "requires isolated Linux root to launch two unprivileged UIDs")
    def test_other_account_cannot_forge_then_remove_launch_acknowledgment(self):
        self.smoke(timeout=3)
        removed = self.cwd / "forgery-removed"
        url, requests = self.reachable_url(wait_for=removed)
        self.profile["testing"]["smoke"].update(
            command=self.command("wait", str(self.pid_file)), url=url)
        runners, helper_pid = self.controlled_smoke_helper(before_launch=(
            "[System.IO.File]::WriteAllText('rendezvous.path.staging', $ReadyFile)\n"
            "[System.IO.File]::Move('rendezvous.path.staging', 'rendezvous.path')\n"
            "while (-not (Test-Path 'release-launch')) { Start-Sleep -Milliseconds 20 }"))
        # No account database changes: only these child processes get the numeric
        # identities. The victim and attacker are both unprivileged and distinct.
        victim_uid, attacker_uid = 41001, 41002
        os.chown(self.cwd, victim_uid, victim_uid)
        self.cwd.chmod(0o755)
        shared = self.cwd / "shared-temp"
        shared.mkdir()
        shared.chmod(0o1777)
        with patch(f"{__name__}.RUNNERS", runners):
            cmd, env = self.prepare(None, "")
        env["TMPDIR"] = str(shared)
        runner = subprocess.Popen(
            cmd, cwd=self.cwd, env=env, user=victim_uid, group=victim_uid, extra_groups=[],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        attacker = None
        try:
            path_file = self.cwd / "rendezvous.path"
            deadline = time.monotonic() + 8
            while not path_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(path_file.exists(), "helper never reached launch barrier")
            ready = Path(path_file.read_text())
            attacker = subprocess.Popen(
                [sys.executable, "-u", "-c",
                 "import json, os, pathlib, sys\n"
                 "ready = pathlib.Path(sys.argv[1])\n"
                 "probe = pathlib.Path(sys.argv[2]) / 'attacker-control'\n"
                 "probe.write_text('public temp is writable'); probe.unlink()\n"
                 "try:\n"
                 "    ready.read_text(); ready_readable = True\n"
                 "except PermissionError:\n"
                 "    ready_readable = False\n"
                 "publication = pathlib.Path(str(ready) + '.publication')\n"
                 "try:\n"
                 "    publication.write_text('forged'); publication.unlink(); staging_writable = True\n"
                 "except PermissionError:\n"
                 "    staging_writable = False\n"
                 "marker = pathlib.Path(str(ready) + '.started')\n"
                 "try:\n"
                 "    marker.write_text(str(os.getpid())); forged = True\n"
                 "except PermissionError:\n"
                 "    forged = False\n"
                 "print(json.dumps({'uid': os.geteuid(), 'forged': forged,\n"
                 "                  'ready_readable': ready_readable,\n"
                 "                  'staging_writable': staging_writable}), flush=True)\n"
                 "sys.stdin.readline()\n"
                 "if forged: marker.unlink()\n"
                 "print('removed', flush=True)\n"
                 "sys.stdin.readline()\n",
                 str(ready), str(shared)],
                cwd=self.cwd, user=attacker_uid, group=attacker_uid, extra_groups=[],
                text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # The attacker stays alive as the substituted PID. Remove its forged
            # marker only AFTER the gate reads it and polls HTTP, before returning
            # HTTP success: this exercises the complete bypass including cleanup.
            self.assertTrue(select.select([attacker.stdout], [], [], 5)[0],
                            "attacker did not report its file-access result")
            report = json.loads(attacker.stdout.readline())
            self.assertEqual(report["uid"], attacker_uid)
            deadline = time.monotonic() + 8
            while runner.poll() is None and len(requests) == 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            attacker.stdin.write("remove\n")
            attacker.stdin.flush()
            self.assertTrue(select.select([attacker.stdout], [], [], 5)[0],
                            "attacker did not acknowledge removal")
            self.assertEqual(attacker.stdout.readline().strip(), "removed")
            removed.touch()
            stdout, stderr = runner.communicate(timeout=12)
            self.output = stdout + stderr
            self.events = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
            self.assertIsNone(attacker.poll(), "substituted PID must stay alive through finalization")
            self.assertFalse(self.pid_file.exists(), "genuine command must never launch")
            assert_process_stopped(self, helper_pid, self.output)
            self.assertFalse(ready.exists(), "ready file leaked")
            self.assertFalse(Path(str(ready) + ".started").exists(), "launch marker leaked")
            # .NET may leave diagnostic pipes after the helper is killed; only
            # rendezvous paths are ours to remove, never the whole shared temp.
            self.assertEqual(list(shared.glob("gate-smoke-*")), [], "private directory leaked")
            # Report all final outcomes on pre-fix failure, not just file access.
            evidence = json.dumps({"attacker": report, "gate_exit": runner.returncode,
                                   "requests": requests, "events": self.events})
            self.assertEqual(runner.returncode, 1, evidence)
            self.assertEqual(self.event("smoke")["outcome"], "fail", evidence)
            self.assert_no_success_summary()
            self.assertFalse(report["forged"], evidence)
            self.assertFalse(report["ready_readable"], evidence)
            self.assertFalse(report["staging_writable"], evidence)
            self.assertEqual(requests, ["/health"], evidence)
            self.assertIn("command launch did not complete", self.event("smoke")["reason"])
        finally:
            if attacker is not None:
                if attacker.poll() is None:
                    attacker.kill()
                attacker.communicate(timeout=5)
            if runner.poll() is None:
                runner.kill()
            runner.communicate(timeout=5)

    def reachable_url(self, wait_for=None):
        requests = []

        class Health(http.server.BaseHTTPRequestHandler):
            def do_GET(handler):
                requests.append(handler.path)
                # The initial probe proves reachability independently of launch.
                # Later responses can wait for a controlled command exit.
                if wait_for is not None and len(requests) > 1:
                    deadline = time.monotonic() + 8
                    while not wait_for.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    if not wait_for.exists():
                        handler.send_error(503, "command exit was not observed")
                        return
                handler.send_response(204)
                handler.end_headers()

            def log_message(handler, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_port}/health"
        with urllib.request.urlopen(url, timeout=5) as response:
            self.assertEqual(response.status, 204)
        return url, requests

    def controlled_smoke_helper(self, *, before_launch="", after_exit=""):
        runners = self.cwd / "controlled-runners"
        runners.mkdir()
        shutil.copyfile(RUNNERS / "run-gate.ps1", runners / "run-gate.ps1")
        source = (RUNNERS / "start-smoke.ps1").read_text(encoding="utf-8")
        # Instrument the real ownership helper, not a replacement protocol.
        # File barriers control scheduling without assuming a slow/fast host.
        for anchor, insertion in (
            ("[System.IO.File]::WriteAllText($ReadyFile, 'ready')",
             "[System.IO.File]::WriteAllText('helper.pid', [string]$PID)\n"),
            ("$argv = @($ArgvJson | ConvertFrom-Json)", before_launch),
            ("$code = $process.ExitCode", after_exit),
        ):
            self.assertEqual(source.count(anchor), 1, anchor)
            source = source.replace(anchor, insertion + "\n" + anchor)
        (runners / "start-smoke.ps1").write_text(source, encoding="utf-8")
        helper_pid = self.cwd / "helper.pid"

        def cleanup_helper():
            if helper_pid.exists():
                pid = int(helper_pid.read_text())
                if process_alive(pid):
                    os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))

        self.addCleanup(cleanup_helper)
        return runners, helper_pid

    def test_reachable_url_cannot_pass_before_command_launch(self):
        self.smoke(timeout=1)
        url, requests = self.reachable_url()
        self.profile["testing"]["smoke"].update(
            command=self.command("wait", str(self.pid_file)), url=url)
        runners, helper_pid = self.controlled_smoke_helper(
            before_launch="while (-not (Test-Path 'release-launch')) { Start-Sleep -Milliseconds 20 }")
        started = time.monotonic()
        with patch(f"{__name__}.RUNNERS", runners):
            code = self.invoke(status=None, timeout=12)
        self.assertEqual(self.event("smoke")["outcome"], "fail", self.output)
        self.assertEqual(code, 1, self.output)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("command launch did not complete within 1s", self.event("smoke")["reason"])
        self.assertEqual(requests, ["/health"], "gate polled before command launch")
        self.assertFalse(self.pid_file.exists(), "withheld command must not execute")
        self.assert_no_success_summary()
        assert_process_stopped(self, helper_pid, self.output)

    def test_reachable_url_cannot_pass_after_command_exit_while_helper_lives(self):
        self.smoke(timeout=3)
        exited = self.cwd / "command-exited"
        url, _ = self.reachable_url(wait_for=exited)
        self.profile["testing"]["smoke"].update(
            command=self.command("orphan", str(self.pid_file)), url=url)
        runners, helper_pid = self.controlled_smoke_helper(after_exit=(
            "[System.IO.File]::WriteAllText('command-exited', 'exited')\n"
            "while (-not (Test-Path 'release-exit')) { Start-Sleep -Milliseconds 20 }"))
        with patch(f"{__name__}.RUNNERS", runners):
            code = self.invoke(status=None, timeout=12)
        self.assertEqual(self.event("smoke")["outcome"], "fail", self.output)
        self.assertEqual(code, 1, self.output)
        self.assertTrue(exited.exists(), "actual command must have exited")
        self.assertIn("process exited", self.event("smoke")["reason"])
        self.assertIn("launcher stderr without newline", self.event("smoke")["stderr_tail"])
        self.assert_no_success_summary()
        self.assert_stopped(self.pid_file)
        self.assert_stopped(self.pid_file.with_suffix(".child"))
        assert_process_stopped(self, helper_pid, self.output)

    def test_command_removed_after_resolution_fails_launch_at_reachable_url(self):
        self.smoke(timeout=3)
        url, requests = self.reachable_url()
        executable = self.cwd / "removed-before-launch.exe"
        shutil.copy2(sys.executable, executable)
        self.profile["testing"]["smoke"].update(command=[str(executable), "-V"], url=url)
        runners, helper_pid = self.controlled_smoke_helper(
            before_launch="Remove-Item -LiteralPath 'removed-before-launch.exe'")
        with patch(f"{__name__}.RUNNERS", runners):
            code = self.invoke(status=None, timeout=12)
        self.assertEqual(self.event("smoke")["outcome"], "fail", self.output)
        self.assertEqual(code, 1, self.output)
        self.assertFalse(executable.exists(), self.output)
        self.assertNotEqual(self.event("smoke")["exit_code"], 0)
        self.assertIn("process exited", self.event("smoke")["reason"])
        self.assertIn(executable.name, self.event("smoke")["stderr_tail"])
        self.assertEqual(requests, ["/health"], "failed launch must not poll HTTP")
        self.assert_no_success_summary()
        assert_process_stopped(self, helper_pid, self.output)

    def test_partial_output_is_reported_without_eof_or_stopping_writer(self):
        self.pid_file = self.cwd / "capture.pid"
        self.addCleanup(self.cleanup_pids)
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-File", str(FIXTURE.with_name("smoke_capture.ps1")),
             "-Runner", str(RUNNERS / "run-gate.ps1"), "-Python", sys.executable,
             "-Fixture", str(FIXTURE), "-PidFile", str(self.pid_file)],
            capture_output=True, text=True, timeout=12,
        )
        self.output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, self.output)
        captured = json.loads(result.stdout)
        self.assertTrue(captured["alive"], "capture must not terminate the live negative control")
        self.assertLess(captured["elapsed_ms"], 3000)
        self.assertIn("partial stdout", captured["text"])
        self.assertIn("partial stderr", captured["text"])
        self.assertIn("output drain timed out", captured["text"])
        self.assert_stopped(self.pid_file)

    def test_smoke_ownership_setup_is_bounded_and_cleans_up(self):
        self.smoke()
        runners = self.cwd / "runners"
        runners.mkdir()
        shutil.copyfile(RUNNERS / "run-gate.ps1", runners / "run-gate.ps1")
        (runners / "start-smoke.ps1").write_text(
            "[System.IO.File]::WriteAllText('smoke.pid', [string]$PID)\n"
            "Start-Sleep -Seconds 120\n", encoding="utf-8")
        started = time.monotonic()
        with patch(f"{__name__}.RUNNERS", runners):
            self.assertEqual(self.invoke(status=None, timeout=12), 1, self.output)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("ownership setup did not complete within 5s", self.event("smoke")["reason"])
        self.assert_no_success_summary()
        self.assert_stopped(self.pid_file)


@unittest.skipUnless(shutil.which("yq") and os.name != "nt",
                     "Bash runner requires installed mikefarah yq")
class BashGateTests(GateCases, unittest.TestCase):
    shell = "bash"


if __name__ == "__main__":
    unittest.main()
