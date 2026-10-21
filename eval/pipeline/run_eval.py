"""Compatibility entrypoint for offline evaluation preparation."""

import os
import sys

if __name__ == "__main__":
    # Re-exec before package imports. Initial plain-Python site startup has already
    # happened; launch with -I -S to exclude those hooks from the first process.
    if not (sys.flags.isolated and sys.flags.no_site):
        os.execv(sys.executable, [sys.executable, "-I", "-S", "-B", "-X", "utf8", *sys.argv])

    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from agile_eval.run_eval import main

    raise SystemExit(main())
