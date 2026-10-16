"""Pure host tests: never execute guest code or a generated artifact locally."""

import io
import json
import tarfile
import unittest
from unittest.mock import patch

import worker


def archive_of(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, kind, data in entries:
            entry = tarfile.TarInfo(name)
            entry.type = kind
            entry.size = len(data) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                entry.linkname = "/host-canary"
            archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


class WorkerUnitTests(unittest.TestCase):
    def test_context_is_copy_only_and_digest_pinned(self):
        payload = b"this is inert host test data, never executed"
        context = worker.build_context({"task.py": payload})
        with tarfile.open(fileobj=io.BytesIO(context)) as archive:
            self.assertEqual(archive.extractfile("input/task.py").read(), payload)
            dockerfile = archive.extractfile("Dockerfile").read().decode()
        self.assertIn("@sha256:", dockerfile)
        self.assertNotIn("\nRUN ", dockerfile)
        self.assertIn('"/usr/bin/env","-i"', dockerfile)

    def test_input_path_type_and_budget_denied(self):
        for inputs in [
            {}, {"task.py": "not bytes"}, {"task.py": b"", "../host": b"x"},
            {"task.py": b"", "/abs": b""}, {"task.py": b"", "a/b": b""},
            {"task.py": b"x" * (worker.INPUT_LIMIT + 1)},
            {"task.py": b"", **{str(i): b"" for i in range(16)}},
        ]:
            with self.subTest(inputs=list(inputs)):
                with self.assertRaises(worker.BoundaryError):
                    worker.build_context(inputs)

    def test_fixed_configuration_has_no_host_binds_or_network(self):
        args = worker.create_args("owned", "image", "volume")
        self.assertEqual(args[args.index("--runtime") + 1], "live-worker-runsc")
        self.assertEqual(args[args.index("--network") + 1], "none")
        self.assertIn("--read-only", args)
        self.assertNotIn("--privileged", args)
        self.assertNotIn("--volume", args)
        self.assertIn("type=volume,src=volume,dst=/output,volume-nocopy", args)
        self.assertEqual(args[args.index("--cpus") + 1], "1")
        self.assertEqual(args[args.index("--pids-limit") + 1], "128")

    def test_output_regular_file_positive(self):
        data = archive_of([("output/description.md", tarfile.REGTYPE, b"# Synthetic")])
        self.assertEqual(worker.parse_output(data), {"output/description.md": b"# Synthetic"})

    def test_output_traversal_absolute_and_nested_denied(self):
        for name in ("../escape", "/output/a", "output/../a", "output/sub/a",
                     "output//../a", "other/a"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(worker.BoundaryError, "OUTPUT_MEMBER_DENIED"):
                    worker.parse_output(archive_of([(name, tarfile.REGTYPE, b"x")]))

    def test_output_links_and_special_files_denied(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE,
                     tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.DIRTYPE):
            with self.subTest(kind=kind):
                with self.assertRaises(worker.BoundaryError):
                    worker.parse_output(archive_of([("output/a", kind, b"")]))

    def test_output_duplicate_and_budgets_denied(self):
        for entries in [
            [("output/a", tarfile.REGTYPE, b"x")] * 2,
            [("output/a", tarfile.REGTYPE, b"x" * (worker.OUTPUT_LIMIT + 1))],
            [(f"output/{i}", tarfile.REGTYPE, b"") for i in range(17)],
        ]:
            with self.assertRaises(worker.BoundaryError):
                worker.parse_output(archive_of(entries))
        with self.assertRaisesRegex(worker.BoundaryError, "OUTPUT_ARCHIVE_TOO_LARGE"):
            worker.parse_output(b"x" * (worker.ARCHIVE_LIMIT + 1))

    def test_unsupported_host_is_non_green(self):
        with patch("worker.platform.system", return_value="Windows"):
            with self.assertRaisesRegex(worker.BoundaryError, "UNSUPPORTED_HOST"):
                worker.preflight()

    def test_missing_runtime_is_non_green(self):
        with patch("worker.platform.system", return_value="Linux"), \
                patch("worker.platform.machine", return_value="x86_64"), \
                patch("worker.Path.is_file", return_value=False):
            with self.assertRaisesRegex(worker.BoundaryError, "UNSUPPORTED_RUNTIME"):
                worker.preflight()

    def test_revocation_prevents_preparation_execution_and_export(self):
        instance = worker.Worker()
        instance.revoke()
        for operation in (lambda: instance.prepare({"task.py": b""}),
                          instance.run, instance.export):
            with self.assertRaises(worker.BoundaryError):
                operation()

    def test_runtime_failure_never_retries_with_docker(self):
        with patch("worker.subprocess.run") as run:
            run.return_value.returncode = 1
            run.return_value.stderr = b"runtime missing"
            with self.assertRaisesRegex(worker.BoundaryError, "DOCKER_FAILED"):
                worker.docker("start", "owned")
            self.assertEqual(run.call_count, 1)
            environment = run.call_args.kwargs["env"]
            self.assertEqual(set(environment), set(worker.SAFE_ENV))
            self.assertEqual(environment["HOME"], environment["DOCKER_CONFIG"])
            self.assertIn("live-worker-client-", environment["HOME"])
            self.assertFalse(worker.Path(environment["HOME"]).exists())

    def test_create_policy_mismatch_fails_closed(self):
        instance = worker.Worker()
        instance.inspection = {"HostConfig": {"Runtime": "runc"}, "Config": {}}
        with self.assertRaisesRegex(worker.BoundaryError, "CREATED_POLICY_MISMATCH"):
            instance.validate_created()

    def test_pins_are_exact(self):
        self.assertRegex(worker.LOCK["image"], r"@sha256:[0-9a-f]{64}$")
        self.assertRegex(worker.LOCK["bundle_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(worker.LOCK["files"]), 7)
        self.assertEqual(worker.LOCK["bundle_size"], 166822039)
        self.assertEqual(json.loads((worker.ROOT / "runtime.lock.json").read_text()),
                         worker.LOCK)


if __name__ == "__main__":
    unittest.main()
