"""Synthetic payload: run unchanged as a host control and via Copilot's bash tool."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def attempt(operation):
    try:
        operation()
        return True
    except OSError:
        return False


def connect(host, port):
    with socket.create_connection((host, port), timeout=3):
        pass


def main():
    workspace, denied, ip, port = sys.argv[1:]
    workspace, denied = Path(workspace), Path(denied)
    result = {
        "uid": os.geteuid(),
        "namespaces": {name: os.readlink(f"/proc/self/ns/{name}")
                       for name in ("user", "mnt", "net")},
        "workspace_read": (workspace / "input").read_text() == "synthetic-input",
        "workspace_write": attempt(lambda: (workspace / "output").write_text("synthetic-output")),
        "command": subprocess.check_output(["/bin/sh", "-c", "printf synthetic-command"],
                                           text=True, timeout=5) == "synthetic-command",
        "outside_read": attempt(lambda: (denied / "sentinel").read_text()),
        "outside_write": attempt(lambda: (denied / "write-marker").write_text("synthetic")),
        "outbound": attempt(lambda: connect(ip, 443)),
        "localhost": attempt(lambda: connect("127.0.0.1", int(port))),
    }
    time.sleep(1)  # Give the host observer time to identify the real bwrap process.
    print("NATIVE_PROBE=" + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
