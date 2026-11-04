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
from agile_eval.custom_eval import checks, judges, plan_approval, runner, scorer
from agile_eval.custom_eval.expectations import (
    Check,
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


def test_from_mapping_parses_checks_with_defaults():
    exp = from_mapping(_base(checks=[
        {"criterion": 1, "run": ["dotnet", "build"]},
        {"criterion": 1, "run": ["{python}", "-m", "pytest"], "cwd": "src/app", "timeout": 30,
         "requires": [["{python}", "-m", "pytest", "--version"]], "on_pass": "judge",
         "fail_if_output_matches": "Warning"},
    ]), "t", CRITERIA)
    assert exp.checks[0] == Check(1, ("dotnet", "build"))
    assert exp.checks[1].requires == (("{python}", "-m", "pytest", "--version"),)
    assert exp.checks[1].on_pass == "judge" and exp.checks[1].cwd == "src/app"


@pytest.mark.parametrize("check", [
    {"criterion": 9, "run": ["x"]},
    {"criterion": 2, "run": ["x"]},  # also declared unverifiable below
    {"criterion": True, "run": ["x"]},
    {"criterion": 1, "run": []},
    {"criterion": 1, "run": "dotnet build"},
    {"criterion": 1, "run": ["x"], "cwd": "../outside"},
    {"criterion": 1, "run": ["x"], "cwd": "/abs"},
    {"criterion": 1, "run": ["x"], "timeout": 0},
    {"criterion": 1, "run": ["x"], "on_pass": "maybe"},
    {"criterion": 1, "run": ["x"], "fail_if_output_matches": "("},
    {"criterion": 1, "run": ["x"], "requires": [[]]},
    {"criterion": 1, "run": ["x"], "shell": True},
])
def test_from_mapping_rejects_invalid_checks(check):
    with pytest.raises(ExpectationsError):
        from_mapping(_base(checks=[check], unverifiable={2: "why"}), "t", CRITERIA)


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


def test_model_judge_sees_command_results_as_evidence(monkeypatch):
    seen = {}

    class FakeModel:
        def generate(self, prompt):
            seen["prompt"] = prompt
            return "1. PASS - ok\n2. PASS - ok\nVERDICT: RESOLVED", 0.0

    monkeypatch.setattr(judges, "azure_openai_model", FakeModel)
    judges.judge("azure-openai", "t", CRITERIA, {}, "diff", command_evidence="BUILD-OUTPUT")
    assert "<command-results>\nBUILD-OUTPUT\n</command-results>" in seen["prompt"]


# --- command checks ---------------------------------------------------------------------

PY = "{python}"


def _run(tmp_path, check: Check) -> dict:
    (tmp_path / "ws").mkdir(exist_ok=True)
    return checks.run_check(check, 0, tmp_path / "ws", tmp_path, checks.check_env())


@pytest.mark.parametrize("check,status,reason", [
    (Check(1, (PY, "-c", "print('ok')")), "passed", "exit code 0"),
    (Check(1, (PY, "-c", "raise SystemExit(3)")), "failed", "exit code 3"),
    (Check(1, (PY, "-c", "print('x.bicep(1,2) : Warning no-unused: y')"),
           fail_if_output_matches=r"\(\d+,\d+\) : Warning "),
     "failed", "output matched the failure pattern"),
    (Check(1, ("no-such-tool-xyz", "build")), "unavailable", "no-such-tool-xyz is not installed"),
    (Check(1, (PY, "-c", "print(1)"), requires=((PY, "-c", "raise SystemExit(1)"),)),
     "unavailable", "failed"),
    (Check(1, (PY, "-c", "print(1)"), cwd="missing"), "failed", "does not exist"),
    (Check(1, (PY, "-c", "import time; time.sleep(30)"), timeout=1), "timeout", "timed out"),
])
def test_run_check_statuses(tmp_path, check, status, reason):
    result = _run(tmp_path, check)
    assert result["status"] == status
    assert reason in result["reason"]


def test_run_check_never_passes_credentials_to_agent_code(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "tok-secret")
    monkeypatch.setenv("AZURE_CLIENT_SECRET", "az-secret")
    script = "import os; print(sorted(k for k in os.environ if 'SECRET' in k or 'TOKEN' in k))"
    result = _run(tmp_path, Check(1, (PY, "-c", script)))
    assert result["status"] == "passed"
    assert "[]" in result["output_tail"] and "secret" not in result["output_tail"]


def test_run_checks_writes_matching_results(tmp_path):
    exp = from_mapping(_base(checks=[{"criterion": 2, "run": [PY, "-c", "print(2)"]}]),
                       "t", CRITERIA)
    (tmp_path / "ws").mkdir()
    checks.run_checks(exp, tmp_path / "ws", tmp_path)
    results = checks.load_results(tmp_path, exp)
    assert results and results[0]["status"] == "passed"
    assert (tmp_path / "checks" / "check-00.log").is_file()
    other = from_mapping(_base(checks=[{"criterion": 2, "run": [PY, "-c", "print(3)"]}]),
                         "t", CRITERIA)
    assert checks.load_results(tmp_path, other) is None


def _judgement(*statuses: str, reason: str = "judge says") -> judges.Judgement:
    rows = [judges.CriterionResult(i + 1, s, reason) for i, s in enumerate(statuses)]
    return judges.Judgement("j", rows, None, judges.verdict_for(list(statuses)), [])


def _result(index: int, criterion: int, status: str) -> dict:
    return {"index": index, "criterion": criterion, "command": f"cmd{index}", "status": status,
            "reason": "r", "cwd": "."}


@pytest.mark.parametrize("on_pass,statuses,judged,expected", [
    ("pass", ["passed"], "UNVERIFIED", "PASS"),
    ("pass", ["passed", "failed"], "PASS", "FAIL"),
    ("pass", ["passed", "timeout"], "PASS", "FAIL"),
    ("pass", ["passed", "unavailable"], "PASS", "UNVERIFIED"),
    ("judge", ["passed"], "FAIL", "FAIL"),
    ("judge", ["passed"], "PASS", "PASS"),
    ("judge", ["failed"], "PASS", "FAIL"),
])
def test_apply_checks_merge_rule(on_pass, statuses, judged, expected):
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": [f"cmd{i}"], "on_pass": on_pass}
                                     for i in range(len(statuses))]), "t", CRITERIA)
    results = [_result(i, 1, s) for i, s in enumerate(statuses)]
    judgement = _judgement(judged, "PASS")
    checks.apply_checks(judgement, exp, results)
    assert judgement.criteria[0].status == expected
    assert judgement.criteria[1].status == "PASS"
    assert judgement.verdict == judges.verdict_for([expected, "PASS"])


