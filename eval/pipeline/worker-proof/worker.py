"""Trusted single-task launcher; fixed Docker/runsc policy, no SDK or model API.

Only input bytes cross into the worker. This module never runs their contents on
the host. The private Docker volume is an 8MiB tmpfs, NOT a host path bind.
"""

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
LOCK = json.loads((ROOT / "runtime.lock.json").read_text())
RUNTIME = "live-worker-runsc"
INSTALL = Path("/usr/local/lib/live-worker-proof")
INPUT_LIMIT = 1024**2
OUTPUT_LIMIT = 1024**2
ARCHIVE_LIMIT = 10 * 1024**2
OPERATION_SECONDS = 60
TASK_SECONDS = 15 * 60
SAFE_ENV = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/nonexistent", "DOCKER_CONFIG": "/nonexistent"}


class BoundaryError(RuntimeError):
    """A denied/unsupported operation. Never means a successful worker proof."""


def docker(*args, timeout=60, data=None):
    # Buildx needs a writable client home even for COPY-only local builds.
    # A fresh empty directory avoids reading/writing the real Docker credential
    # config. It is host preparation state and is never mounted into the guest.
    with tempfile.TemporaryDirectory(prefix="live-worker-client-") as home:
        environment = {**SAFE_ENV, "HOME": home, "DOCKER_CONFIG": home}
        result = subprocess.run(
            ["docker", "--host=unix:///var/run/docker.sock", *args],
            input=data, capture_output=True, env=environment, timeout=timeout)
    if result.returncode:
        # Runtime messages are diagnostic only, not trusted structured results.
        raise BoundaryError("DOCKER_FAILED:" + result.stderr[:4096].decode(errors="replace"))
    return result.stdout


