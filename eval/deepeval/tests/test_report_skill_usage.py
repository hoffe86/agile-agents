"""Real pinned metric and CLI contracts for offline existing-output scoring."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from agile_eval.adapters.copilot_trace import parse_log_text, verify_schema
from agile_eval.report_skill_usage import main, measure_skills, score_logs

ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "eval/deepeval/report_skill_usage.py"
FIXTURE = Path(__file__).parent / "fixtures/skill-scoring-demo.jsonl"


def transcript(*skills):
    events = [
        {"type": "session.skills_loaded", "data": {"skills": [{"name": "skill-a"}, {"name": "skill-b"}]}},
        {"type": "assistant.turn_start", "data": {}},
        {"type": "tool.execution_start", "data": {"toolName": "view", "arguments": {"path": "unused"}}},
    ]
    events.extend(
        {"type": "tool.execution_start", "data": {"toolName": "skill", "arguments": {"skill": skill}}}
        for skill in skills
    )
    return "\n".join(json.dumps(event) for event in events)


@pytest.mark.parametrize("called,expected,score", [
    (["skill-a"], ["skill-a"], 1.0),
    (["skill-b"], ["skill-a"], 0.0),
    ([], ["skill-a"], 0.0),
    (["skill-a"], ["skill-a", "skill-b"], 0.5),
    (["skill-b", "skill-a", "skill-a", "extra-skill"], ["skill-a", "skill-b"], 1.0),
    (["skill-a"], ["skill-a", "skill-a"], 1.0),
])
def test_real_metric_measures_unique_skill_identities(called, expected, score, deepeval_module):
    assert measure_skills(parse_log_text(transcript(*called)), expected) == score


def test_metric_ignores_non_identity_arguments_and_prompt_secrets(deepeval_module):
    text = transcript("skill-a").replace('"skill": "skill-a"', '"skill": "skill-a", "token": "private-value"')
    assert measure_skills(parse_log_text(text), ["skill-a"]) == 1.0


@pytest.mark.parametrize("bad_event", [
    '{"type":"tool.execution_start","data":[]}',
    '{"type":"tool.execution_start","data":null}',
    '{"type":"tool.execution_start","data":{"toolName":2,"arguments":{}}}',
    '{"type":"tool.execution_start","data":{"toolName":"skill","arguments":"skill-a"}}',
    '{"type":"tool.execution_start","data":{"toolName":"skill","arguments":{}}}',
    '{"type":"tool.execution_start","data":{"toolName":"skill","arguments":{"skill":[]}}}',
    '{"type":"tool.execution_start","data":{"toolName":"skill","arguments":{"skill":" "}}}',
    '{"type":"session.skills_loaded","data":{"skills":"not-a-list"}}',
    '{"type":"session.skills_loaded","data":{"skills":[{}]}}',
    '{"type":"tool.renamed","data":{}}',
    '{"data":{}}',
    '{"type":[],"data":{}}',
    '{"type":"tool.execution_start","data":{},"data":{"toolName":"skill","arguments":{"skill":"skill-a"}}}',
    '{"type":"tool.execution_start","data":{"toolName":"skill","arguments":{"skill":"skill-a","extra":NaN}}}',
    "NaN",
    "[" * 1100 + "]" * 1100,
    '{"type":',
    '[]',
    'null',
    '[DRY RUN] fixture prepared; no agent or judge invoked. Live SDK execution held.',
])
def test_malformed_events_in_otherwise_valid_trace_are_visible_errors(bad_event):
    trace = parse_log_text(transcript("skill-a") + "\n" + bad_event)
    assert verify_schema(trace)
    with pytest.raises(ValueError, match="schema errors"):
        measure_skills(trace, ["skill-a"])


@pytest.mark.parametrize("expected", [[], [""], [" "]])
def test_metric_rejects_empty_expectations(expected):
    with pytest.raises(ValueError, match="expected skill"):
        measure_skills(parse_log_text(transcript("skill-a")), expected)


def cli(tmp_path, source, *args, isolated=False):
    # No actual credentials are inherited by test subprocesses.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH"}}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), APPDATA=str(tmp_path),
               LOCALAPPDATA=str(tmp_path), TEMP=str(tmp_path), TMP=str(tmp_path))
    return subprocess.run(
        [sys.executable, "-I", *(["-S"] if isolated else []), "-B", "-X", "utf8",
         str(CLI), str(source), *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
    )


@pytest.mark.parametrize("skills,code,status,score", [
    (["fixture-skill-a"], 0, "passed", 1.0),
    (["fixture-skill-b"], 1, "failed", 0.0),
    (["fixture-skill-a", "fixture-skill-b"], 1, "failed", 0.5),
])
def test_exact_cli_fixture_success_negative_and_partial(tmp_path, skills, code, status, score):
    output = tmp_path / "summary.json"
    args = [item for skill in skills for item in ("--expect-skill", skill)]
    result = cli(tmp_path, FIXTURE, "--score", *args, "--output", str(output))
    assert result.returncode == code, result.stdout + result.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["status"] == status
    assert report["passed"] is (code == 0)
    assert report["measured"] == report["total"] == 1
    assert report["results"][0]["score"] == score
    assert report["metric"] == "ToolCorrectnessMetric"
    assert report["deepeval_version"] == "4.1.8"


@pytest.mark.parametrize("text", [
    transcript("skill-a") + '\n{"type":"tool.execution_start","data":[]}',
    '[DRY RUN] fixture prepared; no agent or judge invoked. Live SDK execution held.',
    "",
    "not session output",
])
def test_exact_cli_schema_errors_are_not_failed_evaluations(tmp_path, text):
    source, output = tmp_path / "input.log", tmp_path / "summary.json"
    source.write_text(text, encoding="utf-8")
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["status"] == "schema_error"
    assert report["passed"] is None
    assert report["measured"] == 0
    assert report["results"][0]["score"] is None
    assert report["results"][0]["errors"]


def test_directory_includes_log_and_jsonl_but_excludes_cli_process_logs(tmp_path):
    logs, output = tmp_path / "logs", tmp_path / "summary.json"
    logs.mkdir()
    (logs / "a.log").write_text(transcript("skill-a"), encoding="utf-8")
    (logs / "b.jsonl").write_text(transcript("skill-b"), encoding="utf-8")
    (logs / ".copilot-home").mkdir()
    (logs / ".copilot-home/process.log").write_text("not a transcript", encoding="utf-8")
    result = cli(tmp_path, logs, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 1, result.stdout + result.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["total"] == report["measured"] == 2
    assert [row["score"] for row in report["results"]] == [1.0, 0.0]


def test_mixed_directory_keeps_measured_failure_distinct_from_schema_error(tmp_path, deepeval_module):
    valid, invalid = tmp_path / "a.log", tmp_path / "b.jsonl"
    valid.write_text(transcript("skill-b"), encoding="utf-8")
    invalid.write_text("[]", encoding="utf-8")
    report = score_logs([valid, invalid], ["skill-a"])
    assert report["status"] == "schema_error" and report["passed"] is None
    assert report["measured"] == 1
    assert [row["status"] for row in report["results"]] == ["failed", "schema_error"]


@pytest.mark.parametrize("empty_directory", [True, False])
def test_no_input_is_setup_error_not_success(tmp_path, empty_directory):
    output = tmp_path / "summary.json"
    source = tmp_path if empty_directory else tmp_path / "missing"
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["status"] == "setup_error" and report["passed"] is None
    assert report["total"] == report["measured"] == 0


def test_missing_deepeval_is_setup_error_with_no_fallback(tmp_path):
    output = tmp_path / "summary.json"
    result = cli(tmp_path, FIXTURE, "--score", "--expect-skill", "fixture-skill-a",
                 "--output", str(output), isolated=True)
    assert result.returncode == 2, result.stdout + result.stderr
    report = json.loads(output.read_text("utf-8"))
    assert report["status"] == "setup_error" and report["measured"] == 0
    assert report["results"][0]["score"] is None


@pytest.mark.parametrize("args", [
    ["--score", "--output", "summary.json"],
    ["--score", "--expect-skill", " "],
    ["--score", "--expect-skill", "skill-a"],
    ["--score", "--expect-skill", "skill-a", "--output", "summary.log"],
    ["--output", "summary.json"],
])
def test_scoring_requires_explicit_expectations_and_json_destination(tmp_path, args):
    assert cli(tmp_path, FIXTURE, *args).returncode == 2


def test_output_cannot_overwrite_input(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(transcript("skill-a"), encoding="utf-8")
    before = source.read_bytes()
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(source))
    assert result.returncode == 2
    assert source.read_bytes() == before


def test_output_cannot_overwrite_hardlinked_input(tmp_path):
    source, output = tmp_path / "input.log", tmp_path / "summary.json"
    source.write_text(transcript("skill-a"), encoding="utf-8")
    output.hardlink_to(source)
    assert output.samefile(source)
    before = source.read_bytes()
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 2, result.stdout + result.stderr
    assert "must not overwrite an input log" in result.stderr
    assert source.read_bytes() == output.read_bytes() == before


def test_existing_distinct_output_can_be_replaced_without_changing_input(tmp_path):
    source, output = tmp_path / "input.log", tmp_path / "summary.json"
    source.write_text(transcript("skill-a"), encoding="utf-8")
    output.write_text("old summary", encoding="utf-8")
    before = source.read_bytes()
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(output.read_text("utf-8"))["status"] == "passed"
    assert source.read_bytes() == before


@pytest.mark.parametrize("operation", ["stat", "samefile"])
def test_output_identity_check_failure_stops_before_scoring(
        tmp_path, monkeypatch, capsys, operation):
    source, output = tmp_path / "input.log", tmp_path / "summary.json"
    source.write_text(transcript("skill-a"), encoding="utf-8")
    output.write_text("existing summary", encoding="utf-8")
    before = source.read_bytes(), output.read_bytes()
    original = getattr(Path, operation)

    def fail_identity(path, *args, **kwargs):
        if path == output:
            raise PermissionError("PRIVATE-FILESYSTEM-DETAIL")
        return original(path, *args, **kwargs)

    def forbid_scoring(*args, **kwargs):
        pytest.fail("identity failure must stop before scoring")

    with monkeypatch.context() as patch:
        patch.setattr(Path, operation, fail_identity)
        patch.setattr("agile_eval.report_skill_usage.score_logs", forbid_scoring)
        assert main([str(source), "--score", "--expect-skill", "skill-a",
                     "--output", str(output)]) == 2
    assert (source.read_bytes(), output.read_bytes()) == before
    captured = capsys.readouterr()
    assert "cannot verify local JSON summary file identity" in captured.out
    assert "PRIVATE-" not in captured.out + captured.err


def test_invalid_utf8_and_unreadable_inputs_remain_errors(tmp_path):
    source = tmp_path / "invalid.log"
    source.write_bytes(b"\xff")
    report = score_logs([source, tmp_path / "missing"], ["skill-a"])
    assert report["status"] == "setup_error"
    assert [row["status"] for row in report["results"]] == ["schema_error", "setup_error"]
    assert report["measured"] == 0


def test_summary_write_failure_is_nonzero(tmp_path, capsys):
    destination = tmp_path / "directory.json"
    destination.mkdir()
    assert main([str(tmp_path / "missing"), "--score", "--expect-skill", "skill-a",
                 "--output", str(destination)]) == 2
    assert "cannot write local JSON summary" in capsys.readouterr().out


def test_metric_setup_error_is_sanitized(tmp_path, monkeypatch):
    from importlib import metadata

    def broken_version(_name):
        raise RuntimeError("PRIVATE-CONFIG")

    monkeypatch.setattr(metadata, "version", broken_version)
    report = score_logs([FIXTURE], ["fixture-skill-a"])
    assert report["status"] == "setup_error"
    assert report["results"][0]["score"] is None
    assert "PRIVATE-CONFIG" not in json.dumps(report)


def test_wrong_deepeval_version_is_setup_error(monkeypatch):
    from importlib import metadata

    monkeypatch.setattr(metadata, "version", lambda _name: "0.0.0")
    report = score_logs([FIXTURE], ["fixture-skill-a"])
    assert report["status"] == "setup_error" and report["measured"] == 0
    assert report["results"][0]["score"] is None


def test_schema_diagnostics_do_not_echo_malformed_event_contents(tmp_path):
    source = tmp_path / "PRIVATE-FILENAME.jsonl"
    output = tmp_path / "summary.json"
    source.write_text(transcript("skill-a") + '\n{"type":"tool.execution_start","data":["PRIVATE-EVENT"]}',
                      encoding="utf-8")
    result = cli(tmp_path, source, "--score", "--expect-skill", "skill-a", "--output", str(output))
    assert result.returncode == 2
    assert "PRIVATE-" not in output.read_text("utf-8") + result.stdout + result.stderr


def test_cold_scoring_audits_trusted_init_without_external_or_recorded_execution(tmp_path):
    # Audit before the first DeepEval import, including attempts caught by third-party
    # code. Run the actual CLI entrypoint, not a fake metric or an alternate runner.
    script = r"""