def test_apply_checks_without_results_leaves_checked_criteria_unverified():
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": ["x"]}]), "t", CRITERIA)
    judgement = _judgement("PASS", "PASS")
    checks.apply_checks(judgement, exp, None)
    assert judgement.criteria[0].status == "UNVERIFIED"
    assert "not run" in judgement.criteria[0].reason
    assert judgement.verdict == "UNVERIFIED"


def test_none_judge_gets_real_verdicts_from_commands():
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": ["a"]},
                                     {"criterion": 2, "run": ["b"], "on_pass": "judge"}]),
                       "t", CRITERIA)
    judgement = judges.judge("none", "p", CRITERIA, {}, "diff")
    checks.apply_checks(judgement, exp, [dict(_result(0, 1, "passed"), command="a"),
                                         dict(_result(1, 2, "passed"), command="b")])
    assert [r.status for r in judgement.criteria] == ["PASS", "UNVERIFIED"]
    assert judgement.criteria[1].reason == "commands passed; the remaining clause needs a judge"


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


def test_phase2_without_a_decision_fails_closed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-05", "status": "awaiting_approval",
                               "session_id": "s", "phases": {}})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed"]) == 4
    assert "run --phase approve first" in capsys.readouterr().out
    assert runner.read_state(paths)["status"] == "awaiting_approval"


def test_phase2_refuses_a_run_that_is_not_awaiting_approval(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {"status": "gate_skipped"})
    assert runner.main(["task-05", "--out", str(tmp_path), "--phase", "2",
                        "--unsandboxed"]) == 4


def test_verify_refuses_a_run_without_a_finished_change(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {"task": "task-02", "status": "awaiting_approval"})
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "verify",
                        "--unsandboxed"]) == 4
    assert not (tmp_path / checks.CHECKS_FILE).exists()


