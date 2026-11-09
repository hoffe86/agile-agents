"""Disposable subprocess for gate integration tests; no external services."""

import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import time


mode = sys.argv[1]
if mode == "check":
    print(json.dumps(sys.argv[2:]))
    print("gate diagnostic", file=sys.stderr)
    sys.exit(int(sys.argv[2]))
if mode == "exit":
    print("startup diagnostic", file=sys.stderr, flush=True)
    sys.exit(int(sys.argv[2]) if len(sys.argv) > 2 else 7)
if mode == "wait":
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
    print("waiting diagnostic", flush=True)
    time.sleep(120)
elif mode == "hold-output":
    print("partial stdout", end="", flush=True)
    print("partial stderr", end="", file=sys.stderr, flush=True)
    Path(sys.argv[2]).write_text(str(os.getpid()), encoding="utf-8")
    time.sleep(120)
elif mode == "orphan":
    pid_file = Path(sys.argv[2])
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    child_pid_file = pid_file.with_suffix(".child")
    child = subprocess.Popen([sys.executable, __file__, "wait", str(child_pid_file)])
    deadline = time.monotonic() + 3
    while not child_pid_file.exists():
        if child.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("smoke descendant did not become ready")
        time.sleep(0.01)
    print("launcher stdout without newline", end="", flush=True)
    print("launcher stderr without newline", end="", file=sys.stderr, flush=True)
    # No wait/join/redirect: the child deliberately keeps both inherited pipes.
    sys.exit(7)
elif mode in ("serve", "tree", "hang", "redirect", "unhealthy"):
    port, pid_file = int(sys.argv[2]), Path(sys.argv[3])
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    if mode == "tree":
        child_pid_file = pid_file.with_suffix(".child")
        child = subprocess.Popen(
            [sys.executable, __file__, "wait", str(child_pid_file)]
        )
        deadline = time.monotonic() + 3
        while not child_pid_file.exists():
            if child.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("smoke descendant did not become ready")
            time.sleep(0.01)
    server = http.server.HTTPServer(("127.0.0.1", port), http.server.BaseHTTPRequestHandler)
    # Base handler returns 501; override only the minimal health behavior.
    def health(self):
        if mode == "hang":
            time.sleep(120)
        status = {"redirect": 302, "unhealthy": 503}.get(mode, 204)
        self.send_response(status)
        if mode == "redirect":
            self.send_header("Location", "/health")
        self.end_headers()
    server.RequestHandlerClass.do_GET = health
    server.serve_forever()
