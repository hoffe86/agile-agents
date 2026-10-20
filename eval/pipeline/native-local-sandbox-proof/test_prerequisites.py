"""Offline pipeline diagnostics tests; never invoke apt or sudo."""

from contextlib import redirect_stdout
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import diagnose_prerequisites as diagnostics


class PrerequisiteDiagnosticsTests(unittest.TestCase):
    def invoke(self, phase, output, code):
        process = MagicMock()
        process.stdout = io.StringIO(output)
        process.wait.return_value = code
        process.__enter__.return_value = process
        captured = io.StringIO()
        with patch.object(diagnostics.subprocess, "Popen", return_value=process) as popen:
            with redirect_stdout(captured), patch.dict(os.environ, {}, clear=True):
                result = diagnostics.run(phase)
        return result, captured.getvalue(), popen.call_args

    def test_failure_retains_exit_and_actual_apt_error(self):
        code, output, call = self.invoke(
            "install", "E: Unable to locate package bubblewrap\n", 100)
        self.assertEqual(code, 100)
        self.assertIn("::error title=Native prerequisite install::", output)
        self.assertIn("E: Unable to locate package bubblewrap", output)
        self.assertEqual(call.args[0], [
            "sudo", "apt-get", *diagnostics.APT_OPTIONS, "install",
            "--no-install-recommends", "-y", "bubblewrap", "slirp4netns",
            "util-linux", "iptables",
        ])
        self.assertEqual(call.kwargs["stderr"], diagnostics.subprocess.STDOUT)

    def test_update_warnings_are_public_even_with_zero_exit(self):
        code, output, _ = self.invoke(
            "update", "W: Failed to fetch https://snapshot.ubuntu.com/ubuntu/ timeout\n", 0)
        self.assertEqual(code, 0)
        self.assertIn("::warning title=Native prerequisite update::", output)
        self.assertIn("snapshot.ubuntu.com", output)
        self.assertIn("timeout", output)

    def test_clean_success_has_no_failure_annotation(self):
        code, output, _ = self.invoke("update", "Reading package lists...\n", 0)
        self.assertEqual(code, 0)
        self.assertNotIn("::", output)

    def test_update_retries_are_bounded_and_fetch_errors_fail_closed(self):
        code, output, call = self.invoke(
            "update", "E: Failed to fetch snapshot index 502 Bad Gateway\n", 100)
        self.assertEqual(code, 100)
        self.assertEqual(call.args[0], [
            "sudo", "apt-get", *diagnostics.APT_OPTIONS, "update", "--error-on=any",
        ])
        self.assertIn("Acquire::Retries=2", call.args[0])
        self.assertIn("502 Bad Gateway", output)

    def test_sanitizes_credentials_and_terminal_controls(self):
        text = diagnostics.sanitize(
            "\x1b[31mE: https://user:password@example.org/path?token=private#secret "
            "Authorization: Bearer sensitive\x1b[0m")
        self.assertEqual(text, "E: https://example.org/path Authorization: [redacted]")
        self.assertEqual(diagnostics.sanitize("ghp_fakeToken123"), "[redacted]")

    def test_bounds_output_and_escapes_workflow_commands(self):
        _, output, _ = self.invoke(
            "install", ("x" * 1000 + "\n") * 1000 + "E: 50%\n::error::injected\n", 100)
        self.assertLess(len(output), 4096)
        self.assertIn("50%25%0A::error::injected", output)
        self.assertEqual(len(output.splitlines()), 1)

    def test_summary_escapes_html_and_contains_diagnosis(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary"
            with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": str(summary)}):
                with redirect_stdout(io.StringIO()):
                    diagnostics.report("install", 100, ["E: <script>broken</script>"])
            text = summary.read_text(encoding="utf-8")
        self.assertIn("exit 100", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>", text)


if __name__ == "__main__":
    unittest.main()
