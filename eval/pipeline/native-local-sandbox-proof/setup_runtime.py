"""Install only the integrity-checked native CLI into a disposable hosted directory."""

import hashlib
import io
import os
from pathlib import Path
import platform
import sys
import tarfile
import urllib.request

URL = "https://github.com/github/copilot-cli/releases/download/v1.0.98/copilot-linux-x64.tar.gz"
SHA256 = "87ddb4b3f98462b7cb13c0a6857c68ee410ec9673e2e5f64ee5bedad45825b05"
SIZE = 116812784


def require_hosted():
    if (platform.system() != "Linux" or platform.machine() != "x86_64"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
            or os.geteuid() == 0):
        raise RuntimeError("Requires non-root disposable GitHub-hosted Linux x86_64")


def verify(data):
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError("CLI archive integrity mismatch")


def main():
    require_hosted()
    destination = Path(sys.argv[1])
    destination.mkdir(mode=0o700)  # Refuse reuse.
    with urllib.request.urlopen(URL, timeout=120) as response:
        data = response.read(SIZE + 1)
    verify(data)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(destination, filter="data")
    if not (destination / "copilot").is_file():
        raise RuntimeError("Pinned archive has no expected copilot executable")
    print(f"CLI integrity verified: sha256:{SHA256}")


if __name__ == "__main__":
    main()
