"""No-loop contracts for native qualification. NOT Linux enforcement evidence."""
from __future__ import annotations

import ast
from contextlib import redirect_stdout
from dataclasses import replace
import errno
import hashlib
import inspect
import io
import json
from pathlib import Path
import socket
import ssl
import tempfile
from types import FunctionType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

import native_runtime_integration as native


def offered(schema=None):
    from copilot.rpc import CurrentToolMetadata, ToolsGetCurrentMetadataResult

    return ToolsGetCurrentMetadataResult(tools=[CurrentToolMetadata(
        name="bash", description="synthetic", input_schema=schema or {
            "type": "object", "additionalProperties": False,
            "required": ["command", "description"],
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "description": {"type": "string"},
                "mode": {"type": "string", "enum": ["sync", "async"]},
                "initial_wait": {"type": "integer", "minimum": 1, "maximum": 600},
            },
        })])


def shell_request(command="fixed command", **changes):
    from copilot.session_events import PermissionRequestShell

    return PermissionRequestShell(**{
        "can_offer_session_approval": False, "commands": [],
        "full_command_text": command, "has_write_file_redirection": False,
        "intention": "synthetic", "possible_paths": [], "possible_urls": [],
        **changes,
    })


def finish(coroutine):
    """Immediate RPC doubles must never yield or construct an asyncio loop."""
    try:
        coroutine.send(None)
    except StopIteration as done:
        return done.value
    finally:
        coroutine.close()
    raise AssertionError("offline contract unexpectedly suspended")