def test_verify_runs_agent_code_so_needs_the_unsandboxed_acknowledgement(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["task-02", "--out", str(tmp_path), "--phase", "verify"])


def test_runner_verify_records_check_counts_only_for_finished_runs(tmp_path):
    exp = from_mapping(_base(checks=[{"criterion": 1, "run": [PY, "-c", "print(1)"]},
                                     {"criterion": 2, "run": ["no-such-tool-xyz"]}]),
                       "t", CRITERIA)
    paths = runner.Paths(tmp_path)
    paths.workspace.mkdir()
    pending = {"status": "awaiting_approval"}
    runner._verify(exp, paths, pending)
    assert "checks" not in pending and not (tmp_path / checks.CHECKS_FILE).exists()
    done = {"status": "gate_skipped"}
    runner._verify(exp, paths, done)
    assert done["checks"] == {"passed": 1, "unavailable": 1}


# --- scorer -----------------------------------------------------------------------------

# --- simulated plan approval ------------------------------------------------------------

RUBRIC = TASKS.parent / plan_approval.RUBRIC_FILE


def _approver(monkeypatch, answer: str, seen: dict | None = None):
    class FakeModel:
        def generate(self, prompt):
            if seen is not None:
                seen["prompt"] = prompt
            return answer, 0.0

    monkeypatch.setattr(plan_approval, "azure_openai_model", FakeModel)


def _answer(*statuses: str) -> str:
    lines = [f"{i}. {s} - reason {i}" for i, s in enumerate(statuses, 1)]
    return "\n".join(lines + ["VERDICT: RESOLVED"])


def _plan_decision(*statuses: str) -> plan_approval.PlanDecision:
    criteria = tuple(Criterion(i, f"criterion {i}") for i in range(1, len(statuses) + 1))
    judgement = judges.parse_contract(_answer(*statuses), criteria, plan_approval.SIMULATED)
    return plan_approval.PlanDecision(plan_approval.SIMULATED,
                                      all(status == "PASS" for status in statuses), judgement)


def test_shared_rubric_loads_and_task_criteria_number_on():
    shared = plan_approval.load_rubric(RUBRIC)
    assert len(shared) >= 5
    combined = plan_approval.load_rubric(RUBRIC, ("names the risky migration",))
    assert combined[:-1] == shared
    assert combined[-1] == Criterion(len(shared) + 1, "names the risky migration")


def test_missing_rubric_is_an_expectations_error(tmp_path):
    with pytest.raises(ExpectationsError, match="rubric"):
        plan_approval.load_rubric(tmp_path / "nope.md")


def test_from_mapping_parses_plan_approval_and_requires_the_gate():
    exp = from_mapping(_base(plan_approval=["  lists the\n migration "]), "t", CRITERIA)
    assert exp.plan_approval == ("lists the migration",)
    with pytest.raises(ExpectationsError, match="plan_gate"):
        from_mapping(_base(plan_gate="not_applicable", plan_approval=["x"]), "t", CRITERIA)


def test_simulated_approver_approves_only_when_every_criterion_passes(monkeypatch):
    seen = {}
    _approver(monkeypatch, _answer("PASS", "PASS"), seen)
    decision = plan_approval.decide("REQ", CRITERIA, "PLAN <b>")
    assert decision.approved and decision.approver == plan_approval.SIMULATED
    assert "<requirement>\nREQ\n</requirement>" in seen["prompt"]
    assert "<plan>\nPLAN <b>\n</plan>" in seen["prompt"]
    assert "untrusted" in seen["prompt"]


@pytest.mark.parametrize("plan", [None, "", " \n"])
def test_missing_plan_is_rejected_without_a_model_call(tmp_path, monkeypatch, plan):
    monkeypatch.setattr(plan_approval, "azure_openai_model",
                        lambda: pytest.fail("judge ran without a plan"))
    decision = plan_approval.decide("requirement", CRITERIA, plan)
    assert decision.approved is False
    assert [row.status for row in decision.judgement.criteria] == ["UNVERIFIED", "UNVERIFIED"]
    assert decision.judgement.claimed_verdict is None
    plan_approval.write(tmp_path, decision)
    assert plan_approval.read(tmp_path, CRITERIA)["approved"] is False


