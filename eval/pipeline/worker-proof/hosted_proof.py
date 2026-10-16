"""Trusted no-model synthetic boundary tests; guest source is staged, never exec'd here."""

import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import unittest

from worker import BoundaryError, Worker, docker, preflight

ACTIVE = None


def cancel_owned(signum, frame):
    if ACTIVE is not None:
        ACTIVE.revoke()
    raise KeyboardInterrupt("Hosted job cancelled")


signal.signal(signal.SIGTERM, cancel_owned)
signal.signal(signal.SIGINT, cancel_owned)

# Deliberately synthetic. No host credential/transcript path is ever read.
CANARY = "SYNTHETIC_CONTROLLER_CANARY_not_a_credential"
GUEST_END = """
import time
time.sleep(120)
"""


class HostedWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.owned_names = set()
        cls.identities = preflight()
        print("IDENTITIES=" + json.dumps(cls.identities, sort_keys=True), flush=True)
        if cls.identities["runner_image"] == "not-reported":
            raise AssertionError("Actual hosted runner image version required")

    @classmethod
    def tearDownClass(cls):
        remaining = set(docker("ps", "-a", "--format", "{{.Names}}").decode().splitlines())
        leaked = remaining & cls.owned_names
        print("OWNED_CONTAINERS_REMAINING=" + json.dumps(sorted(leaked)), flush=True)
        if leaked:
            raise AssertionError("TASK_OWNED_CLEANUP_FAILED:" + ",".join(sorted(leaked)))

    def setUp(self):
        global ACTIVE
        self.worker = Worker()
        ACTIVE = self.worker
        self.addCleanup(self.worker.close)

    def launch(self, source, extra=None):
        global ACTIVE
        ACTIVE = self.worker
        self.owned_names.add(self.worker.name)
        self.worker.prepare({"task.py": (source + GUEST_END).encode(), **(extra or {})})
        self.worker.run()
        print("CONTAINER=" + json.dumps({
            "id": self.worker.inspection["Id"],
            "image": self.worker.inspection["Image"],
            "runtime": self.worker.inspection["HostConfig"]["Runtime"],
        }), flush=True)

    def result(self):
        files = self.worker.export()
        return json.loads(files["output/result.json"])

    def test_01_allowed_work_and_boundaries(self):
        with tempfile.TemporaryDirectory(prefix="live-worker-canary-") as tmp:
            canary = Path(tmp) / "host-canary.txt"
            canary.write_text(CANARY)
            # The host helper is trusted fixed harness code with only synthetic env.
            controller = subprocess.Popen(
                ["/usr/bin/sleep", "120"], env={"CONTROLLER_CANARY": CANARY})
            try:
                source = r'''
import ctypes, errno, json, os, pathlib, resource, socket, subprocess, sys
assert os.getuid() == 65532 and os.getgid() == 65532
assert set(os.environ) == {"PATH", "HOME", "TMPDIR", "LANG"}
libc = ctypes.CDLL(None, use_errno=True)
assert libc.prctl(21, 0, 0, 0, 0) == 2
assert libc.prctl(39, 0, 0, 0, 0) == 1
assert libc.prctl(38, 0, 0, 0, 0) == -1
assert ctypes.get_errno() == errno.EINVAL
denials = {}
def denied(name, operation, expected):
    try:
        operation()
    except OSError as exc:
        assert exc.errno in expected, (name, exc.errno, expected)
        denials[name] = exc.errno
    else:
        raise AssertionError("UNEXPECTED_ALLOW:" + name)
for family in (socket.AF_INET, socket.AF_INET6, socket.AF_UNIX, socket.AF_NETLINK):
    denied("socket_" + str(family), lambda: socket.socket(family), {errno.EPERM})
denied("socketpair", socket.socketpair, {errno.EPERM})
for number, name in ((42, "connect_loopback"), (42, "connect_metadata"),
                     (42, "connect_control_plane"), (425, "io_uring"),
                     (0x40000029, "x32_socket")):
    ctypes.set_errno(0)
    assert libc.syscall(number, -1, 0, 0, 0, 0, 0) == -1
    assert ctypes.get_errno() == errno.EPERM, (name, ctypes.get_errno())
    denials[name] = errno.EPERM
# No network packets are emitted: connect is denied even before fd/address checks.
for name, path in (
    ("host_file", HOST_CANARY), ("docker_socket", "/var/run/docker.sock"),
    ("runsc_control", "/run/runsc"), ("other_task", "/other-task/canary"),
    ("host_root", "/proc/1/root" + HOST_CANARY)):
    denied(name, lambda p=path: pathlib.Path(p).read_bytes(), {errno.ENOENT})
for path in ("/input/diff.txt", "/guest_bootstrap.py", "/usr/local/bin/denied"):
    denied("readonly_" + path, lambda p=path: pathlib.Path(p).write_text("x"),
           {errno.EROFS, errno.EACCES})
for entry in pathlib.Path("/proc").iterdir():
    if entry.name.isdecimal():
        for field in ("environ", "cmdline"):
            try:
                assert b"SYNTHETIC_CONTROLLER_CANARY" not in (entry / field).read_bytes()
            except (FileNotFoundError, PermissionError):
                pass
status = pathlib.Path("/proc/self/status").read_text()
assert "CapEff:\t0000000000000000" in status
assert not pathlib.Path("/scratch/previous-task").exists()
pathlib.Path("/scratch/allowed").write_text("allowed")
diff = pathlib.Path("/input/diff.txt").read_text()
assert diff == "synthetic: rename a heading\n"
pathlib.Path("/output/description.md").write_text("# Synthetic PR description\n\nRename a heading.\n")
child = subprocess.run([sys.executable, "-I", "-c",
    "import socket,errno;\\ntry: socket.socket()\\nexcept OSError as e: assert e.errno==errno.EPERM\\nelse: raise AssertionError('socket allowed')".replace("\\n", "\n")],
    capture_output=True, text=True)
assert child.returncode == 0, child.stderr
pathlib.Path("/output/result.json").write_text(json.dumps({
    "denials": denials, "child_socket_denied": True, "uid": os.getuid(),
    "rlimits": {"nproc": resource.getrlimit(resource.RLIMIT_NPROC),
                "as": resource.getrlimit(resource.RLIMIT_AS)}}))
'''.replace("HOST_CANARY", repr(str(canary)))
                self.launch(source, {"diff.txt": b"synthetic: rename a heading\n"})
                files = self.worker.export()
                self.assertEqual(files["output/description.md"],
                                 b"# Synthetic PR description\n\nRename a heading.\n")
                result = json.loads(files["output/result.json"])
                self.assertTrue(result["child_socket_denied"])
                self.assertGreaterEqual(len(result["denials"]), 18)
                print("BOUNDARIES=" + json.dumps(result, sort_keys=True), flush=True)
            finally:
                controller.terminate()
                controller.wait(timeout=5)

    def test_02_scratch_capacity(self):
        self.launch(r'''
import errno, json, os, pathlib
block = b"x" * (1024 * 1024)
written = 0
try:
    for index in range(40):
        with open("/scratch/block-" + str(index), "wb") as f:
            for _ in range(8):
                f.write(block)
                written += len(block)
except OSError as exc:
    assert exc.errno == errno.ENOSPC, exc
else:
    raise AssertionError("scratch bound did not fire")
assert 240 * 1024**2 <= written <= 256 * 1024**2, written
pathlib.Path("/output/result.json").write_text(json.dumps({"bytes": written, "errno": errno.ENOSPC}))
''')
        result = self.result()
        self.assertEqual(result["errno"], errno.ENOSPC)
        print("SCRATCH=" + json.dumps(result), flush=True)

    def test_03_memory_and_process_bounds(self):
        self.launch(r'''
import errno, json, os, pathlib, signal
try:
    value = bytearray(1100 * 1024**2)
except MemoryError:
    memory_denied = True
else:
    raise AssertionError("memory limit did not fire")
print("MEMORY_BOUND_DENIED:MemoryError", flush=True)
children = []
process_denied = False
try:
    for _ in range(132):  # bounded, worker-only, never a host fork bomb
        try:
            pid = os.fork()
        except OSError as exc:
            assert exc.errno == errno.EAGAIN, exc
            process_denied = True
            break
        if pid == 0:
            signal.pause()
            os._exit(0)
        children.append(pid)
        print("GUEST_CHILDREN=" + str(len(children)), flush=True)
finally:
    for pid in children:
        os.kill(pid, signal.SIGKILL)
    for pid in children:
        os.waitpid(pid, 0)
assert process_denied and len(children) < 128, len(children)
pathlib.Path("/output/result.json").write_text(json.dumps({
    "memory_denied": memory_denied, "children_before_eagain": len(children)}))
''')
        result = self.result()
        self.assertTrue(result["memory_denied"])
        self.assertLess(result["children_before_eagain"], 128)
        print("RESOURCES=" + json.dumps(result), flush=True)

    def test_11_memory_bound_independent_of_process_pressure(self):
        self.launch(r'''
import json, pathlib
positive = bytearray(1024**2)
assert len(positive) == 1024**2
try:
    value = bytearray(1100 * 1024**2)
except MemoryError:
    pass
else:
    raise AssertionError("memory limit did not fire")
pathlib.Path("/output/result.json").write_text(json.dumps({"memory_denied": True}))
''')
        self.assertTrue(self.result()["memory_denied"])

    def test_04_reset(self):
        self.launch(r'''
import pathlib
pathlib.Path("/scratch/previous-task").write_text("synthetic prior task")
pathlib.Path("/output/prior.txt").write_text("synthetic prior output")
''')
        first_volume = self.worker.volume
        self.worker.close()
        self.worker = Worker()
        self.addCleanup(self.worker.close)
        self.launch(r'''
import json, pathlib
assert not pathlib.Path("/scratch/previous-task").exists()
assert list(pathlib.Path("/output").iterdir()) == []
pathlib.Path("/output/result.json").write_text(json.dumps({"reset": True}))
''')
        self.assertNotEqual(first_volume, self.worker.volume)
        self.assertTrue(self.result()["reset"])

    def test_05_output_symlink_denied(self):
        self.launch('import os\nos.symlink("/input/task.py", "/output/leak")\n')
        with self.assertRaisesRegex(BoundaryError, "OUTPUT_MEMBER_DENIED"):
            self.worker.export()

    def test_06_output_fifo_denied(self):
        self.launch(r'''
import json, os, pathlib, stat
pathlib.Path("/output/permitted.txt").write_text("synthetic permitted output\n")
os.mkfifo("/output/fifo")
fifo_mode = os.lstat("/output/fifo").st_mode
regular_mode = os.lstat("/output/permitted.txt").st_mode
assert stat.S_ISFIFO(fifo_mode), fifo_mode
assert stat.S_ISREG(regular_mode), regular_mode
print("FIFO_GUEST_CREATED=" + json.dumps({
    "fifo": stat.S_IFMT(fifo_mode), "permitted.txt": stat.S_IFMT(regular_mode)
}), flush=True)
''')
        # Diagnostic only: the guest log is not a trusted filesystem inventory.
        # A host-volume walk cannot see gVisor's in-memory synthetic FIFO either.
        print(docker("logs", "--tail", "20", self.worker.name).decode(errors="replace"),
              flush=True)
        with self.assertRaisesRegex(BoundaryError, "OUTPUT_MEMBER_DENIED"):
            files = self.worker.export()
            print("FIFO_EXPORT_UNEXPECTEDLY_ACCEPTED=" + json.dumps({
                "names": sorted(files),
                "permitted_bytes_match": files.get("output/permitted.txt")
                == b"synthetic permitted output\n",
            }), flush=True)

    def test_07_output_budget_denied(self):
        self.launch('from pathlib import Path\nPath("/output/large").write_bytes(b"x" * (2*1024**2))\n')
        with self.assertRaisesRegex(BoundaryError, "OUTPUT_MEMBER_DENIED"):
            self.worker.export()

    def test_08_cancellation_descendants_and_revocation(self):
        self.launch(r'''
import os, signal
for _ in range(3):
    if os.fork() == 0:
        os.setsid()
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.pause()
        os._exit(0)
''')
        started = time.monotonic()
        self.worker.revoke()
        self.worker.close()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10)
        names = docker("ps", "-a", "--format", "{{.Names}}").decode().splitlines()
        self.assertNotIn(self.worker.name, names)
        for operation in (self.worker.run, lambda: self.worker.prepare({"task.py": b""})):
            with self.assertRaisesRegex(BoundaryError, "NEW_WORK_DENIED"):
                operation()
        print("CANCELLATION_SECONDS=" + str(elapsed), flush=True)

    def test_09_runtime_exit_is_non_green(self):
        with self.assertRaisesRegex(BoundaryError, "WORKER_EXITED:17"):
            self.launch("import os\nos._exit(17)\n")

    def test_10_operation_deadline(self):
        self.launch("import time\ntime.sleep(120)\n")
        self.worker.watchdog.join(timeout=68)
        self.assertFalse(self.worker.watchdog.is_alive())
        self.assertEqual(self.worker.failure, "OPERATION_DEADLINE")
        self.assertFalse(self.worker.created)
        self.assertLess(time.monotonic() - self.worker.started_at, 70)
        with self.assertRaisesRegex(BoundaryError, "EXPORT_DENIED"):
            self.worker.export()


if __name__ == "__main__":
    unittest.main(verbosity=2)