def preflight():
    if platform.system() != "Linux" or platform.machine() != "x86_64":
        raise BoundaryError("UNSUPPORTED_HOST: Linux amd64 required")
    for name, expected in LOCK["files"].items():
        path = INSTALL / name
        if (not path.is_file() or path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
            raise BoundaryError("UNSUPPORTED_RUNTIME: missing or mismatched " + name)
    config = json.loads(Path("/etc/docker/daemon.json").read_text())
    expected = {"path": str(INSTALL / "runsc"),
                "runtimeArgs": ["--platform=systrap", "--network=none"]}
    if config.get("runtimes", {}).get(RUNTIME) != expected:
        raise BoundaryError("UNSUPPORTED_RUNTIME_CONFIG")
    info = json.loads(docker("info", "--format", "{{json .}}"))
    if (RUNTIME not in info["Runtimes"] or info["OSType"] != "linux"
            or info.get("CgroupVersion") != "2"):
        raise BoundaryError("UNSUPPORTED_DOCKER: runtime/cgroup v2 required")
    image = json.loads(docker("image", "inspect", LOCK["image"]))[0]
    if image["Architecture"] != "amd64" or image["Os"] != "linux":
        raise BoundaryError("UNSUPPORTED_IMAGE")
    return {
        "runner_image": os.environ.get("ImageVersion", "not-reported"),
        "runner_os": os.environ.get("ImageOS", "not-reported"),
        "kernel": platform.release(),
        "docker": json.loads(docker("version", "--format", "{{json .}}")),
        "runsc": subprocess.check_output([str(INSTALL / "runsc"), "--version"],
                                         env=SAFE_ENV, text=True, timeout=10).strip(),
        "runtime_sha256": LOCK["files"]["runsc"],
        "bundle_sha256": LOCK["bundle_sha256"],
        "platform": "systrap", "image": LOCK["image"], "image_id": image["Id"],
    }


def build_context(inputs):
    if (not isinstance(inputs, dict) or "task.py" not in inputs
            or len(inputs) > 16):
        raise BoundaryError("INPUT_SHAPE_DENIED")
    total = 0
    for name, data in inputs.items():
        if (not isinstance(name, str)
                or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", name)
                or not isinstance(data, bytes)):
            raise BoundaryError("INPUT_PATH_OR_TYPE_DENIED")
        total += len(data)
    if total > INPUT_LIMIT:
        raise BoundaryError("INPUT_TOO_LARGE")
    dockerfile = (
        f"FROM {LOCK['image']}\n"
        "COPY --chmod=0555 guest_bootstrap.py /guest_bootstrap.py\n"
        "COPY --chmod=0444 input/ /input/\n"
        "USER 65532:65532\n"
        "WORKDIR /scratch\n"
        'ENTRYPOINT ["/usr/bin/env","-i","PATH=/usr/local/bin:/usr/bin:/bin",'
        '"HOME=/scratch","TMPDIR=/scratch","LANG=C.UTF-8",'
        '"/usr/local/bin/python3","-I","-B","/guest_bootstrap.py"]\n'
    ).encode()
    members = {"Dockerfile": dockerfile,
               "guest_bootstrap.py": (ROOT / "guest_bootstrap.py").read_bytes(),
               **{"input/" + name: data for name, data in inputs.items()}}
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in members.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mode = 0o444
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def create_args(name, image, volume):
    # All options are trusted constants; only task-owned IDs vary.
    return [
        "create", "--name", name, "--runtime", RUNTIME, "--platform", "linux/amd64",
        "--network", "none", "--hostname", "worker", "--user", "65532:65532",
        "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges:true", "--ipc", "none",
        "--cgroupns", "private", "--cpus", "1", "--memory", "1g",
        "--memory-swap", "1g", "--pids-limit", "128",
        "--ulimit", "nofile=256:256", "--ulimit", "core=0:0",
        "--tmpfs", "/scratch:rw,noexec,nosuid,nodev,size=268435456,mode=0700,uid=65532,gid=65532",
        "--mount", f"type=volume,src={volume},dst=/output,volume-nocopy",
        "--log-driver", "local", "--log-opt", "max-size=1m",
        "--log-opt", "max-file=1", "--stop-timeout", "1", image,
    ]


def parse_output(archive_bytes):
    """Parse inert data from a FROZEN worker. Never extract or follow links."""
    if len(archive_bytes) > ARCHIVE_LIMIT:
        raise BoundaryError("OUTPUT_ARCHIVE_TOO_LARGE")
    result = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        for member in archive:
            if member.name in (".", "output", "output/") and member.isdir():
                continue
            path = PurePosixPath(member.name)
            if (len(path.parts) != 2 or path.parts[0] != "output"
                    or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", path.parts[1])
                    or not member.isfile() or member.name in result
                    or member.size < 0 or member.size > OUTPUT_LIMIT):
                raise BoundaryError("OUTPUT_MEMBER_DENIED")
            total += member.size
            if total > OUTPUT_LIMIT or len(result) >= 16:
                raise BoundaryError("OUTPUT_BUDGET_DENIED")
            result[member.name] = archive.extractfile(member).read()
    return result


class Worker:
    """One preparation, one operation. Revocation is terminal for this object."""

    def __init__(self):
        self.name = "live-worker-" + uuid.uuid4().hex
        self.volume = self.name + "-output"
        self.image = self.name + ":prepared"
        self.revoked = threading.Event()
        self.created = False
        self.volume_created = False
        self.image_created = False
        self.started_at = None
        self.inspection = None
        self.watchdog = None
        self.failure = None
        self.stop_lock = threading.Lock()

    def prepare(self, inputs):
        if self.revoked.is_set() or self.created:
            raise BoundaryError("NEW_WORK_DENIED")
        context = build_context(inputs)
        preflight()
        # No RUN, no host binds, no worker-controlled Dockerfile or build options.
        docker("build", "--network=none", "--pull=false", "--no-cache",
               "--tag", self.image, "-", data=context, timeout=240)
        self.image_created = True
        if self.revoked.is_set():
            raise BoundaryError("NEW_WORK_DENIED")
        docker("volume", "create", "--driver", "local", "--opt", "type=tmpfs",
               "--opt", "device=tmpfs", "--opt",
               "o=size=8388608,uid=65532,gid=65532,mode=0700,nosuid,nodev,noexec",
               self.volume)
        self.volume_created = True
        docker(*create_args(self.name, self.image, self.volume))
        self.created = True
        self.inspection = json.loads(docker("inspect", self.name))[0]
        self.validate_created()

    def validate_created(self):
        host = self.inspection["HostConfig"]
        config = self.inspection["Config"]
        if (host["Runtime"] != RUNTIME or host["NetworkMode"] != "none"
                or not host["ReadonlyRootfs"] or host["Privileged"]
                or host.get("Binds") or host.get("Devices")
                or host["CapDrop"] != ["ALL"] or host.get("CapAdd")
                or host["PidMode"] not in ("", "private")
                or config["User"] != "65532:65532"
                or host["NanoCpus"] != 1000000000
                or host["Memory"] != 1073741824 or host["MemorySwap"] != 1073741824
                or host["PidsLimit"] != 128):
            raise BoundaryError("CREATED_POLICY_MISMATCH")
        mounts = self.inspection["Mounts"]
        if len(mounts) != 1 or mounts[0].get("Name") != self.volume:
            raise BoundaryError("CREATED_MOUNT_MISMATCH")

    def revoke(self):
        # No new operation may start after this latch; run() checks every 100ms.
        self.revoked.set()

    def run(self):
        if self.revoked.is_set() or not self.created or self.started_at is not None:
            raise BoundaryError("NEW_WORK_DENIED")
        self.started_at = time.monotonic()
        docker("start", self.name, timeout=10)
        self.watchdog = threading.Thread(target=self._watch, daemon=True)
        self.watchdog.start()
        while True:
            if self.revoked.is_set():
                self.terminate()
                raise BoundaryError(self.failure or "CANCELLED")
            if time.monotonic() - self.started_at >= min(OPERATION_SECONDS, TASK_SECONDS):
                self.revoke()
                self.terminate()
                raise BoundaryError("OPERATION_DEADLINE")
            state = json.loads(docker("inspect", "--format", "{{json .State}}",
                                     self.name, timeout=5))
            if not state["Running"]:
                # Normal exit cannot export tmpfs safely through a live task.
                logs = docker("logs", "--tail", "20", self.name).decode(errors="replace")
                raise BoundaryError("WORKER_EXITED:" + str(state["ExitCode"]) + ":" + logs[:4096])
            # The guest writes result files then waits. Freeze before inspecting
            # output. Caller uses a trusted fixed wait (no guest readiness grants).
            if time.monotonic() - self.started_at >= 2:
                return
            time.sleep(0.1)

    def _watch(self):
        try:
            while not self.revoked.wait(0.1):
                if time.monotonic() - self.started_at >= min(OPERATION_SECONDS, TASK_SECONDS):
                    self.failure = "OPERATION_DEADLINE"
                    self.revoke()
            self.terminate()
        except Exception as exc:
            self.failure = "TERMINATION_FAILED:" + str(exc)

    def export(self):
        if self.revoked.is_set() or self.started_at is None:
            raise BoundaryError("EXPORT_DENIED")
        docker("pause", self.name, timeout=5)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", self.name))
        if not state["Running"] or not state["Paused"]:
            raise BoundaryError("FREEZE_FAILED")
        # A bounded reader; cap before buffering. Do not ask tar to extract.
        process = subprocess.Popen(
            ["docker", "--host=unix:///var/run/docker.sock", "cp",
             self.name + ":/output", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=SAFE_ENV)
        timer = threading.Timer(5, process.kill)
        timer.start()
        try:
            data = process.stdout.read(ARCHIVE_LIMIT + 1)
            if len(data) > ARCHIVE_LIMIT:
                raise BoundaryError("OUTPUT_ARCHIVE_TOO_LARGE")
            if process.wait(timeout=5) != 0:
                raise BoundaryError("OUTPUT_COPY_FAILED")
            return parse_output(data)
        finally:
            timer.cancel()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            process.stdout.close()
            self.terminate()

    def terminate(self):
        self.revoke()
        with self.stop_lock:
            if self.created:
                docker("rm", "--force", self.name, timeout=8)
                self.created = False

    def close(self):
        self.terminate()
        if self.watchdog is not None:
            self.watchdog.join(timeout=10)
            if self.watchdog.is_alive() or self.failure and self.failure.startswith("TERMINATION_FAILED"):
                raise BoundaryError(self.failure or "TERMINATION_NOT_CONFIRMED")
        if self.volume_created:
            docker("volume", "rm", self.volume)
            self.volume_created = False
        if self.image_created:
            docker("image", "rm", "--force", self.image)
            self.image_created = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