def test_simulated_approver_requires_criteria():
    with pytest.raises(judges.JudgeError, match="at least one criterion"):
        plan_approval.decide("requirement", (), "plan")


@pytest.mark.parametrize("statuses", [("PASS", "FAIL"), ("PASS", "UNVERIFIED")])
def test_simulated_approver_rejects_a_failed_or_unverified_criterion(monkeypatch, statuses):
    _approver(monkeypatch, _answer(*statuses))
    assert plan_approval.decide("r", CRITERIA, "plan").approved is False


def test_simulated_approver_contract_break_is_a_judge_error_not_a_rejection(monkeypatch):
    _approver(monkeypatch, "looks good to me, approved")
    with pytest.raises(judges.JudgeError, match="contract"):
        plan_approval.decide("r", CRITERIA, "plan")


def test_simulated_approver_hides_sdk_error_text(monkeypatch):
    class Exploding:
        def generate(self, prompt):
            raise RuntimeError("https://secret.example token=abc")

    monkeypatch.setattr(plan_approval, "azure_openai_model", Exploding)
    with pytest.raises(judges.JudgeError) as info:
        plan_approval.decide("r", CRITERIA, "plan")
    assert "secret" not in str(info.value)


@pytest.mark.parametrize("content", [
    "not json", json.dumps([]), json.dumps({"approver": "human", "approved": True}),
    json.dumps({"approver": plan_approval.SIMULATED, "approved": "yes"}),
    json.dumps({"approver": plan_approval.SIMULATED, "approved": True}),
])
def test_read_ignores_records_that_are_not_a_simulated_decision(tmp_path, content):
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(content, encoding="utf-8")
    assert plan_approval.read(tmp_path) is None


@pytest.mark.parametrize(("statuses", "approved", "valid"), [
    (("PASS", "PASS"), True, True),
    (("PASS", "FAIL"), False, True),
    (("PASS", "UNVERIFIED"), False, True),
    (("PASS", "FAIL"), True, False),
    (("PASS", "PASS"), False, False),
    (("PASS",), True, False),
])
def test_read_requires_a_complete_and_consistent_judgement(tmp_path, statuses, approved, valid):
    record = _plan_decision(*statuses).to_dict()
    record["approved"] = approved
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(json.dumps(record), encoding="utf-8")
    assert (plan_approval.read(tmp_path, CRITERIA) is not None) is valid


def test_read_rejects_duplicate_criterion_ids(tmp_path):
    record = _plan_decision("PASS", "PASS").to_dict()
    record["judgement"]["criteria"][1]["id"] = 1
    (tmp_path / plan_approval.APPROVAL_FILE).write_text(json.dumps(record), encoding="utf-8")
    assert plan_approval.read(tmp_path, CRITERIA) is None


def _awaiting(tmp_path) -> runner.Paths:
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {"task": "task-02-python-di-refactor",
                               "status": "awaiting_approval", "session_id": "s",
                               "plan_message": "the plan", "phases": {}})
    return paths


@pytest.mark.parametrize("status", ["PASS", "FAIL"])
def test_phase_approve_records_the_decision_and_runs_no_agent(tmp_path, monkeypatch, status):
    n = len(plan_approval.load_rubric(RUBRIC))
    _approver(monkeypatch, _answer(*([status] * n)))
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path)
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 0
    state = runner.read_state(paths)
    approved = status == "PASS"
    assert state["status"] == ("awaiting_approval" if approved else "plan_rejected")
    assert state["plan_approval"]["approved"] is approved
    assert plan_approval.read(tmp_path)["approved"] is approved


@pytest.mark.parametrize("old_option", [("--approver", "human"), ("--approve",)])
def test_human_approval_options_are_not_available(tmp_path, old_option, capsys):
    with pytest.raises(SystemExit) as exc:
        runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve", *old_option])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err


def test_phase_approve_judge_failure_is_a_setup_error(tmp_path, monkeypatch):
    _approver(monkeypatch, "garbage")
    paths = _awaiting(tmp_path)
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "approve"]) == 4
    assert runner.read_state(paths)["status"] == "awaiting_approval"
    assert plan_approval.read(tmp_path) is None