class ProcessDescriptorTests(unittest.TestCase):
    def test_native_rpc_shapes_bind_to_installed_sdk_without_constructing_client(self):
        from copilot.generated.rpc import ToolsApi
        from copilot.rpc import ToolsExecuteRequest

        request = ToolsExecuteRequest(
            name="bash", arguments=native._process_arguments(offered(), "fixed"), tool_call_id="call")
        inspect.signature(ToolsApi.execute).bind(None, request, timeout=native.PROCESS_TIMEOUT)
        inspect.signature(ToolsApi.initialize_and_validate).bind(None)
        inspect.signature(ToolsApi.get_current_metadata).bind(None)
        self.assertEqual(request.to_dict()["arguments"]["command"], "fixed")

    def test_current_metadata_preserves_schema_that_builtin_decoder_loses(self):
        from copilot.rpc import BuiltinToolInputSchema, CurrentToolMetadata

        schema = offered().tools[0].input_schema
        decoded = BuiltinToolInputSchema.from_dict(schema).to_dict()
        self.assertEqual(decoded, {"type": "object"})
        current = CurrentToolMetadata.from_dict({
            "name": "bash", "description": "", "input_schema": schema,
        })
        self.assertEqual(current.input_schema, schema)

    def test_arguments_use_supported_sync_window_and_exact_command(self):
        result = native._process_arguments(offered(), "fixed command")
        self.assertEqual(result, {
            "command": "fixed command", "description": "Fixed native boundary qualification",
            "mode": "sync", "initial_wait": 30,
        })

    def test_missing_required_unknown_schema_and_unsupported_bounds_fail_closed(self):
        schema = offered().tools[0].input_schema
        variants = [
            {**schema, "required": ["timeout"]},
            {**schema, "required": [None]},
            {**schema, "allOf": []},
            {**schema, "additionalProperties": {}},
            {**schema, "$schema": "unrecognized"},
            {**schema, "properties": {**schema["properties"], "env": {"type": "object"}}},
            {**schema, "properties": {"command": {"type": "string"}}},
            {**schema, "properties": {**schema["properties"],
                                    "mode": {"type": "string", "enum": ["async"]}}},
            {**schema, "properties": {**schema["properties"],
                                    "initial_wait": {"type": "integer", "maximum": 10}}},
            {**schema, "properties": {**schema["properties"],
                                    "command": {"type": "string", "pattern": ".*"}}},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                with self.assertRaisesRegex(native.CheckFailure, "process_descriptor_incompatible"):
                    native._process_arguments(offered(variant), "fixed command")

    def test_not_offered_duplicate_or_mcp_bash_is_not_native(self):
        tool = offered().tools[0]
        for tools in (None, [], [tool, tool], [replace(tool, name="shell")],
                      [replace(tool, mcp_server_name="synthetic")]):
            with self.subTest(tools=tools):
                with self.assertRaisesRegex(native.CheckFailure, "process_descriptor_incompatible"):
                    native._process_arguments(SimpleNamespace(tools=tools), "fixed")

    def diagnostic(self, metadata):
        with self.assertRaisesRegex(native.CheckFailure, "^process_descriptor_incompatible$") as caught:
            native._process_arguments(metadata, "fixed command")
        diagnostic = caught.exception.diagnostic
        public = native.safe_failure_report(json.dumps({
            "status": "fail", "check": "native_process_sandbox",
            "reason": "process_descriptor_incompatible", "process_descriptor": diagnostic,
        }))
        self.assertEqual(public["process_descriptor"], diagnostic)
        return diagnostic

    def test_pinned_wire_alias_is_dictionary_not_json_text_or_camel_case(self):
        from copilot.rpc import CurrentToolMetadata, ToolsGetCurrentMetadataResult

        schema = offered().tools[0].input_schema
        decoded = ToolsGetCurrentMetadataResult.from_dict({"tools": [{
            "name": "bash", "description": "synthetic", "input_schema": schema,
        }]})
        self.assertEqual(decoded.tools[0].to_dict()["input_schema"], schema)
        self.assertEqual(native._process_arguments(decoded, "fixed command")["command"], "fixed command")
        with self.assertRaises(AssertionError):
            CurrentToolMetadata.from_dict({
                "name": "bash", "description": "", "input_schema": json.dumps(schema)})
        wrong_alias = CurrentToolMetadata.from_dict({
            "name": "bash", "description": "", "inputSchema": schema})
        diagnostic = self.diagnostic(SimpleNamespace(tools=[wrong_alias]))
        self.assertEqual((diagnostic["stage"], diagnostic["schema_shape"]), ("schema", "null"))

    def test_descriptor_envelope_and_schema_shapes_have_distinct_fixed_reasons(self):
        from copilot.rpc import BuiltinToolInputSchema

        tool = offered().tools[0]
        cases = [
            (SimpleNamespace(tools=None), "tools", "shape", "null"),
            (SimpleNamespace(tools=[]), "tools", "count", "list"),
            (SimpleNamespace(tools=[replace(tool, name="other")]), "identity", "identity", "null"),
            (SimpleNamespace(tools=[replace(tool, input_schema="sensitive")]),
             "schema", "shape", "string"),
            (SimpleNamespace(tools=[replace(tool, input_schema=BuiltinToolInputSchema.from_dict(
                {"type": "object"}))]), "schema", "shape", "other"),
            (offered({"type": ["object", "null"]}), "schema", "type", "mapping"),
        ]
        for metadata, stage, reason, shape in cases:
            with self.subTest(stage=stage, reason=reason, shape=shape):
                diagnostic = self.diagnostic(metadata)
                self.assertEqual((diagnostic["stage"], diagnostic["reason"], diagnostic["schema_shape"]),
                                 (stage, reason, shape))

    def test_rejection_identifies_exact_stage_property_and_constraint_without_changing_acceptance(self):
        schema = offered().tools[0].input_schema
        cases = [
            ({**schema, "properties": None}, "properties", "shape", "root", "properties"),
            ({**schema, "required": [None]}, "required", "shape", "root", "required"),
            ({**schema, "required": ["timeout"]}, "required", "unsupplied", "root", "required"),
            ({**schema, "required": ["unknown"]}, "required", "unsupplied", "root", "required"),
            ({**schema, "allOf": []}, "schema", "keywords", "root", "none"),
            ({**schema, "$ref": "sensitive"}, "schema", "keywords", "root", "none"),
            ({**schema, "additionalProperties": {}}, "schema", "shape", "root", "additionalProperties"),
            ({**schema, "$schema": "sensitive"}, "schema", "unsupported", "root", "$schema"),
            ({**schema, "properties": {"command": {"type": "string"}}},
             "properties", "missing", "root", "properties"),
        ]
        property_cases = [
            ("command", None, "property", "shape", "none"),
            ("command", {"type": "string", "pattern": "sensitive"}, "property", "keywords", "none"),
            ("command", {"$ref": "sensitive"}, "property", "keywords", "none"),
            ("mode", {"oneOf": [{"type": "string"}, {"type": "null"}]},
             "property", "keywords", "none"),
            ("mode", {"type": ["string", "null"]}, "property", "type", "type"),
            ("mode", {"type": "boolean"}, "property", "type", "type"),
            ("mode", {"type": "number"}, "argument", "type", "type"),
            ("mode", {"type": "string", "enum": []}, "property", "enum_shape", "enum"),
            ("mode", {"type": "string", "enum": [True]}, "property", "enum_shape", "enum"),
            ("mode", {"type": "string", "enum": ["async"]}, "argument", "enum_mismatch", "enum"),
            ("command", {"type": "string", "minLength": -1}, "property", "bound_shape", "minLength"),
            ("command", {"type": "string", "minimum": 1}, "property", "bound_shape", "minimum"),
            ("command", {"type": "string", "minLength": 50}, "argument", "bound_mismatch", "minLength"),
            ("command", {"type": "string", "maxLength": 1}, "argument", "bound_mismatch", "maxLength"),
            ("initial_wait", {"type": "integer", "minimum": True}, "property", "bound_shape", "minimum"),
            ("initial_wait", {"type": "integer", "minimum": 31}, "argument", "bound_mismatch", "minimum"),
            ("initial_wait", {"type": "integer", "minimum": 31, "maximum": 10},
             "argument", "bound_mismatch", "minimum"),
            ("initial_wait", {"type": "integer", "maximum": 10}, "argument", "bound_mismatch", "maximum"),
        ]
        cases.extend(({**schema, "properties": {**schema["properties"], name: spec}},
                      stage, reason, name, keyword)
                     for name, spec, stage, reason, keyword in property_cases)
        for variant, stage, reason, name, keyword in cases:
            with self.subTest(stage=stage, reason=reason, name=name, keyword=keyword):
                diagnostic = self.diagnostic(offered(variant))
                self.assertEqual({key: diagnostic[key] for key in ("stage", "reason", "property", "keyword")},
                                 {"stage": stage, "reason": reason, "property": name, "keyword": keyword})

    def test_required_known_but_undeclared_argument_is_identified_without_guessing_a_value(self):
        schema = offered().tools[0].input_schema
        schema["required"] = ["timeout"]
        diagnostic = self.diagnostic(offered(schema))
        self.assertEqual(diagnostic["required_arguments"], ["timeout"])
        self.assertNotIn("timeout", diagnostic["properties"])
        self.assertEqual(diagnostic["reason"], "unsupplied")

    def test_known_presence_types_and_required_flags_survive_while_unknown_names_are_counted(self):
        schema = offered().tools[0].input_schema
        schema["properties"]["sensitive/path"] = {"type": "string"}
        schema["required"].append("sensitive/path")
        diagnostic = self.diagnostic(offered(schema))
        self.assertEqual((diagnostic["stage"], diagnostic["reason"]), ("properties", "unsupported"))
        self.assertEqual(diagnostic["unknown_properties"], 1)
        self.assertEqual(diagnostic["unknown_required"], 1)
        self.assertEqual(diagnostic["properties"], {
            "command": {"schema_shape": "mapping", "schema_type": "string", "required": "yes"},
            "description": {"schema_shape": "mapping", "schema_type": "string", "required": "yes"},
            "mode": {"schema_shape": "mapping", "schema_type": "string", "required": "no"},
            "initial_wait": {"schema_shape": "mapping", "schema_type": "integer", "required": "no"},
        })
        self.assertNotIn("sensitive", json.dumps(diagnostic))

    def test_diagnostics_omit_arbitrary_metadata_defaults_enum_values_and_reference_targets(self):
        schema = offered().tools[0].input_schema
        secret = "synthetic-private-path-or-token"
        schema.update(description=secret, title=secret, **{"$ref": secret})
        schema["properties"]["mode"].update(default=secret, enum=[secret])
        schema.update({f"{secret}-{i}": secret for i in range(150)})
        schema["properties"].update({f"{secret}-{i}": secret for i in range(150)})
        schema["required"].extend(f"{secret}-{i}" for i in range(150))
        before = json.dumps(schema)
        tool = replace(offered(schema).tools[0], description=secret)
        diagnostic = self.diagnostic(SimpleNamespace(tools=[tool]))
        self.assertIn("$ref", diagnostic["keywords"])
        self.assertEqual(diagnostic["unknown_keywords"], 100)
        self.assertEqual(diagnostic["unknown_properties"], 100)
        self.assertEqual(diagnostic["unknown_required"], 100)
        self.assertNotIn(secret, json.dumps(diagnostic))
        self.assertLess(len(json.dumps(diagnostic)), 2000)
        self.assertEqual(json.dumps(schema), before)

    def test_property_keyword_diagnostic_reports_ref_and_union_without_their_contents(self):
        schema = offered().tools[0].input_schema
        schema["properties"]["mode"] = {
            "type": ["string", "null"], "$ref": "synthetic-secret",
            "anyOf": [{"const": "synthetic-secret"}], "unrecognized-secret": "synthetic-secret",
        }
        diagnostic = self.diagnostic(offered(schema))
        self.assertEqual(diagnostic["schema_type"], "union")
        self.assertEqual(diagnostic["keywords"], ["type", "$ref", "anyOf"])
        self.assertEqual(diagnostic["unknown_keywords"], 1)
        self.assertNotIn("secret", json.dumps(diagnostic))

    def test_parent_strips_forged_diagnostic_text_keys_and_invalid_counts(self):
        public = native.safe_failure_report(json.dumps({
            "status": "fail", "check": "native_process_sandbox", "reason": "process_descriptor_incompatible",
            "process_descriptor": {
                "stage": "schema", "reason": "keywords", "property": "secret", "keyword": ["type"],
                "schema_shape": {}, "schema_type": "secret", "unknown_keywords": True,
                "unknown_properties": 101, "unknown_required": -1, "secret": "secret",
                "keywords": ["$ref", "$ref", "secret", {"type": "secret"}],
                "required_arguments": ["timeout", "timeout", "secret", ["command"]],
                "properties": {"command": {"schema_type": "string", "required": True, "default": "secret"},
                               "mode": "secret", "secret": {"schema_type": "string"}},
            },
        }))
        self.assertEqual(public["process_descriptor"], {
            "stage": "schema", "reason": "keywords", "keywords": ["$ref"],
            "required_arguments": ["timeout"],
            "properties": {"command": {"schema_type": "string"}},
        })
        self.assertNotIn("secret", json.dumps(public))

    def test_descriptor_diagnostics_only_leave_parent_on_relevant_failure(self):
        for status, check, reason in (
            ("pass", "native_process_sandbox", "process_descriptor_incompatible"),
            ("fail", "native_file_denial", "process_descriptor_incompatible"),
            ("fail", "native_process_sandbox", "process_cleanup_failed"),
        ):
            with self.subTest(status=status, check=check, reason=reason):
                public = native.safe_failure_report(json.dumps({
                    "status": status, "check": check, "reason": reason,
                    "process_descriptor": {"stage": "schema"},
                }))
                self.assertNotIn("process_descriptor", public)


class ProcessPermissionTests(unittest.TestCase):
    def setUp(self):
        self.permission = native._ProcessPermission("owned", "fixed command", "call")
        self.context = {"session_id": "owned"}

    def test_only_pending_exact_typed_request_is_approved_once(self):
        request = shell_request(tool_call_id="call")
        self.assertEqual(self.permission(request, self.context).to_dict()["kind"], "reject")
        self.permission.active = True
        self.assertEqual(self.permission(request, self.context).to_dict()["kind"], "approve-once")
        self.assertEqual(self.permission(request, self.context).to_dict()["kind"], "reject")
        self.assertTrue(self.permission.unexpected)

    def test_wrong_session_command_call_id_bypass_and_path_grants_are_rejected(self):
        variants = (
            {"full_command_text": "fixed command extra"},
            {"tool_call_id": "other"}, {"request_sandbox_bypass": True},
            {"request_sandbox_bypass": 0}, {"managed_approval_required": True},
            {"request_sandbox_permissive": True}, {"sandbox_path_grant": {}},
            {"request_sandbox_bypass_reason": "anything"},
        )
        self.permission.active = True
        for changes in variants:
            with self.subTest(changes=changes):
                self.assertEqual(self.permission(shell_request(**changes), self.context)
                                 .to_dict()["kind"], "reject")
        self.assertEqual(self.permission(shell_request(), {"session_id": "other"})
                         .to_dict()["kind"], "reject")
        self.assertFalse(self.permission.consumed)

    def test_untyped_shell_and_non_shell_kinds_never_authorize(self):
        from copilot.session_events import PermissionRequestRead

        self.permission.active = True
        for request in (None, {"kind": "shell", "fullCommandText": "fixed command"},
                        PermissionRequestRead(intention="", path="/owned")):
            with self.subTest(request=request):
                self.assertEqual(self.permission(request, self.context).to_dict()["kind"], "reject")
        self.assertFalse(self.permission.consumed)

    def test_late_callback_cannot_borrow_next_sessions_window(self):
        self.permission.active = False
        other = native._ProcessPermission("other", "fixed command", "call")
        other.active = True
        self.assertEqual(self.permission(shell_request(), {"session_id": "other"})
                         .to_dict()["kind"], "reject")
        self.assertFalse(other.consumed)


class HeadControlTests(unittest.TestCase):
    def invoke(self, *, status=200, error=None):
        response = Mock(status=status)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.side_effect = error
        opener.open.return_value = response
        with patch("urllib.request.getproxies", return_value={"https": "http://127.0.0.1:1234"}):
            with patch("urllib.request.build_opener", return_value=opener) as build:
                outcome = native._head_outcome()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://docs.github.com/")
        self.assertEqual(request.method, "HEAD")
        self.assertIsNone(request.data)
        self.assertEqual(request.header_items(), [])
        self.assertEqual(opener.open.call_args.kwargs, {"timeout": 8})
        response.read.assert_not_called()
        self.assertIsNone(build.call_args.args[1].redirect_request(
            request, None, 302, "", {}, "https://other.invalid/"))
        return outcome

    def test_positive_requires_http_response_without_body_or_redirect(self):
        self.assertEqual(self.invoke(), "http_ok")

    def test_redirect_is_observed_but_never_followed(self):
        error = urllib.error.HTTPError("https://docs.github.com/", 302, "", {}, None)
        self.assertEqual(self.invoke(error=error), "http_ok")

    def test_http_failure_is_not_connection_denial(self):
        error = urllib.error.HTTPError("https://docs.github.com/", 403, "", {}, None)
        self.assertEqual(self.invoke(error=error), "http_error")

    def test_tls_dns_and_generic_setup_failure_are_not_denials(self):
        for error, expected in (
            (ssl.SSLCertVerificationError("synthetic"), "tls_error"),
            (socket.gaierror("synthetic"), "dns_error"),
            (OSError("unexpected setup"), "network_setup_error"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(self.invoke(error=urllib.error.URLError(error)), expected)

    def test_ambiguous_transport_errors_and_proxy_status_cannot_establish_denial(self):
        for error, expected in (
            (OSError(errno.EPERM, "synthetic"), "network_setup_error"),
            (OSError(errno.ECONNREFUSED, "synthetic"), "connection_refused"),
            (OSError(errno.ECONNRESET, "synthetic"), "transport_reset"),
            (OSError(errno.ENETUNREACH, "synthetic"), "network_setup_error"),
            (OSError(errno.EHOSTUNREACH, "synthetic"), "network_setup_error"),
            (TimeoutError(), "transport_timeout"),
            (OSError("Tunnel connection failed: 403 Forbidden"), "network_setup_error"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(self.invoke(error=urllib.error.URLError(error)), expected)

    def test_only_local_connect_permission_refusal_establishes_denial(self):
        for code in (errno.EACCES, errno.EPERM):
            with self.subTest(errno=code):
                with patch("urllib.request.getproxies", return_value={}):
                    with patch("socket.create_connection", side_effect=PermissionError(code, "fixed")):
                        self.assertEqual(native._head_outcome(), "connect_permission_denied")

    def test_sent_head_then_timeout_reset_or_permission_error_is_inconclusive(self):
        for error, expected in (
            (TimeoutError(), "transport_timeout"),
            (ConnectionResetError(errno.ECONNRESET, "fixed"), "transport_reset"),
            (PermissionError(errno.EPERM, "fixed"), "network_setup_error"),
        ):
            with self.subTest(expected=expected):
                connection = Mock()
                connection.makefile.return_value.readline.side_effect = error
                context = Mock()
                context.wrap_socket.return_value = connection
                with patch("urllib.request.getproxies", return_value={}):
                    with patch("socket.create_connection", return_value=connection) as connect:
                        with patch("ssl.create_default_context", return_value=context):
                            self.assertEqual(native._head_outcome(), expected)
                connect.assert_called_once()
                context.wrap_socket.assert_called_once()
                self.assertTrue(connection.sendall.call_args.args[0].startswith(b"HEAD / HTTP/1.1\r\n"))
                connection.makefile.return_value.readline.assert_called_once()
                connection.close.assert_called()

    def test_credential_bearing_proxy_is_never_used(self):
        with patch("urllib.request.getproxies",
                   return_value={"https": "http://invented:invented@127.0.0.1:1234"}):
            with patch("urllib.request.build_opener") as build:
                self.assertEqual(native._head_outcome(), "proxy_credentials")
        build.assert_not_called()


class ProcessEvidenceTests(unittest.TestCase):
    def test_echoed_command_contains_neither_fresh_marker_nor_protected_bytes(self):
        command = native._process_command(
            Path("/owned/workspace"), Path("/owned/protected/file"), Path("/owned/record"),
            "a" * 16 + "b" * 16, "protected", b"secret-fixture")
        self.assertTrue(command.startswith("/usr/bin/python3 -I -c "))
        self.assertNotIn("a" * 16 + "b" * 16, command)
        self.assertNotIn("secret-fixture", command)
        self.assertNotIn("start_new_session", inspect.getsource(native._process_child).replace(
            "# Attached: no setsid/start_new_session, and no shell or arbitrary command.", ""))
        with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
            native._process_result({"resultType": "success", "textResultForLlm": command},
                                   "a" * 16 + "b" * 16, ("read_ok",), "secret-fixture")

    def test_wrong_missing_duplicate_or_reordered_output_cannot_pass(self):
        for text in ("", "n:completed\nn:started", "n:started\nn:wrong\nn:completed",
                     "n:started\nn:read_ok\nn:completed\nn:completed"):
            with self.subTest(text=text):
                with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
                    native._process_result({"resultType": "success", "textResultForLlm": text},
                                           "n", ("read_ok",), "secret-fixture")

    def test_leak_in_any_result_field_is_failure_before_kind_check(self):
        with self.assertRaisesRegex(native.CheckFailure, "protected_canary_leaked"):
            native._process_result({
                "resultType": "denied", "textResultForLlm": "",
                "structuredContent": {"value": "secret-fixture"},
            }, "n", (), "secret-fixture")

    def test_successful_exact_semantic_output_is_accepted_without_logging_contents(self):
        native._process_result({
            "resultType": "success",
            "textResultForLlm": "Output:\nn:started\nn:read_ok\nn:write_ok\nn:completed\n",
        }, "n", ("read_ok", "write_ok"), "secret-fixture")

    def test_failed_or_malformed_result_cannot_pass_even_with_completion_marker(self):
        for result in (
            {"resultType": "timeout", "textResultForLlm": "n:started\nn:completed"},
            {"resultType": "success", "textResultForLlm": None},
            {"resultType": "success", "textResultForLlm": "x" * native.CHILD_REPORT_LIMIT},
            {"resultType": "success", "textResultForLlm": "n:started\nn:completed", "error": "failed"},
        ):
            with self.subTest(result_type=result.get("resultType")):
                with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
                    native._process_result(result, "n", (), "protected-marker")

    def test_fresh_record_requires_actual_owned_live_child_and_attached_descendant(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "record"
            identities = [[4000, 10, 3000, 40, 40], [4001, 11, 4000, 40, 40]]
            record.write_text(json.dumps({"nonce": "n", "identities": identities}))
            table = {4000: (identities[0], "S"), 4001: (identities[1], "S"),
                     3000: ([3000, 9, 2000, 30, 30], "S")}
            with patch.object(native.os, "getpid", return_value=2000):
                with patch.object(native, "_proc_identity", side_effect=table.get):
                    self.assertEqual(native._owned_start(record, "n", True), identities)

    def test_unowned_reused_dead_or_detached_record_is_rejected(self):
        for current, descendant in (
            (None, [4001, 11, 4000, 40, 40]),
            (([4000, 99, 3000, 40, 40], "S"), [4001, 11, 4000, 40, 40]),
            (([4000, 10, 3000, 40, 40], "Z"), [4001, 11, 4000, 40, 40]),
            (([4000, 10, 3000, 40, 40], "S"), [4001, 11, 4000, 41, 41]),
            (([4000, 10, 3000, 40, 40], "S"), [4001, 11, 9999, 40, 40]),
        ):
            with self.subTest(current=current, descendant=descendant):
                with tempfile.TemporaryDirectory() as directory:
                    record = Path(directory) / "record"
                    record.write_text(json.dumps({
                        "nonce": "n", "identities": [[4000, 10, 3000, 40, 40], descendant],
                    }))
                    with patch.object(native, "_proc_identity", side_effect={
                        4000: current, 4001: (descendant, "S"),
                        3000: ([3000, 9, 1, 30, 30], "S"),
                    }.get):
                        with self.assertRaisesRegex(native.CheckFailure, "process_identity_invalid"):
                            native._owned_start(record, "n", True)

    def test_missing_or_stale_start_marker_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "record"
            with self.assertRaisesRegex(native.CheckFailure, "process_start_missing"):
                native._owned_start(record, "n", False)
            record.write_text('{"nonce":"stale","identities":[]}')
            with self.assertRaisesRegex(native.CheckFailure, "process_start_missing"):
                native._owned_start(record, "n", False)

    def test_proc_parser_handles_spaces_and_parentheses_in_process_name(self):
        fields = ["S", "3000", "40", "40"] + ["0"] * 15 + ["10"]
        with patch.object(Path, "read_text",
                          return_value="4000 (a process (name)) " + " ".join(fields)):
            self.assertEqual(native._proc_identity(4000), ([4000, 10, 3000, 40, 40], "S"))
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertIsNone(native._proc_identity(4000))

    def test_death_check_uses_only_recorded_pids_and_starttimes_and_never_kills(self):
        identities = [[4000, 10, 3000, 40, 40], [4001, 11, 4000, 40, 40]]
        with patch.object(native, "_proc_identity", side_effect=[
            None, ([4001, 11, 1, 40, 40], "S"),
        ]) as read:
            self.assertFalse(native._identities_dead(identities))
            self.assertEqual([call.args[0] for call in read.call_args_list], [4000, 4001])
        with patch.object(native, "_proc_identity", side_effect=[
            ([4000, 99, 1, 40, 40], "S"), ([4001, 11, 1, 40, 40], "Z"),
        ]):
            self.assertTrue(native._identities_dead(identities))

    def test_parent_filters_process_diagnostics_and_never_relays_raw_values(self):
        result = native.safe_failure_report(json.dumps({
            "status": "fail", "check": "native_process_sandbox",
            "reason": "process_orphan_alive", "process_controls": {
                "workspace": "complete", "cancel": "raw-pid-command", "unknown": "complete",
                "timeout": ["timed_out"],
            }, "pids": [4000], "command": "never relay",
        }))
        self.assertEqual(result["process_controls"], {"workspace": "complete"})
        self.assertNotIn("pids", result)
        self.assertNotIn("command", result)


class ProcessPayloadTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.record = self.root / "record.json"
        self.target = self.root / "protected"
        self.target.write_bytes(b"synthetic-original")
        self.record.with_suffix(".ready").write_text("fresh-nonce")
        self.original_read = Path.read_text
        fields = ["S", "3000", "40", "40"] + ["0"] * 15 + ["10"]
        self.stat = "4000 (python) " + " ".join(fields)

    def run_child(self, probe):
        def read(path, *args, **kwargs):
            return self.stat if path == Path("/proc/self/stat") else self.original_read(path, *args, **kwargs)
        output = io.StringIO()
        with patch.object(Path, "read_text", read), patch("os.getpid", return_value=4000):
            with redirect_stdout(output):
                native._process_child(
                    str(self.root), str(self.target), str(self.record),
                    ("fresh-", "nonce"), probe, hashlib.sha256(b"synthetic-original").hexdigest())
        return output.getvalue()

    def test_child_really_writes_start_record_and_roundtrips_workspace(self):
        output = self.run_child("workspace")
        self.assertEqual(json.loads(self.record.read_text())["identities"], [[4000, 10, 3000, 40, 40]])
        self.assertEqual((self.root / "process-write.txt").read_text(), "fresh-nonce")
        self.assertIn("fresh-nonce:workspace_ok", output)
        self.assertTrue(output.endswith("fresh-nonce:completed\n"))

    def test_protected_positive_really_reads_and_writes_without_printing_bytes(self):
        output = self.run_child("protected")
        self.assertEqual(self.target.read_bytes(), b"native-write-ok")
        self.assertIn("fresh-nonce:read_ok\nfresh-nonce:write_ok", output)
        self.assertNotIn("synthetic-original", output)

    def test_only_permission_or_missing_errors_count_as_child_refusals(self):
        for error in (PermissionError, FileNotFoundError):
            with self.subTest(error=error):
                with patch.object(Path, "read_bytes", side_effect=error):
                    with patch("builtins.open", side_effect=error):
                        output = self.run_child("protected")
                self.assertIn("fresh-nonce:read_refused\nfresh-nonce:write_refused", output)
        self.assertEqual(self.target.read_bytes(), b"synthetic-original")

    def test_generic_read_or_write_error_cannot_count_as_denial(self):
        with patch.object(Path, "read_bytes", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.run_child("protected")
        with patch("builtins.open", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.run_child("protected")

    def test_wrong_protected_bytes_never_count_as_read_success(self):
        self.target.write_bytes(b"changed")
        with self.assertRaisesRegex(RuntimeError, "fixture_mismatch"):
            self.run_child("protected")

    def test_normal_payload_uses_attached_descendant_and_lasts_eleven_seconds(self):
        descendant = Mock()
        descendant.stdout.readline.return_value = "[4001,11,4000,40,40]\n"
        with patch("subprocess.Popen", return_value=descendant) as launch:
            with patch("time.sleep") as sleep:
                output = self.run_child("normal_exit")
        self.assertEqual(launch.call_args.args[0][:3], ["/usr/bin/python3", "-I", "-c"])
        self.assertNotIn("start_new_session", launch.call_args.kwargs)
        self.assertNotIn("preexec_fn", launch.call_args.kwargs)
        sleep.assert_called_once_with(11)
        descendant.terminate.assert_called_once_with()
        descendant.wait.assert_called_once_with(timeout=3)
        self.assertEqual(json.loads(self.record.read_text())["identities"][1],
                         [4001, 11, 4000, 40, 40])
        self.assertIn("fresh-nonce:attached_complete\nfresh-nonce:completed", output)

    def test_ambient_canary_stops_payload_before_start_proof(self):
        with patch.dict(native.os.environ, {native.CANARY_NAME: "synthetic-only"}):
            with self.assertRaisesRegex(RuntimeError, "ambient_environment"):
                self.run_child("workspace")
        self.assertFalse(self.record.exists())


class NativeProcessMatrixTests(unittest.TestCase):
    """Execute the actual orchestration using immediate typed RPC doubles.

    No event loop/socket/SDK client is constructed; fake time advances only at
    named readiness/execution/death boundaries. Separate payload tests exercise
    real synthetic I/O; neither kind of test is native sandbox evidence.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        (self.root / "workspace").mkdir()
        (self.root / "protected").mkdir()
        self.options = []
        self.calls = []
        self.report = {}
        self.time = 0
        self.alive = False
        self.fault = None
        self.output_override = None
        self.fixture_change = False
        self.permission_noise = None
        self.case = None
        self.short_normal = False
        self.early_completion = False
        self.current_task = None
        self.in_bound = False
        self.premature_identity = None
        self.phase_expiry = None
        self.client = SimpleNamespace(create_session=self.create_session, delete_session=self.delete)

    async def bounded(self, awaitable):
        self.in_bound = True
        try:
            return await awaitable
        finally:
            self.in_bound = False

    def record_call(self, operation):
        self.calls.append((self.case, operation))
        if self.phase_expiry == (self.case, operation):
            import asyncio

            self.deadline_expired = True
            raise asyncio.CancelledError()
        if self.fault == (self.case, operation):
            raise TimeoutError("synthetic")

    def assert_native_policy(self, options, case):
        workspace = str(self.root / "workspace")
        target = str(self.root / "protected" / "process-control.txt")
        self.assertEqual(options["sandbox_config"].to_dict(), {
            "enabled": True, "allowBypass": False, "allowDevToolAccess": False,
            "userPolicy": {
                "filesystem": {
                    "readwritePaths": [workspace, target],
                    "deniedPaths": [target] if case == "protected_deny" else [],
                },
                "network": {
                    "allowedHosts": ["docs.github.com"], "allowLocalNetwork": False,
                    "allowOutbound": case == "network_permit",
                },
            },
        })

    async def delete(self, session_id):
        self.record_call("delete")
        self.assertEqual(session_id, self.options[-1]["session_id"])

    async def create_session(self, **options):
        from copilot import CopilotClient
        from copilot.rpc import PermissionsConfigureParams, ToolsExecuteRequest
        from copilot.session_events import PermissionMode

        inspect.signature(CopilotClient.create_session).bind(None, **options)
        self.case = native.PROCESS_CASES[len(self.options)]
        self.options.append(options)
        self.record_call("create")
        self.assertTrue(self.in_bound)
        # Name-based fake outcomes are valid only after the actual wire policy
        # independently matches the entire expected policy, not merely its pair.
        self.assert_native_policy(options, self.case)
        permission = options["on_permission_request"]
        context = {"session_id": options["session_id"]}

        async def configure(params):
            self.assertIs(type(params), PermissionsConfigureParams)
            self.assertFalse(params.approve_all_tool_permission_requests)
            self.assertFalse(params.paths.include_temp_directory)
            self.record_call("configure")

        async def mode():
            return SimpleNamespace(mode=PermissionMode.MANUAL)

        async def initialize():
            self.record_call("initialize")
            self.assertEqual(permission(shell_request(permission.command), context)
                             .to_dict()["kind"], "reject")

        async def metadata():
            self.record_call("metadata")
            return offered()

        async def execute(params, *, timeout):
            self.assertIs(type(params), ToolsExecuteRequest)
            self.assertEqual(timeout, native.PROCESS_TIMEOUT)
            self.assertEqual(params.name, "bash")
            self.assertEqual(params.arguments["mode"], "sync")
            self.record_call("execute")
            if self.permission_noise is not None:
                self.permission_noise(permission, context)
            decision = permission(shell_request(params.arguments["command"],
                                                tool_call_id=params.tool_call_id), context)
            self.assertEqual(decision.to_dict()["kind"], "approve-once")
            # Inspect only the fixed literal invocation, never eval the payload.
            import shlex
            source = shlex.split(params.arguments["command"])[-1]
            invocation = ast.parse(source).body[-1].value
            workspace, target, record, parts, probe, _digest = [
                ast.literal_eval(arg) for arg in invocation.args]
            self.nonce = "".join(parts)
            self.record = Path(record)
            if self.fault != (self.case, "no_start"):
                self.record.write_text(json.dumps({"nonce": self.nonce, "identities": []}))
            self.alive = True
            if self.case == "protected_permit":
                Path(target).write_bytes(b"native-write-ok")
            if self.fixture_change and self.case == "protected_deny":
                Path(target).write_bytes(b"unauthorized-change")
            outcomes = {
                "workspace": ["workspace_ok"],
                "protected_permit": ["read_ok", "write_ok"],
                "protected_deny": ["read_refused", "write_refused"],
                "network_permit": ["http_ok"], "network_deny": ["connect_permission_denied"],
                "normal_exit": ["attached_complete"], "cancel": [], "timeout": [],
            }[self.case]
            if self.output_override is not None and self.case == self.output_override[0]:
                outcomes = self.output_override[1]
            return {"resultType": "success", "textResultForLlm": "\n".join(
                self.nonce + ":" + item for item in ["started", *outcomes, "completed"])}

        async def abort():
            self.record_call("abort")
            if self.fault != (self.case, "orphan"):
                self.alive = False
            self.current_task.interrupted = True

        async def disconnect():
            self.record_call("disconnect")
            self.assertFalse(permission.active)

        return SimpleNamespace(
            session_id=options["session_id"], abort=abort, disconnect=disconnect,
            rpc=SimpleNamespace(
                permissions=SimpleNamespace(configure=configure, get_mode=mode),
                tools=SimpleNamespace(initialize_and_validate=initialize,
                                      get_current_metadata=metadata, execute=execute)),
        )

    def task(self, coroutine):
        owner = self
        result = finish(coroutine)

        class Task:
            interrupted = False
            completed = False

            def done(self):
                return self.completed

            def cancel(self):
                self.completed = True

            def __await__(self):
                if False:
                    yield
                self.completed = True
                if self.interrupted:
                    return {"resultType": "failure", "textResultForLlm": ""}
                owner.alive = False
                if owner.case == "normal_exit":
                    owner.time += 1 if owner.short_normal else 11
                return result
        self.current_task = Task()
        return self.current_task

    async def wait_for(self, awaitable, timeout):
        if timeout in (native.PROCESS_CANCEL_DELAY, native.PROCESS_CANCEL_TIMEOUT):
            if self.early_completion:
                return await awaitable
            self.time += timeout
            if self.premature_identity == (self.case, None, None):
                self.alive = False  # Both exited, while the tools RPC stays pending.
            raise TimeoutError("deliberate test deadline")
        return await awaitable

    async def sleep(self, seconds):
        self.time += seconds

    def owned_start(self, record, nonce, descendants):
        self.assertEqual(record, self.record)
        self.assertEqual(nonce, self.nonce)
        self.assertTrue(self.alive)
        self.record_call("start_verified")
        return [[4000, 10, 3000, 40, 40]] + (
            [[4001, 11, 4000, 40, 40]] if descendants else [])

    def proc_identity(self, pid):
        self.record_call("identity_" + str(pid))
        if self.premature_identity is not None:
            case, failed_pid, current = self.premature_identity
            if self.case == case and failed_pid in (None, pid):
                # The RPC deliberately stays pending even when this process died.
                self.assertFalse(self.current_task.done())
                return current
        identity = {4000: [4000, 10, 3000, 40, 40], 4001: [4001, 11, 4000, 40, 40]}[pid]
        return (identity, "S") if self.alive else None

    def run_matrix(self, operation=None):
        import asyncio

        with patch.object(asyncio, "get_running_loop",
                          return_value=SimpleNamespace(time=lambda: self.time)):
            with patch.object(asyncio, "create_task", side_effect=self.task):
                with patch.object(asyncio, "wait_for", side_effect=self.wait_for):
                    with patch.object(asyncio, "shield", side_effect=lambda task: task):
                        with patch.object(asyncio, "sleep", side_effect=self.sleep):
                            with patch.object(native, "_owned_start", side_effect=self.owned_start):
                                with patch.object(native, "_identities_dead",
                                                  side_effect=lambda _: not self.alive):
                                    with patch.object(native, "_proc_identity",
                                                      side_effect=self.proc_identity):
                                        return finish(operation() if operation else
                                                      native.qualify_native_processes(
                                                          self.client, self.root, self.report,
                                                          self.bounded, Mock()))

    def run_report_boundary(self):
        """Keep the real process stage, report handler and final cleanup intact."""
        import asyncio

        tree = ast.parse(inspect.getsource(native.native_checks))
        boundary = next(node for node in tree.body[0].body if isinstance(node, ast.Try))
        start = next(index for index, node in enumerate(boundary.body)
                     if isinstance(node, ast.Assign)
                     and ast.unparse(node) == "report['check'] = 'native_process_sandbox'")
        boundary.body = boundary.body[start:]
        function = ast.parse("async def report_boundary(): pass").body[0]
        function.body = [boundary, ast.Return(value=ast.Name(id="report", ctx=ast.Load()))]
        self.report.update(status="fail", passed=["native_file_denial"])
        self.deadline_expired = False
        self.outer_cleanup = []
        owner = self

        class Deadline:
            async def __aenter__(self):
                return self

            def expired(self):
                return owner.deadline_expired

            async def __aexit__(self, kind, value, traceback):
                # Model only the timer's own cancellation, as asyncio.timeout
                # does; ordinary operation TimeoutError is propagated unchanged.
                if self.expired() and kind is asyncio.CancelledError:
                    raise TimeoutError() from None

        def timeout(seconds):
            self.assertEqual(seconds, native.PROCESS_PHASE_TIMEOUT)
            return Deadline()

        async def support():
            return SimpleNamespace(supported=True, capabilities=[
                SimpleNamespace(name="shell", supported=True),
                SimpleNamespace(name="denied_paths", supported=True),
            ])

        async def abort():
            self.outer_cleanup.append("abort")

        async def disconnect():
            self.outer_cleanup.append("disconnect")

        async def stop():
            self.outer_cleanup.append("stop")

        self.client.rpc = SimpleNamespace(sandbox=SimpleNamespace(get_host_support=support))
        self.client.stop = stop
        namespace = {
            **vars(native), "asyncio": asyncio, "report": self.report, "client": self.client,
            "session": SimpleNamespace(abort=abort, disconnect=disconnect),
            "root": self.root, "bounded": self.bounded, "on_event": Mock(),
            "model_activity": SimpleNamespace(is_set=lambda: False),
        }
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     native.__file__, "exec"), namespace)
        with patch.object(asyncio, "timeout", side_effect=timeout):
            report = self.run_matrix(namespace["report_boundary"])
        return native.safe_failure_report(json.dumps(report))

    def test_complete_native_matrix_distinguishes_normal_cancel_and_timeout(self):
        self.run_matrix()
        self.assertEqual(self.report["process_controls"], {
            case: "cancelled" if case == "cancel" else "timed_out" if case == "timeout"
            else "complete" for case in native.PROCESS_CASES})
        self.assertNotIn(("normal_exit", "abort"), self.calls)
        self.assertLess(self.calls.index(("cancel", "start_verified")),
                        self.calls.index(("cancel", "abort")))
        self.assertLess(self.calls.index(("timeout", "start_verified")),
                        self.calls.index(("timeout", "abort")))
        for case in ("cancel", "timeout"):
            abort = self.calls.index((case, "abort"))
            self.assertEqual(self.calls[abort - 2:abort],
                             [(case, "identity_4000"), (case, "identity_4001")])
        self.assertEqual(len([call for call in self.calls if call[1] == "delete"]), 8)

    def test_unsupported_descriptor_never_executes_or_approves_and_still_cleans_up(self):
        schema = offered().tools[0].input_schema
        schema["properties"]["mode"]["enum"] = ["async"]
        metadata = offered(schema)
        with patch(f"{__name__}.offered", return_value=metadata):
            report = self.run_report_boundary()
        self.assertEqual(report["reason"], "process_descriptor_incompatible")
        self.assertEqual(report["process_descriptor"]["reason"], "enum_mismatch")
        self.assertEqual(report["process_descriptor"]["property"], "mode")
        self.assertEqual(report["passed"], ["native_file_denial"])
        self.assertEqual(report["process_controls"], {"workspace": "started"})
        self.assertEqual(report["process_network"], {})
        self.assertNotIn(("workspace", "execute"), self.calls)
        self.assertEqual(self.calls[-2:], [("workspace", "disconnect"), ("workspace", "delete")])
        self.assertEqual(self.outer_cleanup, ["abort", "disconnect", "stop"])
        self.assertFalse(self.options[0]["on_permission_request"].active)
        self.assertFalse(self.options[0]["on_permission_request"].consumed)
        self.assertIsNone(self.current_task)

    def test_successful_process_matrix_does_not_add_descriptor_diagnostics(self):
        self.run_matrix()
        self.assertNotIn("process_descriptor", self.report)

    def test_descriptor_rejection_with_cleanup_failure_still_attempts_delete_and_outer_cleanup(self):
        schema = offered().tools[0].input_schema
        schema["properties"]["mode"]["enum"] = ["async"]
        metadata = offered(schema)
        self.fault = ("workspace", "disconnect")
        with patch(f"{__name__}.offered", return_value=metadata):
            report = self.run_report_boundary()
        self.assertEqual(report["reason"], "process_cleanup_failed")
        self.assertNotIn("process_descriptor", report)
        self.assertNotIn(("workspace", "execute"), self.calls)
        self.assertEqual(self.calls[-2:], [("workspace", "disconnect"), ("workspace", "delete")])
        self.assertEqual(self.outer_cleanup, ["abort", "disconnect", "stop"])

    def test_pairs_change_only_native_policy_and_use_identical_commands(self):
        self.run_matrix()
        for left, right, field in ((1, 2, "filesystem"), (3, 4, "network")):
            with self.subTest(field=field):
                a, b = self.options[left], self.options[right]
                self.assert_native_policy(a, native.PROCESS_CASES[left])
                self.assert_native_policy(b, native.PROCESS_CASES[right])
                self.assertEqual(a["on_permission_request"].command, b["on_permission_request"].command)
                self.assertNotEqual(a["session_id"], b["session_id"])
                def comparable(options):
                    return {key: value.to_dict() if hasattr(value, "to_dict") else
                            value.to_list() if key == "available_tools" else value
                            for key, value in options.items()
                            if key not in ("session_id", "on_permission_request")}
                ca, cb = comparable(a), comparable(b)
                pa = ca["sandbox_config"]["userPolicy"][field]
                pb = cb["sandbox_config"]["userPolicy"][field]
                self.assertNotEqual(pa, pb)
                del ca["sandbox_config"]["userPolicy"][field]
                del cb["sandbox_config"]["userPolicy"][field]
                self.assertEqual(ca, cb)

    def test_paired_policy_assertions_reject_reversed_toggles_and_wrong_targets(self):
        source = inspect.getsource(native.qualify_native_processes)
        for original, mutation in (
            ('case == "protected_deny" else []', 'case == "protected_permit" else []'),
            ('denied_paths=[str(target)]', 'denied_paths=[str(workspace)]'),
            ('readwrite_paths=[str(workspace), str(target)]', 'readwrite_paths=[str(workspace)]'),
            ('allow_outbound=case == "network_permit"', 'allow_outbound=case == "network_deny"'),
            ('allowed_hosts=["docs.github.com"]', 'allowed_hosts=["github.com"]'),
            ('allow_local_network=False', 'allow_local_network=True'),
        ):
            with self.subTest(mutation=mutation):
                self.assertEqual(source.count(original), 1)
                namespace = dict(vars(native))
                exec(compile(source.replace(original, mutation), native.__file__, "exec"), namespace)
                with patch.object(native, "qualify_native_processes",
                                  FunctionType(namespace["qualify_native_processes"].__code__,
                                               vars(native))):
                    result = unittest.TestResult()
                    NativeProcessMatrixTests(
                        "test_pairs_change_only_native_policy_and_use_identical_commands").run(result)
                self.assertEqual(len(result.failures), 1, result.errors)
                self.assertEqual(result.errors, [])

    def test_readiness_is_invisible_until_closed_sibling_is_atomically_published(self):
        write_text = Path.write_text
        replace_file = Path.replace
        publications = []

        def write(path, data, *args, **kwargs):
            self.assertNotEqual(path.suffix, ".ready", "never write the visible acknowledgement")
            if path.name.endswith(".ready.pending"):
                self.assertFalse(path.with_suffix("").exists())
            return write_text(path, data, *args, **kwargs)

        def publish(path, destination):
            if destination.suffix == ".ready":
                self.assertEqual(path, destination.with_suffix(".ready.pending"))
                self.assertFalse(destination.exists())
                self.assertEqual(path.read_text(encoding="utf-8"), self.nonce)
                result = replace_file(path, destination)
                self.assertEqual(destination.read_text(encoding="utf-8"), self.nonce)
                publications.append(self.case)
                return result
            return replace_file(path, destination)

        with patch.object(Path, "write_text", write), patch.object(Path, "replace", publish):
            self.run_matrix()
        self.assertEqual(publications, list(native.PROCESS_CASES))

    def test_disposable_sessions_have_no_ambient_sources_or_bypass(self):
        self.run_matrix()
        for options in self.options:
            with self.subTest(session=options["session_id"]):
                self.assertEqual(options["available_tools"].to_list(), ["builtin:bash"])
                self.assertFalse(options["enable_config_discovery"])
                self.assertFalse(options["enable_skills"])
                self.assertEqual(options["mcp_servers"], {})
                self.assertEqual(options["disabled_mcp_servers"], ["*"])
                self.assertFalse(options["sandbox_config"].allow_bypass)
                self.assertFalse(options["sandbox_config"].allow_dev_tool_access)
                self.assertTrue(options["sandbox_config"].enabled)
                self.assertEqual(options["managed_settings"].permissions
                                 .disable_bypass_permissions_mode, "disable")
                self.assertEqual(options["sandbox_config"].user_policy.network.allowed_hosts,
                                 ["docs.github.com"])
                for key in ("plugin_directories", "agent_directories", "skill_directories",
                            "instruction_directories", "hook_directories"):
                    self.assertEqual(options[key], [])

    def test_network_allow_failure_does_not_run_or_pass_negative(self):
        self.output_override = ("network_permit", ["connection_refused"])
        with self.assertRaisesRegex(native.CheckFailure, "process_network_positive_failed"):
            self.run_matrix()
        self.assertNotIn("network_deny", self.report["process_controls"])
        self.assertEqual(self.calls[-1], ("network_permit", "delete"))
        self.assertEqual(self.report["process_network"], {"network_permit": "connection_refused"})

    def test_network_blocked_http_response_does_not_count_as_denial(self):
        self.output_override = ("network_deny", ["http_ok"])
        with self.assertRaisesRegex(native.CheckFailure, "process_network_negative_failed"):
            self.run_matrix()

    def test_network_negative_tls_failure_is_inconclusive_not_a_pass(self):
        self.output_override = ("network_deny", ["tls_error"])
        with self.assertRaisesRegex(native.CheckFailure, "process_network_negative_failed"):
            self.run_matrix()
        self.assertEqual(self.report["process_network"]["network_deny"], "tls_error")

    def test_ambiguous_network_failures_never_qualify_outbound_denial(self):
        for outcome in ("transport_timeout", "transport_reset", "connection_refused",
                        "network_setup_error", "http_error"):
            with self.subTest(outcome=outcome):
                case = NativeProcessMatrixTests()
                case.setUp()
                try:
                    case.output_override = ("network_deny", [outcome])
                    with self.assertRaisesRegex(native.CheckFailure, "process_network_negative_failed"):
                        case.run_matrix()
                    self.assertEqual(case.report["process_controls"]["network_deny"], "started")
                    self.assertEqual(case.calls[-1], ("network_deny", "delete"))
                finally:
                    case.doCleanups()

    def test_native_negative_read_success_fails_even_without_printed_file_contents(self):
        self.output_override = ("protected_deny", ["read_ok", "write_refused"])
        with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
            self.run_matrix()

    def test_protected_positive_failure_cannot_qualify_negative_policy(self):
        self.output_override = ("protected_permit", ["read_refused", "write_refused"])
        with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
            self.run_matrix()
        self.assertNotIn("protected_deny", self.report["process_controls"])

    def test_early_completion_cannot_be_called_cancellation(self):
        self.early_completion = True
        with self.assertRaisesRegex(native.CheckFailure, "process_completed_before_cancel"):
            self.run_matrix()
        self.assertEqual(self.report["process_controls"]["cancel"], "started")

    def test_dead_or_reused_parent_or_descendant_with_pending_rpc_cannot_earn_abort_credit(self):
        for control in ("cancel", "timeout"):
            for pid in (4000, 4001):
                for current in (None, ([pid, 99, 3000, 40, 40], "S"),
                                ([pid, 10 if pid == 4000 else 11,
                                  3000 if pid == 4000 else 4000, 40, 40], "Z")):
                    with self.subTest(control=control, pid=pid, current=current):
                        case = NativeProcessMatrixTests()
                        case.setUp()
                        try:
                            case.premature_identity = (control, pid, current)
                            with self.assertRaisesRegex(native.CheckFailure,
                                                        "process_completed_before_cancel"):
                                case.run_matrix()
                            self.assertEqual(case.report["process_controls"][control], "started")
                            self.assertIn((control, "abort"), case.calls)  # Cleanup still runs.
                            self.assertEqual(case.calls[-1], (control, "delete"))
                        finally:
                            case.doCleanups()

    def test_both_processes_exit_with_pending_rpc_so_noop_abort_cannot_qualify(self):
        self.premature_identity = ("cancel", None, None)
        with self.assertRaisesRegex(native.CheckFailure, "process_completed_before_cancel"):
            self.run_matrix()
        self.assertEqual(self.report["process_controls"]["cancel"], "started")
        self.assertIn(("cancel", "abort"), self.calls)  # Only failure cleanup, not pass credit.
        self.assertEqual(self.calls[-1], ("cancel", "delete"))

    def test_normal_result_must_remain_attached_for_more_than_ten_seconds(self):
        self.short_normal = True
        with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
            self.run_matrix()
        self.assertEqual(self.report["process_controls"]["normal_exit"], "started")

    def test_protected_negative_changed_bytes_fail_even_with_refusal_output(self):
        self.fixture_change = True
        with self.assertRaisesRegex(native.CheckFailure, "process_fixture_changed"):
            self.run_matrix()
        self.assertEqual(self.report["process_controls"]["protected_deny"], "started")

    def test_wrong_output_does_not_pass_workspace(self):
        self.output_override = ("workspace", ["wrong"])
        with self.assertRaisesRegex(native.CheckFailure, "process_result_invalid"):
            self.run_matrix()
        self.assertEqual(self.calls[-1], ("workspace", "delete"))

    def test_missing_actual_start_record_times_out_and_cleans_session(self):
        self.fault = ("workspace", "no_start")
        with self.assertRaisesRegex(native.CheckFailure, "process_start_missing"):
            self.run_matrix()
        self.assertIn(("workspace", "abort"), self.calls)
        self.assertEqual(self.calls[-1], ("workspace", "delete"))

    def test_cleanup_orphan_remains_failure_after_native_abort_acknowledgement(self):
        self.fault = ("cancel", "orphan")
        with self.assertRaisesRegex(native.CheckFailure, "process_cleanup_failed"):
            self.run_matrix()
        self.assertNotEqual(self.report["process_controls"]["cancel"], "cancelled")
        self.assertEqual(self.calls[-1], ("cancel", "delete"))

    def test_failed_delete_does_not_award_normal_cleanup(self):
        self.fault = ("normal_exit", "delete")
        with self.assertRaisesRegex(native.CheckFailure, "process_cleanup_failed"):
            self.run_matrix()
        self.assertEqual(self.report["process_controls"]["normal_exit"], "started")

    def test_unrecognized_permission_request_poisoning_is_not_hidden_by_success(self):
        def noise(permission, context):
            decision = permission(shell_request("different command"), context)
            self.assertEqual(decision.to_dict()["kind"], "reject")
        self.permission_noise = noise
        with self.assertRaisesRegex(native.CheckFailure, "process_permission_mismatch"):
            self.run_matrix()

    def test_metadata_timeout_cleans_owned_session_without_starting_command(self):
        self.fault = ("workspace", "metadata")
        with self.assertRaises(TimeoutError):
            self.run_matrix()
        self.assertNotIn(("workspace", "execute"), self.calls)
        self.assertEqual(self.calls[-1], ("workspace", "delete"))

    def test_inner_operation_timeouts_reach_final_report_without_phase_deadline_credit(self):
        for operation in ("configure", "metadata", "execute"):
            with self.subTest(operation=operation):
                case = NativeProcessMatrixTests()
                case.setUp()
                try:
                    case.fault = ("workspace", operation)
                    report = case.run_report_boundary()
                    self.assertFalse(case.deadline_expired)
                    self.assertEqual(report["status"], "fail")
                    self.assertEqual(report["reason"], "process_operation_timeout")
                    self.assertEqual(report["check"], "native_process_sandbox")
                    self.assertEqual(report["passed"], ["native_file_denial"])
                    self.assertEqual(report["process_controls"], {"workspace": "started"})
                    self.assertEqual(case.calls[-2:], [("workspace", "disconnect"),
                                                       ("workspace", "delete")])
                    self.assertEqual(case.outer_cleanup, ["abort", "disconnect", "stop"])
                finally:
                    case.doCleanups()

    def test_phase_deadline_cancellation_reaches_final_report_after_bounded_cleanup(self):
        self.phase_expiry = ("workspace", "metadata")
        report = self.run_report_boundary()
        self.assertTrue(self.deadline_expired)
        self.assertEqual(report["status"], "fail")
        self.assertEqual(report["reason"], "process_deadline_exceeded")
        self.assertEqual(report["check"], "native_process_sandbox")
        self.assertEqual(report["passed"], ["native_file_denial"])
        self.assertEqual(report["process_controls"], {"workspace": "started"})
        self.assertNotIn(("workspace", "execute"), self.calls)
        self.assertEqual(self.calls[-2:], [("workspace", "disconnect"), ("workspace", "delete")])
        self.assertEqual(self.outer_cleanup, ["abort", "disconnect", "stop"])


if __name__ == "__main__":
    unittest.main()
