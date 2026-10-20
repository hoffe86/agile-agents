"""Bounded public apt diagnostics for this credential-free hosted proof only."""

import argparse
from collections import deque
import html
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit, urlunsplit


MAX_LINES = 60
MAX_LINE_CHARS = 500
MAX_REPORT_CHARS = 6000
APT_OPTIONS = [
    "-o", "Dir::Etc::sourcelist=/etc/apt/native-sandbox-proof.list",
    "-o", "Dir::Etc::sourceparts=-",
]


def sanitize(line):
    # No environment/config dumps. Strip terminal controls and defensively remove
    # URL credentials, queries, fragments, auth headers and common token forms.
    line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", line)
    line = "".join(c for c in line if c.isprintable() or c == "\t")

    def safe_url(match):
        try:
            url = urlsplit(match.group())
            host = url.netloc.rsplit("@", 1)[-1]
            return urlunsplit((url.scheme, host, url.path, "", ""))
        except ValueError:
            return "[redacted-url]"

    line = re.sub(r"https?://[^\s<>\"']+", safe_url, line)
    line = re.sub(
        r"(?i)\b(authorization|proxy-authorization|password|token|secret|api[_-]?key)"
        r"(\s*[:=]\s*).*", r"\1\2[redacted]", line,
    )
    line = re.sub(r"\b(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)\b",
                  "[redacted]", line)
    return line[:MAX_LINE_CHARS]


def report(phase, code, lines):
    tail = "\n".join(lines)[-MAX_REPORT_CHARS:]
    message = f"apt-get {phase} exit {code}; bounded sanitized output:\n{tail}"
    # Escape workflow command data so package output cannot inject commands.
    escaped = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    level = "error" if code else "warning"
    print(f"::{level} title=Native prerequisite {phase}::{escaped}", flush=True)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"\n### Native prerequisite {phase}\n<pre>"
                         f"{html.escape(message)}</pre>\n")


def run(phase):
    command = ["sudo", "apt-get", *APT_OPTIONS, phase]
    if phase == "install":
        command += ["--no-install-recommends", "-y",
                    "bubblewrap", "slirp4netns", "util-linux", "iptables"]
    lines = deque(maxlen=MAX_LINES)
    warning = False
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace") as process:
        for line in process.stdout:
            line = sanitize(line)
            lines.append(line)
            warning = warning or line.startswith(("W:", "E:", "Err:"))
        code = process.wait()
    if code or warning:
        report(phase, code, lines)
    else:
        print(f"apt-get {phase} completed successfully.", flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("update", "install"))
    args = parser.parse_args()
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted" or os.getuid() == 0:
        parser.error("Only the non-root disposable GitHub-hosted runner is supported")
    raise SystemExit(run(args.phase))