import os
from pathlib import Path
import runpy
import socket
import sys
root, owned = map(Path, sys.argv[1:])
source = owned / 'PRIVATE-FILENAME.jsonl'
source.write_text(
    (root / 'eval/deepeval/tests/fixtures/skill-scoring-demo.jsonl').read_text('utf-8')
    .replace('Fixture demonstration only.', 'PRIVATE-PROMPT')
    .replace('"skill":"fixture-skill-a"', '"skill":"fixture-skill-a","token":"PRIVATE-ARGUMENT"'),
    encoding='utf-8')
(owned / '.env').write_text('DEEPEVAL_UPDATE_WARNING_OPT_IN=1\nCONFIDENT_API_KEY=PRIVATE-DOTENV\n')
os.environ.update(DEEPEVAL_TELEMETRY_OPT_OUT='0', DEEPEVAL_UPDATE_WARNING_OPT_IN='1',
                  CONFIDENT_API_KEY='PRIVATE-KEY', OPENAI_API_KEY='PRIVATE-MODEL-KEY')
before = set(owned.rglob('*'))
output = owned / 'summary.json'
denied = []
trusted_init = []
platform_source = Path(os.__file__).with_name('platform.py')
shell = Path(os.environ['SystemRoot']) / 'System32/cmd.exe' if os.name == 'nt' else None
def called_from(module, function, source=None):
    frame = sys._getframe(1)
    while frame:
        if (frame.f_globals.get('__name__') == module
                and frame.f_code.co_name == function
                and (source is None or Path(frame.f_code.co_filename) == source)):
            return True
        frame = frame.f_back
    return False
