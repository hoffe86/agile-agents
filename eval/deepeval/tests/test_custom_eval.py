"""Offline tests for the DeepEval custom-eval pipeline (agile_eval.custom_eval).

No Copilot CLI, no network, no model: the trajectory metrics run DeepEval's
ToolCorrectnessMetric against a stub model, the judge is exercised with a fake.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from agile_eval.adapters.copilot_trace import parse_log
from agile_eval.custom_eval import judges, runner, scorer
from agile_eval.custom_eval.expectations import (
    Criterion,
    ExpectationsError,
    from_mapping,
    load,
    parse_acceptance,
)
from agile_eval.custom_eval.trajectory import (
    IMPLEMENTATION_AGENTS,
    check_plan_gate,
    delegated_agents,
    short_agent,
    skills_by_short_agent,
)

FIXTURE = Path(__file__).parent / "fixtures" / "copilot-subagent-session.jsonl"
TASKS = runner.default_tasks_root()
TASK_DIRS = sorted(p for p in TASKS.iterdir() if p.is_dir())
CRITERIA = (Criterion(1, "one"), Criterion(2, "two"))


def _base(**overrides) -> dict:
    data = {
        "schema": 1, "root_agent": "dev-lead", "plan_gate": "required",
        "agents": ["coding"], "skills": {"coding": ["testing-practices"]},
    }
    data.update(overrides)
    return data


@pytest.fixture(scope="module")
def trace():
    return parse_log(FIXTURE)


# --- expectations -----------------------------------------------------------------------

@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=lambda p: p.name)
def test_every_task_has_loadable_expectations(task_dir):
    exp = load(task_dir)
    assert exp.task == task_dir.name
    assert exp.plan_gate == "required"
    assert [c.id for c in exp.criteria] == list(range(1, len(exp.criteria) + 1))
    assert "reviewer-read-only-rules" in exp.skills["review-lead"]
    assert "code-review-checklist" in exp.forbidden_skills["review-lead"]


def test_parse_acceptance_joins_continuation_lines():
    criteria = parse_acceptance("# Title\n\n1. **A** first\n   continues\n2. second\n")
    assert criteria == (Criterion(1, "**A** first continues"), Criterion(2, "second"))


@pytest.mark.parametrize("text", ["", "# no list\n", "1. a\n3. b\n"])
def test_parse_acceptance_rejects_missing_or_gapped_numbering(text):
    with pytest.raises(ExpectationsError):
        parse_acceptance(text)


@pytest.mark.parametrize("overrides", [
    {"schema": 2},
    {"plan_gate": "sometimes"},
    {"surprise": True},
    {"skills": {}},
    {"skills": {"architect": ["x"]}},
    {"forbidden_skills": {"coding": ["testing-practices"]}},
    {"unverifiable": {9: "no such criterion"}},
])
def test_from_mapping_rejects_invalid_expectations(overrides):
    with pytest.raises(ExpectationsError):
        from_mapping(_base(**overrides), "t", CRITERIA)


def test_from_mapping_accepts_any_agent_and_known_unverifiable():
    exp = from_mapping(_base(skills={"any": ["pr-description"]}, unverifiable={2: "why"}),
                       "t", CRITERIA)
    assert exp.skills["any"] == ("pr-description",)
    assert exp.unverifiable == {2: "why"}


# --- trajectory + DeepEval metrics -------------------------------------------------------

def test_short_agent_strips_plugin_prefix_and_maps_top_level_to_root():
    assert short_agent("agile-agents-core:coding", "dev-lead") == "coding"
    assert short_agent(None, "dev-lead") == "dev-lead"


def test_fixture_attribution_and_gate_violation(trace):
    assert delegated_agents(trace, "dev-lead") == ["coding", "review-lead"]
    skills = skills_by_short_agent(trace, "dev-lead")
    assert "dev-lead-templates" in skills["dev-lead"]
    assert not skills.get("coding")
    gate = check_plan_gate(trace, IMPLEMENTATION_AGENTS)
    assert not gate.honoured
    assert "coding" in gate.violations[0]


def test_deepeval_metrics_score_skills_per_agent(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import delegation_metric, plan_gate_metric, skill_metrics

    exp = load(TASKS / "task-02-python-di-refactor")
    by_name = {m.name: m for m in skill_metrics(trace, exp)}
    assert by_name["skills:dev-lead"].passed is True
    assert by_name["skills:coding"].score == 0.0
    assert "python-implementation" in by_name["skills:coding"].reason
    assert "never delegated" in by_name["skills:code-reviewer"].reason
    delegation = delegation_metric(trace, exp)
    assert delegation.score == 0.5 and delegation.passed is False
    gate, _ = plan_gate_metric(trace, exp)
    assert gate.passed is False


def test_forbidden_skill_zeroes_the_agent_score(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(
        _base(agents=[], skills={"dev-lead": ["read-repo-context"]},
              forbidden_skills={"dev-lead": ["cost-budget"]}),
        "t", CRITERIA,
    )
    (metric,) = skill_metrics(trace, exp)
    assert metric.score == 0.0
    assert "forbidden skill invoked: cost-budget" in metric.reason


def test_any_agent_skill_is_satisfied_by_whoever_loads_it(trace):
    pytest.importorskip("deepeval")
    from agile_eval.custom_eval.metrics import skill_metrics

    exp = from_mapping(_base(agents=[], skills={"any": ["test-bar-gate"]}), "t", CRITERIA)
    (metric,) = skill_metrics(trace, exp)
    assert metric.passed is True


# --- judge ------------------------------------------------------------------------------

@pytest.mark.parametrize("statuses,verdict", [
    (["PASS", "PASS"], "RESOLVED"),
    (["FAIL", "FAIL"], "FAILED"),
    (["FAIL", "UNVERIFIED"], "FAILED"),
    (["PASS", "UNVERIFIED"], "UNVERIFIED"),
    (["PASS", "FAIL"], "PARTIAL"),
])
def test_verdict_rule(statuses, verdict):
    assert judges.verdict_for(statuses) == verdict


def test_parse_contract_recomputes_verdict_and_flags_contract_errors():
    good = judges.parse_contract("1. PASS - ok\n2. FAIL - bad\nVERDICT: RESOLVED", CRITERIA, "x")
    assert good.verdict == "PARTIAL" and good.claimed_verdict == "RESOLVED"
    assert not good.contract_errors
    bad = judges.parse_contract("1. PASS - ok\n1. PASS - again\n7. FAIL - ?", CRITERIA, "x")
    assert len(bad.contract_errors) == 4
    assert bad.criteria[1].status == "UNVERIFIED"


def test_none_judge_marks_every_criterion_unverified():
    result = judges.judge("none", "p", CRITERIA, {2: "known"}, "diff")
    assert result.verdict == "UNVERIFIED"
    assert [r.reason for r in result.criteria] == ["no judge configured", "known"]


def test_model_judge_cannot_credit_a_known_unverifiable_criterion(monkeypatch):
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - fine\n2. PASS - also fine\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    result = judges.judge("azure-openai", "task", CRITERIA, {2: "unresolved"}, "x" * 200_000)
    assert [r.status for r in result.criteria] == ["PASS", "UNVERIFIED"]
    assert result.verdict == "UNVERIFIED"
    assert "[evidence truncated]" in seen["prompt"]


def test_model_judge_hides_sdk_error_text(monkeypatch):
    class Exploding:
        def generate(self, prompt):
            raise RuntimeError("https://secret.example token=abc")

    monkeypatch.setattr(judges, "azure_openai_model", Exploding)
    with pytest.raises(judges.JudgeError) as info:
        judges.judge("azure-openai", "t", CRITERIA, {}, "d")
    assert "secret" not in str(info.value)


def test_azure_judge_requires_endpoint_configuration(monkeypatch):
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT", raising=False)
    with pytest.raises(judges.JudgeError, match="AZURE_OPENAI_ENDPOINT"):
        judges.azure_openai_model()


# --- runner -----------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@needs_git
def test_stage_copies_inputs_and_commits_a_baseline(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    assert len(baseline) == 40
    assert (paths.workspace / ".github" / "solution-profile.yaml").is_file()
    assert any(paths.workspace.rglob("*.py"))
    with pytest.raises(runner.SetupError, match="not empty"):
        runner.stage(TASKS / "task-02-python-di-refactor", paths)


@needs_git
def test_dry_run_records_a_redacted_command_and_needs_no_token(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    out = tmp_path / "run"
    assert runner.main(["task-05", "--out", str(out), "--dry-run", "--copilot", "copilot"]) == 0
    state = json.loads((out / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "dry_run"
    cmd = state["command"]
    assert "<prompt.md>" in cmd and cmd[cmd.index("--agent") + 1] == runner.ROOT_AGENT
    assert "--no-ask-user" in cmd and cmd.count("--plugin-dir") >= 1


def test_live_run_requires_explicit_unsandboxed_acknowledgement(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["task-05", "--out", str(tmp_path / "run")])


def test_run_phase_refuses_without_a_token(tmp_path, monkeypatch):
    monkeypatch.delenv("COPILOT_GITHUB_TOKEN", raising=False)
    with pytest.raises(runner.SetupError, match="COPILOT_GITHUB_TOKEN"):
        runner.run_phase(["copilot"], runner.Paths(tmp_path), 1, 10)


def test_phase2_without_approval_blocks_instead_of_running(tmp_path):
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-05", "status": "awaiting_approval",
                               "session_id": "s", "phases": {}})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed"]) == 0
    assert runner.read_state(paths)["status"] == "blocked_approval"


def test_phase2_refuses_a_run_that_is_not_awaiting_approval(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {"status": "gate_skipped"})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed", "--approve"]) == 4


# --- scorer -----------------------------------------------------------------------------

@pytest.mark.parametrize("args,expected", [
    (("setup_error", True, True, "RESOLVED"), "setup_error"),
    (("blocked_approval", True, True, "RESOLVED"), "unverified"),
    (("complete", False, True, "RESOLVED"), "failed"),
    (("complete", True, False, "RESOLVED"), "failed"),
    (("complete", True, True, "FAILED"), "failed"),
    (("complete", True, True, "PARTIAL"), "partial"),
    (("complete", None, True, "RESOLVED"), "resolved"),
])
def test_outcome(args, expected):
    assert scorer.outcome(*args) == expected


def test_aggregate_takes_the_worst_status():
    assert scorer.aggregate([{"status": "resolved"}, {"status": "partial"}]) == "partial"
    assert scorer.aggregate([{"status": "failed"}, {"status": "setup_error"}]) == "setup_error"
    assert scorer.aggregate([]) == "setup_error"


@needs_git
def test_score_recorded_run_end_to_end(tmp_path):
    pytest.importorskip("deepeval")
    run = tmp_path / "run"
    paths = runner.Paths(run)
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    shutil.copyfile(FIXTURE, paths.log(1))
    runner.write_state(paths, {"task": "task-02-python-di-refactor", "status": "complete",
                               "baseline": baseline, "session_id": "s", "phases": {}})
    (paths.workspace / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    runner.capture_diff(paths, baseline)
    output = tmp_path / "summary.json"

    code = scorer.main([str(run), "--judge", "none", "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    (row,) = report["results"]
    assert row["errors"] == []
    assert row["status"] == "failed" and code == scorer.EXIT["failed"]
    assert row["plan_gate"]["passed"] is False
    assert {m["name"] for m in row["trajectory"]} >= {"delegation", "skills:coding"}
    assert row["acceptance"]["verdict"] == "UNVERIFIED"
    assert row["usage"] == {"premiumRequests": 1}


def test_scoring_an_unreadable_run_is_a_setup_error(tmp_path):
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error" and row["errors"]


@needs_git
def test_capture_diff_includes_untracked_files(tmp_path):
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-05-pr-description", paths)
    (paths.workspace / "PR.md").write_text("hello\n", encoding="utf-8")
    runner.capture_diff(paths, baseline)
    assert "+hello" in scorer.produced_diff(paths)


@needs_git
def test_scorer_without_a_captured_diff_is_a_setup_error(tmp_path):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path / "run")
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    shutil.copyfile(FIXTURE, paths.log(1))
    runner.write_state(paths, {"task": "task-02-python-di-refactor", "status": "complete",
                               "baseline": baseline, "phases": {}})
    row = scorer.score_run(paths.run, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "produced.diff" in row["errors"][0]