def test_phase2_stops_on_a_recorded_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path)
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision("FAIL", *(["PASS"] * (count - 1))))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 0
    assert runner.read_state(paths)["status"] == "plan_rejected"


def test_phase2_refuses_an_approval_missing_a_rubric_criterion(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "run_phase", lambda *a, **k: pytest.fail("agent ran"))
    paths = _awaiting(tmp_path)
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision(*(["PASS"] * (count - 1))))
    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 4
    assert runner.read_state(paths)["status"] == "awaiting_approval"


def test_phase2_uses_an_approved_record_without_calling_the_judge(tmp_path, monkeypatch):
    paths = _awaiting(tmp_path)
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision(*(["PASS"] * count)))
    monkeypatch.setattr(plan_approval, "decide", lambda *a, **k: pytest.fail("judge ran"))
    calls = []

    def run_phase(cmd, paths, phase, timeout):
        calls.append((phase, cmd))
        shutil.copyfile(FIXTURE, paths.log(phase))
        return 0

    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--phase", "2", "--unsandboxed"]) == 0
    state = runner.read_state(paths)
    assert state["status"] == "complete" and state["approved_by"] == plan_approval.SIMULATED
    assert len(calls) == 1 and calls[0][0] == 2
    assert runner.APPROVAL_MESSAGE in calls[0][1]


@pytest.mark.parametrize(("status", "expected_status", "approved_by", "expected_calls"), [
    ("PASS", "complete", plan_approval.SIMULATED, [2]),
    ("FAIL", "plan_rejected", None, []),
    ("UNVERIFIED", "plan_rejected", None, []),
])
def test_all_phases_automatically_use_the_simulated_approver(
        tmp_path, monkeypatch, status, expected_status, approved_by, expected_calls):
    count = len(plan_approval.load_rubric(RUBRIC))
    _approver(monkeypatch, _answer(*([status] * count)))

    def phase1(args, task_dir, paths):
        return runner.read_state(_awaiting(paths.run))

    calls = []

    def run_phase(cmd, paths, phase, timeout):
        calls.append(phase)
        shutil.copyfile(FIXTURE, paths.log(phase))
        return 0

    monkeypatch.setattr(runner, "phase1", phase1)
    monkeypatch.setattr(runner, "run_phase", run_phase)
    monkeypatch.setattr(runner, "_capture", lambda *a: None)
    monkeypatch.setattr(runner, "_verify", lambda *a: None)

    assert runner.main(["task-02", "--out", str(tmp_path), "--unsandboxed"]) == 0
    state = runner.read_state(runner.Paths(tmp_path))
    assert state["status"] == expected_status
    assert state.get("approved_by") == approved_by
    assert calls == expected_calls


