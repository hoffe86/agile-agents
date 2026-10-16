"""Trusted preparation ONLY on a disposable GitHub-hosted Ubuntu 24.04 VM.

No task artifacts are executed here. Downloads are immutable official artifacts.
No local Windows/WSL/Desktop modifications are supported.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
LOCK = json.loads((ROOT / "runtime.lock.json").read_text())
INSTALL = Path("/usr/local/lib/live-worker-proof")
DAEMON = Path("/etc/docker/daemon.json")
RUNTIME = "live-worker-runsc"


def main():
    if (platform.system() != "Linux" or platform.machine() != "x86_64"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or os.geteuid() != 0):
        raise SystemExit("UNSUPPORTED: disposable hosted Linux amd64/root required")
    release = Path("/etc/os-release").read_text()
    if 'ID=ubuntu\n' not in release or 'VERSION_ID="24.04"' not in release:
        raise SystemExit("UNSUPPORTED: Ubuntu 24.04 required")
    if INSTALL.exists():
        raise SystemExit("FAIL_CLOSED: task-owned runtime directory already exists")
    with urllib.request.urlopen(LOCK["bundle_url"], timeout=120) as response:
        bundle = response.read(LOCK["bundle_size"] + 1)
    if len(bundle) != LOCK["bundle_size"]:
        raise SystemExit("FAIL_CLOSED: runtime bundle size mismatch")
    if hashlib.sha256(bundle).hexdigest() != LOCK["bundle_sha256"]:
        raise SystemExit("FAIL_CLOSED: runtime bundle checksum mismatch")
    # Validate every member and hash before writing; never extractall.
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(bundle), mode="r:bz2") as archive:
        for member in archive:
            if member.isdir() and member.name == "gvisor-bin":
                continue
            if (not member.isfile() or member.name not in LOCK["files"]
                    or member.name in contents or member.size > 128 * 1024**2):
                raise SystemExit("FAIL_CLOSED: unexpected runtime archive member")
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != LOCK["files"][member.name]:
                raise SystemExit("FAIL_CLOSED: runtime member checksum mismatch")
            contents[member.name] = data
    if set(contents) != set(LOCK["files"]):
        raise SystemExit("FAIL_CLOSED: incomplete runtime bundle")
    INSTALL.mkdir(mode=0o755)
    for name, data in contents.items():
        destination = INSTALL / name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(data)
        destination.chmod(0o755)
    config = json.loads(DAEMON.read_text()) if DAEMON.exists() else {}
    runtimes = config.setdefault("runtimes", {})
    if RUNTIME in runtimes:
        raise SystemExit("FAIL_CLOSED: runtime already registered")
    runtimes[RUNTIME] = {
        "path": str(INSTALL / "runsc"),
        "runtimeArgs": ["--platform=systrap", "--network=none"],
    }
    DAEMON.parent.mkdir(exist_ok=True)
    DAEMON.write_text(json.dumps(config, indent=2) + "\n")
    subprocess.run(["systemctl", "restart", "docker"], check=True, timeout=60)
    subprocess.run(["docker", "pull", "--platform=linux/amd64", LOCK["image"]],
                   check=True, timeout=240)
    subprocess.run([str(INSTALL / "runsc"), "--version"], check=True, timeout=10)
    print("PREPARATION_COMPLETE: pinned bundle and image; no model invocation")


if __name__ == "__main__":
    main()
