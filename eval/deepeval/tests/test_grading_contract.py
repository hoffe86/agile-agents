"""Strict, model-free contract tests shared by both scoring paths."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from grading import (
    Verdict, acceptance_count, artifact_dump, has_unverified, immutable_inputs,
    parse_result, result_status, write_result,
)


@pytest.mark.parametrize("statuses,claimed,want,exit_code", [
    (["PASS"], "RESOLVED", Verdict.RESOLVED, 0),
    (["PASS", "FAIL"], "RESOLVED", Verdict.PARTIAL, 2),
    (["FAIL"], "RESOLVED", Verdict.FAILED, 1),
    (["UNVERIFIED"], "RESOLVED", Verdict.UNVERIFIED, 3),
    (["UNVERIFIED", "UNVERIFIED"], "UNVERIFIED", Verdict.UNVERIFIED, 3),
    (["PASS", "UNVERIFIED"], "PARTIAL", Verdict.UNVERIFIED, 3),
    (["PASS", "FAIL", "UNVERIFIED"], "RESOLVED", Verdict.UNVERIFIED, 3),
    (["FAIL", "UNVERIFIED"], "UNVERIFIED", Verdict.FAILED, 1),
])
def test_normalization_preserves_verified_failures_and_uncertainty(statuses, claimed, want, exit_code):
    text = "\n".join(f"{i}. {s} - evidence {i}" for i, s in enumerate(statuses, 1))
    result = parse_result(text + f"\nVERDICT: {claimed}", len(statuses))
    assert result.verdict is want
    assert result.exit_code == exit_code
    assert result.claimed_verdict == claimed
    assert [c["status"] for c in result.criteria] == statuses
    assert result.complete == ("UNVERIFIED" not in statuses)
    assert result.to_dict()["contract_valid"]
    assert result.to_dict()["verified_failures"] == [
        i for i, s in enumerate(statuses, 1) if s == "FAIL"
    ]
    if "UNVERIFIED" in statuses:
        assert result.unverified and result.score == 0
        assert any("evidence" in reason for reason in result.reasons)


@pytest.mark.parametrize("text", [
    "VERDICT: RESOLVED",
    "1. PASS - ok",
    "1. PASS - ok\nVERDICT: RESOLVED\nVERDICT: FAILED",
    "1. PASS - ok\n1. PASS - duplicate\nVERDICT: RESOLVED",
    "2. PASS - wrong id\nVERDICT: RESOLVED",
    "1. PASS - ok\n2. PASS - extra\nVERDICT: RESOLVED",
    "1. PASS - ok\nVERDICT: MAYBE",
    "1. PASS - ok\nVERDICT: RESOLVED extra",
    "1. PASS - ok\nVERDICT: RESOLVED\ntrailing prose",
    "1. UNVERIFIED\nVERDICT: RESOLVED",
    "1. PASS - ok\n1. UNKNOWN - bad\nVERDICT: RESOLVED",
    "prose says 1. PASS - ok and VERDICT: RESOLVED",
])
def test_malformed_contract_is_judge_error_not_agent_failure(text):
    result = parse_result(text, 1)
    assert result.verdict is Verdict.SETUP_ERROR
    assert result.exit_code == 4
    assert result.score == 0 and not result.complete
    assert result.error_kind == "judge_contract" and result.reasons


def test_status_words_in_prose_are_not_criterion_statuses():
    text = "UNVERIFIED was discussed; FAIL is not a result.\n1. PASS - no unverified work\nVERDICT: RESOLVED"
    assert not has_unverified(text)
    assert parse_result(text, 1).verdict is Verdict.RESOLVED


def test_nonzero_judge_exit_overrides_resolved_text_without_losing_claim():
    result = parse_result("1. PASS - ok\nVERDICT: RESOLVED", 1, judge_exit=19)
    assert result.claimed_verdict == "RESOLVED"
    assert result.verdict is Verdict.SETUP_ERROR
    assert result.judge_exit == 19 and result.error_kind == "judge_cli"


@pytest.mark.parametrize("text", ["", "1. criterion\n3. gap", "1. a\n1. duplicate"])
def test_acceptance_count_rejects_invalid_actual_criteria(text):
    with pytest.raises(ValueError):
        acceptance_count(text)


def test_count_all_actual_fixture_criteria():
    tasks = Path(__file__).resolve().parents[2] / "pipeline/custom-eval/tasks"
    counts = {p.parent.name: acceptance_count(p.read_text(encoding="utf-8"))
              for p in tasks.glob("*/acceptance.md")}
    assert len(counts) == 10
    assert counts["task-10-helm-to-kustomize"] == 5


def test_result_consumer_rechecks_completeness_and_actual_acceptance(tmp_path):
    path = tmp_path / "result.json"
    acceptance = tmp_path / "acceptance.md"
    acceptance.write_text("1. Criterion", encoding="utf-8")
    result = parse_result("1. UNVERIFIED - missing helm\nVERDICT: RESOLVED", 1)
    write_result(result, path)
    assert result_status(path, 3, acceptance) == "unverified"
    assert result_status(path, 0, acceptance) == "setup_error"
    data = json.loads(path.read_text())
    data.update(status="resolved", score=1, complete=True, exit_code=0)
    path.write_text(json.dumps(data))
    assert result_status(path, 0, acceptance) == "setup_error"
    write_result(parse_result("1. PASS - ok\nVERDICT: RESOLVED", 1), path)
    acceptance.write_text("1. Criterion\n2. Missing", encoding="utf-8")
    assert result_status(path, 0, acceptance) == "setup_error"


def test_artifacts_include_workflows_but_not_secrets_internal_inputs_or_builds(tmp_path):
    for name in [".github/workflows/deploy.yml", ".github/CODEOWNERS", "README.md"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("deliverable", encoding="utf-8")
    for name in [".github/eval-inputs.json", ".github/solution-profile.yaml", ".env",
                 ".copilot/config.json", ".copilot-runs/log.md", "bin/output.txt", "secret.key"]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("NEVER_INLINE_THIS", encoding="utf-8")
    dump = artifact_dump(tmp_path)
    assert ".github/workflows/deploy.yml" in dump and ".github/CODEOWNERS" in dump
    assert "NEVER_INLINE_THIS" not in dump


@pytest.mark.parametrize("threshold", [0, 0.5, 1])
def test_metric_never_succeeds_for_unverified_even_at_permissive_threshold(tmp_path, monkeypatch, threshold):
    from metrics import acceptance
    monkeypatch.setattr(acceptance, "run_judge", lambda *a, **kw: parse_result(
        "1. UNVERIFIED - tool missing\nVERDICT: RESOLVED", 1,
    ))
    metric = acceptance.AcceptanceMetric(tmp_path / "ac.md", threshold=threshold)
    case = type("Case", (), {"actual_output": str(tmp_path)})()
    assert metric.measure(case) == 0 and not metric.is_successful()


@pytest.fixture
def staged(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pipeline/custom-eval"))
    from prepare_inputs import prepare
    task = Path(__file__).resolve().parents[2] / "pipeline/custom-eval/tasks/task-10-helm-to-kustomize"
    workspace = tmp_path / "ws" / task.name
    baseline = tmp_path / "baseline" / task.name
    prepare(task, workspace, baseline)
    yield workspace, baseline
    # Windows read-only snapshots need their file attributes cleared for pytest cleanup.
    for p in baseline.rglob("*"):
        p.chmod(0o700)
    baseline.chmod(0o700)


def test_originals_remain_available_after_produced_chart_removal(staged):
    import shutil
    ws, baseline = staged
    shutil.rmtree(ws / "deploy/helm")
    text = immutable_inputs(ws, baseline)
    assert str(baseline) in text and "Repository-fixture originals verified" in text
    assert "deployment.yaml" in text and "sha256" in text
    assert "context/" not in text.split("Do not read")[0]
    assert "Originals are comparison inputs ONLY" in text
    assert "not an OS access boundary" in text


@pytest.mark.parametrize("pointer", ["../../outside", "C:/sensitive", "/etc", "../baseline/other"])
def test_metadata_cannot_redirect_judge_to_arbitrary_input_paths(staged, pointer):
    ws, baseline = staged
    path = ws / ".github/eval-inputs.json"
    path.write_text(json.dumps({"baseline_dir": pointer}), encoding="utf-8")
    with pytest.raises(ValueError, match="workspace-local baseline metadata is untrusted"):
        immutable_inputs(ws, baseline)


def test_mutated_original_hash_is_setup_error(staged):
    ws, baseline = staged
    path = next((baseline / "deploy").rglob("*.yaml"))
    path.chmod(0o600)
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        immutable_inputs(ws, baseline)


def test_added_answer_file_cannot_change_immutable_render_inventory(staged):
    ws, baseline = staged
    baseline.chmod(0o700)
    (baseline / "invented-answer.yaml").write_text("kind: Ingress", encoding="utf-8")
    with pytest.raises(ValueError, match="inventory"):
        immutable_inputs(ws, baseline)


def test_metadata_input_paths_cannot_leak_undeclared_contents(staged):
    ws, baseline = staged
    path = ws / ".github/eval-inputs.json"
    path.write_text(json.dumps({"inputs": [{"path": "../../secrets"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="workspace-local baseline metadata is untrusted"):
        immutable_inputs(ws, baseline)


@pytest.mark.parametrize("metadata", [[], None, {"version": 1, "read_only": True, "baseline_dir": []}])
def test_malformed_metadata_cannot_escape_structured_error_boundary(staged, metadata):
    ws, baseline = staged
    (ws / ".github/eval-inputs.json").write_text(json.dumps(metadata))
    with pytest.raises((ValueError, TypeError)):
        immutable_inputs(ws, baseline)


def test_metadata_profile_hash_must_match_immutable_original(staged):
    ws, baseline = staged
    path = ws / ".github/eval-inputs.json"
    path.write_text(json.dumps({"profile_sha256": "not-a-hash"}), encoding="utf-8")
    with pytest.raises(ValueError, match="workspace-local baseline metadata is untrusted"):
        immutable_inputs(ws, baseline)


def test_unknown_workspace_origin_is_rejected(tmp_path):
    workspace = tmp_path / "unknown-task"
    workspace.mkdir()
    with pytest.raises(ValueError, match="no canonical repository fixture origin"):
        immutable_inputs(workspace)


def test_manifest_cannot_self_authorize_tampered_digest(staged):
    ws, baseline = staged
    manifest_path = baseline / "baseline-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch|canonical repository fixture"):
        immutable_inputs(ws, baseline)


def test_manifest_path_traversal_is_rejected(staged):
    ws, baseline = staged
    manifest_path = baseline / "baseline-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../../outside"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="path traversal|safe relative"):
        immutable_inputs(ws, baseline)


def test_raw_judge_response_and_embedded_credentials_are_never_persisted(tmp_path, capsys):
    from grading import write_result

    secret = "ghp_fixtureNotARealCredential_1234567890"
    response = f"1. FAIL - copied {secret} VERDICT: FAILED\nVERDICT: FAILED"
    result = parse_result(response, 1)
    path = tmp_path / "result.json"
    write_result(result, path)
    persisted = path.read_text(encoding="utf-8") + capsys.readouterr().out
    assert secret not in persisted
    assert response not in persisted
    assert result.to_dict()["criteria"] == [{"id": 1, "status": "FAIL"}]


def test_symlink_artifacts_are_not_inlined(tmp_path):
    secret = tmp_path.parent / (tmp_path.name + "-outside.txt")
    secret.write_text("NEVER_INLINE_EXTERNAL_FILE")
    try:
        (tmp_path / "linked.txt").symlink_to(secret)
    except OSError:
        pytest.skip("creating symlinks requires Windows developer mode or privilege")
    assert "NEVER_INLINE_EXTERNAL_FILE" not in artifact_dump(tmp_path)