@pytest.mark.parametrize("args,expected", [
    (("setup_error", True, True, "RESOLVED"), "setup_error"),
    (("plan_rejected", True, True, "RESOLVED"), "failed"),
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
def test_score_recorded_run_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("deepeval")
    run = tmp_path / "run"
    paths = runner.Paths(run)
    baseline = runner.stage(TASKS / "task-02-python-di-refactor", paths)
    shutil.copyfile(FIXTURE, paths.log(1))
    runner.write_state(paths, {"task": "task-02-python-di-refactor", "status": "gate_skipped",
                               "baseline": baseline, "session_id": "s", "phases": {}})
    (paths.workspace / "new_file.py").write_text("x = 1\n", encoding="utf-8")
    runner.capture_diff(paths, baseline)
    exp = load(TASKS / "task-02-python-di-refactor")
    recorded = [{"index": i, "criterion": c.criterion, "command": checks.display(c.run),
                 "cwd": c.cwd, "status": "passed" if c.criterion == 3 else "failed",
                 "reason": "r", "output_tail": "tail"} for i, c in enumerate(exp.checks)]
    (run / checks.CHECKS_FILE).write_text(json.dumps({"schema": 1, "results": recorded}),
                                          encoding="utf-8")
    output = tmp_path / "summary.json"

    code = scorer.main([str(run), "--judge", "none", "--output", str(output)])

    report = json.loads(output.read_text(encoding="utf-8"))
    (row,) = report["results"]
    assert row["errors"] == []
    assert row["status"] == "failed" and code == scorer.EXIT["failed"]
    assert row["plan_gate"]["passed"] is False
    assert {m["name"] for m in row["trajectory"]} >= {"delegation", "skills:coding"}
    statuses = {r["id"]: r["status"] for r in row["acceptance"]["criteria"]}
    assert statuses == {1: "UNVERIFIED", 2: "UNVERIFIED", 3: "UNVERIFIED", 4: "FAIL",
                        5: "UNVERIFIED"}
    assert row["acceptance"]["verdict"] == "FAILED"
    assert [c["status"] for c in row["checks"]] == ["passed", "failed"]
    assert "output_tail" not in row["checks"][0]
    assert row["usage"] == {"premiumRequests": 1}

    (run / checks.CHECKS_FILE).unlink()
    row = scorer.score_run(run, "none", TASKS)
    assert row["acceptance"]["verdict"] == "UNVERIFIED"
    assert row["checks"] is None and "--phase verify" in row["errors"][0]

    # CI: the approve job's rejection sits beside a state.json still awaiting it.
    runner.write_state(paths, {**runner.read_state(paths), "status": "awaiting_approval"})
    assert scorer.score_run(run, "none", TASKS)["status"] == "unverified"
    (run / plan_approval.APPROVAL_FILE).write_text(
        json.dumps({"approver": plan_approval.SIMULATED, "approved": True}), encoding="utf-8")
    row = scorer.score_run(run, "none", TASKS)
    assert row["status"] == "setup_error" and "invalid plan-approval.json" in row["errors"]

    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(run, _plan_decision("FAIL", *(["PASS"] * (count - 1))))
    real_judge = scorer.judge

    def no_acceptance_model(name, *args, **kwargs):
        assert name == "none"
        return real_judge(name, *args, **kwargs)

    monkeypatch.setattr(scorer, "judge", no_acceptance_model)
    row = scorer.score_run(run, "azure-openai", TASKS)
    assert row["status"] == "failed"
    assert row["plan_approval"]["passed"] is False
    assert row["acceptance"]["judge"] == "none"


def test_scorer_requires_approval_for_a_completed_run_with_a_required_gate(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {
        "task": "task-02-python-di-refactor", "status": "complete",
    })
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "missing plan-approval.json" in row["errors"]


def test_scorer_rejects_a_completed_run_with_a_rejected_plan(tmp_path):
    runner.write_state(runner.Paths(tmp_path), {
        "task": "task-02-python-di-refactor", "status": "complete",
    })
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision("FAIL", *(["PASS"] * (count - 1))))
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "recorded plan decision conflicts with the run state" in row["errors"]


def test_scorer_accepts_a_completed_run_with_a_valid_simulated_approval(tmp_path):
    pytest.importorskip("deepeval")
    paths = runner.Paths(tmp_path)
    runner.write_state(paths, {
        "task": "task-02-python-di-refactor", "status": "complete",
        "approved_by": plan_approval.SIMULATED,
    })
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(tmp_path, _plan_decision(*(["PASS"] * count)))
    shutil.copyfile(FIXTURE, paths.log(1))
    paths.diff.write_text("synthetic diff\n", encoding="utf-8")
    row = scorer.score_run(tmp_path, "none", TASKS)
    assert row["status"] == "failed"
    assert row["plan_approval"]["passed"] is True
    assert row["plan_gate"]["passed"] is False


def test_approval_metric_lists_the_failing_criteria():
    decision = plan_approval.PlanDecision(
        plan_approval.SIMULATED, False, _judgement("PASS", "FAIL", reason="no risks")).to_dict()
    metric = scorer.approval_metric(decision)
    assert metric["name"] == "Plan approval (llm-simulated)"
    assert metric["passed"] is False and metric["score"] == 0.5
    assert metric["reason"] == "rejected: 2. FAIL - no risks"


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
    count = len(plan_approval.load_rubric(RUBRIC))
    plan_approval.write(paths.run, _plan_decision(*(["PASS"] * count)))
    row = scorer.score_run(paths.run, "none", TASKS)
    assert row["status"] == "setup_error"
    assert "produced.diff" in row["errors"][0]
