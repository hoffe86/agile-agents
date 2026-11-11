"""Run an explicitly synthetic agent through the custom-eval transport."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "python"))

from agile_eval.custom_eval import runner

runner.ROOT_AGENT = "eval-live-probe:probe-full"
runner.plugin_dirs = lambda _root: [HERE / "plugin"]

raise SystemExit(runner.main([*sys.argv[1:], "--tasks-root", str(HERE / "tasks")]))
