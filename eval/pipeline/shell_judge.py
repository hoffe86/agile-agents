"""Compatibility forwarder, not a second judge backend."""

import os
import sys

if __name__ == "__main__":
    if not (sys.flags.isolated and sys.flags.no_site):
        os.execv(sys.executable, [sys.executable, "-I", "-S", "-B", "-X", "utf8", *sys.argv])

    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from agile_eval.score_workspace import main

    raise SystemExit(main())