def audit(event, args):
    # CPython 3.11 Windows metadata lookup: only the fixed stdlib "ver", not
    # arbitrary shell commands or anything taken from the recorded transcript.
    if (event == 'subprocess.Popen' and shell is not None
            and Path(args[0]) == shell
            and args[1] == f'{args[0]} /c "ver"'
            and args[2:] == (None, None)
            and called_from('platform', '_syscmd_ver', platform_source)):
        trusted_init.append('stdlib Windows version subprocess')
        return
    # urllib3's import-time IPv6 capability test binds loopback without connecting.
    # Do not mutate socket.has_ipv6 or create an asyncio/socketpair warmup.
    if (event == 'socket.bind' and args[1] == ('::1', 0)
            and args[0].family == socket.AF_INET6
            and called_from('urllib3.util.connection', '_has_ipv6')):
        trusted_init.append('urllib3 IPv6 loopback capability bind')
        return
    if event.startswith(('socket.connect', 'socket.bind', 'socket.getaddrinfo',
                         'socket.gethostby', 'socket.getnameinfo', 'socket.sendto',
                         'socket.sendmsg', 'subprocess.', 'os.system', 'os.exec',
                         'os.spawn', 'os.posix_spawn', 'os.fork')):
        denied.append(event)
        raise AssertionError('offline operation attempted')
sys.addaudithook(audit)
sys.argv = [str(root / 'eval/deepeval/report_skill_usage.py'), str(source), '--score',
            '--expect-skill', 'fixture-skill-a', '--output', str(output)]
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as result:
    assert result.code == 0
assert not denied, denied
assert os.environ['DEEPEVAL_TELEMETRY_OPT_OUT'] == '1'
assert 'PRIVATE-' not in output.read_text('utf-8')
assert set(owned.rglob('*')) - before == {output}
assert not any(name.startswith('copilot') for name in sys.modules)
from agile_eval.metrics.local_model import stub_model, StubModelCalled
try:
    stub_model().generate('never call a model')
except StubModelCalled:
    pass
else:
    raise AssertionError('stub must fail on call')
print('trusted initialization observed: ' + repr(trusted_init))
print('cold scoring: no forbidden attempts, cache, upload or private report data')
"""
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), APPDATA=str(tmp_path),
               LOCALAPPDATA=str(tmp_path), TEMP=str(tmp_path), TMP=str(tmp_path))
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-c", script, str(ROOT), str(tmp_path)],
        cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cold scoring: no forbidden attempts, cache, upload or private report data" in result.stdout
    assert "PRIVATE-" not in result.stdout + result.stderr
    print(result.stdout)
