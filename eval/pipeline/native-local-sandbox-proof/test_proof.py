"""Pure infrastructure tests: never start Copilot or require Linux."""

import copy
import json
from pathlib import Path, PurePosixPath
import unittest
from unittest.mock import patch

from proof import check_boundaries, parse_probe, permitted, policy
from setup_runtime import require_hosted, verify


class ProofTests(unittest.TestCase):
    def setUp(self):
        self.host = {
            "uid": 1001, "namespaces": {"user": "u1", "mnt": "m1", "net": "n1"},
            **{k: True for k in ("workspace_read", "workspace_write", "command",
                                "outside_read", "outside_write", "outbound", "localhost")},
        }
        self.child = copy.deepcopy(self.host)
        self.child.update(namespaces={"user": "u2", "mnt": "m2", "net": "n2"},
                          outside_read=False, outside_write=False, outbound=False, localhost=False)

    def test_positive_isolation(self):
        self.assertTrue(all(check_boundaries(self.host, self.child, {"123"}).values()))

    def test_unsandboxed_execution_cannot_pass(self):
        self.assertFalse(all(check_boundaries(self.host, self.host, set()).values()))

    def test_each_leak_fails(self):
        for field in ("outside_read", "outside_write", "outbound", "localhost"):
            with self.subTest(field=field):
                child = dict(self.child, **{field: True})
                self.assertFalse(all(check_boundaries(self.host, child, {"123"}).values()))

    def test_failed_positive_control_cannot_prove_denial(self):
        host = dict(self.host, outbound=False)
        self.assertFalse(check_boundaries(host, self.child, {"123"})["outbound_denied"])

    def test_no_backend_observation_fails(self):
        self.assertFalse(check_boundaries(self.host, self.child, set())["native_bwrap_observed"])

    def test_root_execution_fails(self):
        self.assertFalse(check_boundaries(self.host, dict(self.child, uid=0), {"1"})["non_root"])

    def test_same_namespace_fails(self):
        for name in ("user", "mnt", "net"):
            child = copy.deepcopy(self.child)
            child["namespaces"][name] = self.host["namespaces"][name]
            self.assertFalse(check_boundaries(self.host, child, {"1"})["private_namespaces"])

    def test_probe_marker_is_required_and_unique(self):
        line = "NATIVE_PROBE=" + json.dumps(self.child)
        self.assertEqual(parse_probe("tool output\n" + line + "\n"), self.child)
        for text in ("", "command echoed NATIVE_PROBE={}", line + "\n" + line):
            with self.subTest(text=text):
                with self.assertRaises(AssertionError):
                    parse_probe(text)

    def test_policy_explicitly_denies_network_and_bypass(self):
        sandbox = policy(PurePosixPath("/work"), PurePosixPath("/outside"))["sandbox"]
        self.assertTrue(sandbox["enabled"])
        for key in ("allowBypass", "allowDevToolAccess"):
            self.assertFalse(sandbox[key])
        self.assertEqual(sandbox["userPolicy"]["filesystem"]["deniedPaths"], ["/outside"])
        self.assertEqual(sandbox["userPolicy"]["network"],
                         {"allowOutbound": False, "allowLocalNetwork": False})
        self.assertEqual(sandbox["auth"], {"git": False, "gh": False})

    def test_only_exact_command_permission(self):
        data = {"kind": "shell", "fullCommandText": "synthetic"}
        self.assertTrue(permitted(data, "synthetic"))
        self.assertFalse(permitted(data, "different"))
        self.assertFalse(permitted(dict(data, kind="read"), "synthetic"))

    def test_no_bypass_or_policy_escalation(self):
        data = {"kind": "shell", "fullCommandText": "synthetic"}
        for key in ("requestSandboxBypass", "requestSandboxPermissive",
                    "sandboxPathGrant", "managedApprovalRequired"):
            with self.subTest(key=key):
                self.assertFalse(permitted(dict(data, **{key: True}), "synthetic"))

    def test_archive_integrity_rejects_bad_bytes(self):
        with self.assertRaisesRegex(RuntimeError, "integrity"):
            verify(b"not-a-cli")

    def test_local_execution_refused(self):
        with patch("setup_runtime.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(RuntimeError, "GitHub-hosted"):
                require_hosted()

    def test_harness_has_no_model_send_or_sampling(self):
        import ast
        tree = ast.parse(Path(__file__).with_name("proof.py").read_text())
        forbidden = {"send", "send_and_wait", "execute_sampling", "compact"}
        self.assertFalse([n for n in ast.walk(tree) if isinstance(n, ast.Call)
                          and isinstance(n.func, ast.Attribute) and n.func.attr in forbidden])


if __name__ == "__main__":
    unittest.main()
