"""Exercise actual pinned evaluate/BaseMetric offline, not a mocked framework."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_native_evaluate_maps_held_and_setup_results_without_network_models_or_cache(tmp_path):
    # Child isolation precedes imports. Ambient keys, .env, user config and site
    # hooks are unavailable; denied operations are recorded even if caught by a library.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), APPDATA=str(tmp_path),
               LOCALAPPDATA=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path),
               TEMP=str(tmp_path), TMP=str(tmp_path), DEEPEVAL_TELEMETRY_OPT_OUT="1",
               DEEPEVAL_NO_INSPECT_PROMPT="1")
    script = r"""
import sys
from pathlib import Path
root, owned = map(Path, sys.argv[1:])
sys.path.insert(0, str(root / 'eval/python'))
from agile_eval.run_eval import dependency_path
dependency_path()
# CPython 3.11's Windows platform probe runs `cmd /c ver`. Resolve this trusted
# stdlib OS metadata before denying subprocesses; no library/model is imported.
import platform
platform.uname()
import traceback
import socket
# urllib3 probes IPv6 by binding ::1 during import. Disable this capability in
# the offline test, rather than permitting a socket or weakening the deny hook.
socket.has_ipv6 = False
denied = []
def deny(event, args):
    if event.startswith(('socket.connect', 'socket.bind', 'socket.getaddrinfo',
                         'subprocess.', 'os.system')):
        denied.append((event, traceback.format_stack(limit=12)))
        raise AssertionError('offline native integration forbids ' + event)
sys.addaudithook(deny)
from importlib.metadata import version
assert version('deepeval') == '4.1.8'
from agile_eval.metrics.acceptance import AcceptanceMetric
from agile_eval.prepare_inputs import prepare
from deepeval import evaluate
from deepeval.metrics import BaseMetric
from deepeval.test_case import LLMTestCase
from deepeval.evaluate.configs import AsyncConfig, CacheConfig, DisplayConfig, ErrorConfig
task = root / 'eval/pipeline/custom-eval/tasks/task-10-helm-to-kustomize'
ws, baseline = owned / 'run/ws' / task.name, owned / 'run/baseline' / task.name
prepare(task, ws, baseline)
assert issubclass(AcceptanceMetric, BaseMetric)
assert CacheConfig().write_cache is True and CacheConfig().use_cache is False
for valid, expected in ((True, 'UNVERIFIED'), (False, 'SETUP_ERROR')):
    metric = AcceptanceMetric(task / 'acceptance.md', baseline_dir=baseline, threshold=0)
    result = evaluate(
        test_cases=[LLMTestCase(input='offline fixture', actual_output=str(ws if valid else owned / 'missing'))],
        metrics=[metric], official=False,
        async_config=AsyncConfig(run_async=False),
        cache_config=CacheConfig(write_cache=False, use_cache=False),
        display_config=DisplayConfig(show_indicator=False, print_results=False,
            inspect_after_run=False, results_folder=str(owned / 'native-results')),
        error_config=ErrorConfig(ignore_errors=False),
    )
    assert result.confident_link is None
    assert len(result.test_results) == 1
    outcome = result.test_results[0]
    assert outcome.success is False
    data, = outcome.metrics_data
    assert data.score == 0 and data.success is False
    assert ('verdict=' + expected) in data.reason
    assert metric.result.verdict.value == expected
    assert metric.result.exit_code == (3 if valid else 4)
assert not denied, denied
assert not any(name.startswith('copilot') for name in sys.modules)
assert not list(owned.rglob('*cached*'))
print('native framework: UNVERIFIED and SETUP_ERROR, no credit, calls or cache')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-X", "utf8", "-c", script, str(ROOT), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "native framework: UNVERIFIED and SETUP_ERROR" in result.stdout
