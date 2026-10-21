"""Deterministic provenance tests: no model, work-product or dependency execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys

import pytest

import agile_eval.provenance as p
from agile_eval.grading_contract import parse_result
from agile_eval.provenance import credited_status, result_status, retained_result, write_result
from agile_eval import file_io


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for task_id in ("task-a", "task-b"):
        task = root / "eval/pipeline/custom-eval/tasks" / task_id
        task.mkdir(parents=True)
        (task / "prompt.md").write_text("Produce the requested file.", encoding="utf-8")
        (task / "acceptance.md").write_text(f"1. {task_id} exists.", encoding="utf-8")
        (task / "solution-profile.yaml").write_text("identity: synthetic\n", encoding="utf-8")
        (task / "inputs.json").write_text('{"version":1,"inputs":[]}', encoding="utf-8")
    skill = root / "plugins/agile-agents-core/skills/acceptance-grading/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Synthetic grading doctrine", encoding="utf-8")
    locks = root / "eval/deepeval"
    locks.mkdir()
    (locks / "requirements.lock.txt").write_text("# synthetic lock identity\n", encoding="utf-8")
    (locks / "requirements-yaml.lock.txt").write_text("# synthetic yaml lock\n", encoding="utf-8")
    monkeypatch.setattr(p, "ROOT", root)
    return root


def context(repo, run_id="run-one"):
    return p.build_context(repo, run_id, ["task-a", "task-b"],
                           agent="requested-agent", judge="requested-judge")


def acceptance(repo, task="task-a"):
    return repo / "eval/pipeline/custom-eval/tasks" / task / "acceptance.md"


def payload(tmp_path, expected, repo, task="task-a", verdict="UNVERIFIED"):
    run = tmp_path / expected["run_id"]
    run.mkdir(exist_ok=True)
    path = run / f"{task}.shell.json"
    state = {"RESOLVED": "PASS", "FAILED": "FAIL"}.get(verdict, verdict)
    result = parse_result(f"1. {state} - synthetic evidence\nVERDICT: {verdict}", 1)
    write_result(result, path)
    file_io.write_json(path.with_name(path.name + ".provenance.json"),
                 p.manifest(expected, [p.binding(path, expected, task, acceptance(repo, task))]))
    return path


def test_manifest_captures_scoped_identities_without_claiming_observation(repo):
    expected = context(repo)
    assert expected["selected_task_ids"] == ["task-a", "task-b"]
    assert expected["models"]["observed"] == {}
    assert expected["models"]["requested"]["agent"] == "requested-agent"
    assert expected["toolchain"]["copilot_cli"] is None
    assert expected["toolchain"]["copilot_cli_status"] == "unavailable_not_invoked"
    assert expected["execution"] == {
        "mode": "dry", "admission": "blocked", "sandbox": "not_verified",
        "approval_reference": None, "execution_ready": False,
    }
    assert expected["tasks"]["task-a"]["canonical_inputs"]
    assert all(p.HASH.fullmatch(value) for value in expected["dependency_locks"].values())
    assert p.HASH.fullmatch(expected["grading_doctrine_sha256"])
    assert expected["harness"]["revision"] is None
    assert expected["harness"]["dirty"] is None  # unavailable is never "clean"


@pytest.mark.parametrize("verdict,code,status", [
    ("UNVERIFIED", 3, "unverified"), ("FAILED", 1, "failed"),
])
def test_valid_binding_preserves_unverified_without_credit(repo, tmp_path, verdict, code, status):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict=verdict)
    p.validate_result(path, expected, "task-a", acceptance(repo))
    assert credited_status(path, code, acceptance(repo), expected, "task-a") == status


def test_valid_integrity_is_not_execution_admission(repo, tmp_path):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict="RESOLVED")
    assert result_status(path, 0, acceptance(repo)) == "resolved"  # format API only
    p.validate_result(path, expected, "task-a", acceptance(repo))
    assert credited_status(path, 0, acceptance(repo), expected, "task-a") == "setup_error"


@pytest.mark.parametrize("verdict,code", [("RESOLVED", 0), ("UNVERIFIED", 3), ("FAILED", 1)])
def test_two_run_payload_and_sidecar_cannot_supply_other_run_credit(repo, tmp_path, verdict, code):
    first, second = context(repo), context(repo, "run-two")
    source = payload(tmp_path, first, repo, verdict=verdict)
    target = payload(tmp_path, second, repo, verdict=verdict)
    shutil.copyfile(source, target)
    shutil.copyfile(source.with_name(source.name + ".provenance.json"),
                    target.with_name(target.name + ".provenance.json"))
    with pytest.raises(ValueError, match="trusted expected context"):
        p.validate_result(target, second, "task-a", acceptance(repo))
    assert credited_status(target, code, acceptance(repo), second, "task-a") == "setup_error"


@pytest.mark.parametrize("verdict,code", [("RESOLVED", 0), ("UNVERIFIED", 3), ("FAILED", 1)])
def test_copied_other_task_payload_and_sidecar_are_rejected(repo, tmp_path, verdict, code):
    expected = context(repo)
    source = payload(tmp_path, expected, repo, verdict=verdict)
    target = payload(tmp_path, expected, repo, task="task-b", verdict=verdict)
    shutil.copyfile(source, target)
    shutil.copyfile(source.with_name(source.name + ".provenance.json"),
                    target.with_name(target.name + ".provenance.json"))
    with pytest.raises(ValueError, match="binding mismatch"):
        p.validate_result(target, expected, "task-b", acceptance(repo, "task-b"))
    assert credited_status(target, code, acceptance(repo, "task-b"), expected, "task-b") == "setup_error"


@pytest.mark.parametrize("verdict,code,status", [
    ("RESOLVED", 0, "resolved"), ("UNVERIFIED", 3, "unverified"), ("FAILED", 1, "failed"),
])
def test_changed_acceptance_same_criterion_count_rejected(repo, tmp_path, verdict, code, status):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict=verdict)
    acceptance(repo).write_text("1. A different obligation.", encoding="utf-8")
    assert result_status(path, code, acceptance(repo)) == status
    with pytest.raises(ValueError, match="acceptance differs"):
        p.validate_result(path, expected, "task-a", acceptance(repo))
    assert credited_status(path, code, acceptance(repo), expected, "task-a") == "setup_error"


@pytest.mark.parametrize("verdict,code,status", [
    ("UNVERIFIED", 3, "unverified"), ("FAILED", 1, "failed"),
])
@pytest.mark.parametrize("change", ["missing", "tampered"])
def test_nonpositive_consumer_rejects_missing_or_tampered_sidecar(
    repo, tmp_path, verdict, code, status, change,
):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict=verdict)
    assert credited_status(path, code, acceptance(repo), expected, "task-a") == status
    sidecar = path.with_name(path.name + ".provenance.json")
    if change == "missing":
        sidecar.unlink()
    else:
        row = file_io.read_json(sidecar)
        row["result_bindings"][0]["sha256"] = "0" * 64
        file_io.write_json(sidecar, row)
    assert result_status(path, code, acceptance(repo)) == status
    assert credited_status(path, code, acceptance(repo), expected, "task-a") == "setup_error"


def test_valid_bound_partial_is_denied_by_execution_hold(repo, tmp_path):
    acceptance(repo).write_text("1. First obligation.\n2. Second obligation.", encoding="utf-8")
    expected = context(repo)
    result = parse_result("1. PASS - done\n2. FAIL - missing\nVERDICT: PARTIAL", 2)
    path = tmp_path / "partial.json"
    write_result(result, path)
    file_io.write_json(path.with_name(path.name + ".provenance.json"),
                 p.manifest(expected, [p.binding(path, expected, "task-a", acceptance(repo))]))
    assert result_status(path, 2, acceptance(repo)) == "partial"
    p.validate_result(path, expected, "task-a", acceptance(repo))
    assert credited_status(path, 2, acceptance(repo), expected, "task-a") == "setup_error"


def test_tampered_result_fails_integrity_even_if_format_is_valid(repo, tmp_path):
    expected = context(repo)
    path = payload(tmp_path, expected, repo)
    row = file_io.read_json(path)
    row["reasons"] = ["diagnostic withheld"]
    file_io.write_json(path, row)
    assert result_status(path, 3, acceptance(repo)) == "unverified"
    with pytest.raises(ValueError, match="binding mismatch"):
        p.validate_result(path, expected, "task-a", acceptance(repo))


def test_summary_projection_cannot_retain_arbitrary_diagnostics(repo, tmp_path):
    expected = context(repo)
    path = payload(tmp_path, expected, repo)
    row = file_io.read_json(path)
    row["reasons"] = ["PRIVATE_SYNTHETIC_DIAGNOSTIC"]
    row["criteria"][0]["reason"] = "PRIVATE_SYNTHETIC_DIAGNOSTIC"
    row["raw_response"] = "PRIVATE_SYNTHETIC_DIAGNOSTIC"
    file_io.write_json(path, row)
    file_io.write_json(path.with_name(path.name + ".provenance.json"),
                 p.manifest(expected, [p.binding(path, expected, "task-a", acceptance(repo))]))
    safe = retained_result(path, expected, "task-a", acceptance(repo))
    assert safe["status"] == "unverified"
    assert "PRIVATE_SYNTHETIC_DIAGNOSTIC" not in json.dumps(safe)
    assert safe["criteria"] == [{"id": 1, "status": "UNVERIFIED"}]


@pytest.mark.parametrize("field,value", [
    ("status", "unknown"), ("expected_criteria", 10**20), ("criteria", [None]),
    ("expected_criteria", True),
])
def test_malformed_result_fails_bounded_format_validation(repo, tmp_path, field, value):
    path = payload(tmp_path, context(repo), repo)
    row = file_io.read_json(path)
    row[field] = value
    file_io.write_json(path, row)
    assert result_status(path, 3, acceptance(repo)) == "setup_error"


@pytest.mark.parametrize("version", [None, 0, 2, "1", True])
def test_legacy_and_unknown_manifest_versions_never_backfilled(repo, tmp_path, version):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict="RESOLVED")
    sidecar = path.with_name(path.name + ".provenance.json")
    row = file_io.read_json(sidecar)
    row["schema_version"] = version
    file_io.write_json(sidecar, row)
    before = sidecar.read_bytes()
    with pytest.raises(ValueError, match="legacy/unattributed"):
        p.validate_result(path, expected, "task-a", acceptance(repo))
    assert sidecar.read_bytes() == before


@pytest.mark.parametrize("version", [None, 1, 3, "2", True])
def test_unknown_result_version_cannot_award_credit(repo, tmp_path, version):
    path = payload(tmp_path, context(repo), repo, verdict="RESOLVED")
    row = file_io.read_json(path)
    row["schema_version"] = version
    file_io.write_json(path, row)
    assert result_status(path, 0, acceptance(repo)) == "setup_error"


def test_missing_legacy_binding_no_credit_and_no_backfill(repo, tmp_path):
    expected = context(repo)
    path = payload(tmp_path, expected, repo, verdict="RESOLVED")
    sidecar = path.with_name(path.name + ".provenance.json")
    sidecar.unlink()
    assert credited_status(path, 0, acceptance(repo), None, "task-a") == "setup_error"
    assert credited_status(path, 0, acceptance(repo), expected, "task-a") == "setup_error"
    assert not sidecar.exists()


@pytest.mark.parametrize("tamper", ["hash", "status", "reference", "task_id", "input_identity"])
def test_invalid_binding_fields_fail_without_following_manifest_paths(repo, tmp_path, tamper):
    expected = context(repo)
    path = payload(tmp_path, expected, repo)
    sidecar = path.with_name(path.name + ".provenance.json")
    row = file_io.read_json(sidecar)
    key = "sha256" if tamper == "hash" else tamper
    row["result_bindings"][0][key] = "../../outside/private" if tamper == "reference" else "unknown"
    file_io.write_json(sidecar, row)
    with pytest.raises(ValueError, match="binding mismatch"):
        p.validate_result(path, expected, "task-a", acceptance(repo))


def test_untrusted_manifest_cannot_redefine_expected_run(repo, tmp_path):
    expected = context(repo)
    run = tmp_path / "run"
    run.mkdir()
    changed = copy.deepcopy(expected)
    changed["run_id"] = "attacker-run"
    file_io.write_json(run / p.MANIFEST, p.manifest(changed))
    with pytest.raises(ValueError, match="run context changed"):
        p.load_expected(run, file_io.identity(expected))


def test_relevant_untracked_source_changes_fingerprint_not_unrelated_research(repo):
    before = context(repo)
    unrelated = repo / "docs/research"
    unrelated.mkdir(parents=True)
    (unrelated / "private.md").write_text("not in hash scope", encoding="utf-8")
    runs = repo / "eval/pipeline/runs"
    runs.mkdir()
    (runs / "transcript.json").write_text("not in hash scope", encoding="utf-8")
    (repo / "eval/.env").write_text("synthetic excluded secret", encoding="utf-8")
    assert context(repo)["harness"] == before["harness"]
    (repo / "eval/new-helper.py").write_text("# relevant untracked source", encoding="utf-8")
    after = context(repo)
    assert after["harness"]["source_fingerprint"] != before["harness"]["source_fingerprint"]
    assert "eval/new-helper.py" in after["harness"]["files"]
    with pytest.raises(ValueError, match="trusted expected context"):
        p.validate_manifest(p.manifest(after), before)


def test_dirty_revision_cannot_masquerade_as_release(repo):
    expected = context(repo)
    expected["harness"]["revision"] = "a" * 40
    expected["harness"]["dirty"] = True
    changed = copy.deepcopy(expected)
    changed["harness"]["dirty"] = False
    with pytest.raises(ValueError, match="trusted expected context"):
        p.validate_manifest(p.manifest(changed), expected)


def test_git_dirty_observation_is_separate_from_revision_and_scoped_bytes(repo, monkeypatch):
    def git_only(argv, **kwargs):
        assert argv[0] == "git", "version collection must not invoke agent/model/work product"
        output = b"a" * 40 if "rev-parse" in argv else b"?? eval/new-helper.py\n"
        return p.subprocess.CompletedProcess(argv, 0, stdout=output)

    monkeypatch.setattr(p.subprocess, "run", git_only)
    before = p.harness_identity(repo)
    assert before["dirty"] is True
    assert before["revision"] == "a" * 40
    source = repo / "eval/new-helper.py"
    source.write_text("# first", encoding="utf-8")
    first = p.harness_identity(repo)
    source.write_text("# changed", encoding="utf-8")
    second = p.harness_identity(repo)
    assert first["revision"] == second["revision"]
    assert first["source_fingerprint"] != second["source_fingerprint"]


@pytest.mark.parametrize("path", ["../outside", "task/../../outside"])
def test_output_traversal_is_explicit_failure(tmp_path, path):
    with pytest.raises(ValueError, match="traversal"):
        file_io.write_json(tmp_path / path, {})


def test_output_symlink_never_overwrites_target(tmp_path):
    target = tmp_path / "target.json"
    target.write_text("original", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symlink/reparse"):
        file_io.write_json(link, {})
    assert target.read_text() == "original"


def test_reparse_attribute_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "file.json"
    path.write_text("{}")
    original = Path.lstat

    def reparse(self):
        if self == path:
            return type("Attributes", (), {
                "st_file_attributes": file_io.stat.FILE_ATTRIBUTE_REPARSE_POINT,
                "st_mode": original(self).st_mode,
            })()
        return original(self)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(ValueError, match="reparse"):
        file_io.checked_path(path)


def test_bounded_result_read_returns_setup_error(repo, tmp_path, monkeypatch):
    path = payload(tmp_path, context(repo), repo)
    monkeypatch.setattr(file_io, "MAX_BYTES", 10)
    assert result_status(path, 3, acceptance(repo)) == "setup_error"


def test_excessive_json_nesting_is_explicit_failure(tmp_path):
    path = tmp_path / "nested.json"
    path.write_text('{"nested":' + "[" * 2000 + "0" + "]" * 2000 + "}", encoding="utf-8")
    with pytest.raises(ValueError, match="nesting"):
        file_io.read_json(path)


def nested_json(shape, depth, leaf="0"):
    """Build containers iteratively, including the required root object in depth."""
    wrappers = {
        "object": [('{"nested":', "}")],
        "array": [("[", "]")],
        "mixed": [('{"nested":', "}"), ("[", "]")],
    }[shape]
    for index in range(depth - 1):
        opening, closing = wrappers[index % len(wrappers)]
        leaf = opening + leaf + closing
    return '{"root":' + leaf + "}"


@pytest.mark.parametrize("shape", ["object", "array", "mixed"])
@pytest.mark.parametrize("depth", [1, file_io.MAX_JSON_DEPTH - 1, file_io.MAX_JSON_DEPTH])
def test_json_container_depth_through_limit_is_accepted(tmp_path, shape, depth):
    text = nested_json(shape, depth)
    path = tmp_path / "nested.json"
    path.write_text(text, encoding="utf-8")

    assert file_io.read_json(path) == json.loads(text)


@pytest.mark.parametrize("shape", ["object", "array", "mixed"])
def test_json_one_container_over_limit_is_rejected_before_decode(tmp_path, monkeypatch, shape):
    path = tmp_path / "nested.json"
    path.write_text(nested_json(shape, file_io.MAX_JSON_DEPTH + 1), encoding="utf-8")

    def unexpected_decode(*args, **kwargs):
        pytest.fail("over-depth JSON reached the runtime-dependent decoder")

    monkeypatch.setattr(file_io.json, "loads", unexpected_decode)
    with pytest.raises(ValueError, match="nesting"):
        file_io.read_json(path)


@pytest.mark.parametrize("leaf", [
    "{[" * (file_io.MAX_JSON_DEPTH + 1),
    "}]" * (file_io.MAX_JSON_DEPTH + 1),
    'escaped quote " then {[ and backslash \\',
    'backslash then quote \\" and ]}',
])
def test_json_depth_ignores_string_delimiters_and_escapes(tmp_path, leaf):
    text = nested_json("mixed", file_io.MAX_JSON_DEPTH, json.dumps(leaf))
    path = tmp_path / "nested.json"
    path.write_text(text, encoding="utf-8")

    assert file_io.read_json(path) == json.loads(text)


@pytest.mark.parametrize("text", ['{"broken":[}', '{"broken":"unterminated}', '{"broken":"\\q"}'])
def test_json_depth_scan_does_not_replace_syntax_validation(tmp_path, text):
    path = tmp_path / "malformed.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        file_io.read_json(path)


def test_capture_failure_retains_full_denominator_without_invented_hashes(repo, tmp_path, monkeypatch):
    run = tmp_path / "failed-run"
    run.mkdir()
    monkeypatch.setattr(sys, "argv", [
        "provenance", "start", "--run-dir", str(run), "--run-id", run.name,
        "--output-root", str(tmp_path),
        "--task-id", "task-a", "--task-id", "task-b", "--agent", 'injected"model',
    ])
    assert p.main() == 2
    row = file_io.read_json(run / p.MANIFEST)
    assert row["attribution"] == "unavailable"
    assert row["selected_task_ids"] == ["task-a", "task-b"]
    assert "context_sha256" not in row
    saved = file_io.read_json(run / "summary.json")
    assert saved["total"] == saved["setup_error_count"] == 2
    assert {t["status"] for t in saved["tasks"]} == {"setup_error"}
    for key in ("resolved_pct", "partial_pct", "failed_pct"):
        assert key in saved
        assert saved[key] is None
    assert 'injected' not in json.dumps(saved)


def test_ignored_results_and_virtualenv_never_enter_source_scope(repo, monkeypatch):
    excluded = repo / "eval/results"
    excluded.mkdir()
    private = excluded / "summary.json"
    private.write_text("not read", encoding="utf-8")
    environment = repo / "eval/old-environment"
    environment.mkdir()
    (environment / "pyvenv.cfg").write_text("not read", encoding="utf-8")
    (environment / "module.py").write_text("not read", encoding="utf-8")
    original = file_io.read_bytes

    def scoped_read(path):
        assert excluded not in path.parents and environment not in path.parents
        return original(path)

    monkeypatch.setattr(file_io, "read_bytes", scoped_read)
    assert not any(name.startswith(("eval/results/", "eval/old-environment/"))
                   for name in p.source_files(repo))


@pytest.mark.parametrize("relative", ["eval/custom-output", "eval/.github", "external-output"])
def test_declared_output_tree_is_pruned_before_reads_and_traversal(repo, tmp_path, monkeypatch, relative):
    output = (tmp_path if relative == "external-output" else repo) / relative
    output.mkdir(parents=True)
    retained = output / "older-run"
    retained.mkdir()
    (retained / ".github").mkdir()
    summary_file = retained / "summary.json"
    summary_file.write_text('{"old":1}', encoding="utf-8")
    (retained / p.MANIFEST).write_text("{}", encoding="utf-8")
    (retained / ".github/staged.py").write_text("# never read", encoding="utf-8")
    original_read, original_walk = file_io.read_bytes, p.os.walk

    def read_source(path):
        assert output not in path.parents
        return original_read(path)

    def walk_source(*args, **kwargs):
        for directory, dirs, names in original_walk(*args, **kwargs):
            assert not Path(directory).is_relative_to(output)
            yield directory, dirs, names

    monkeypatch.setattr(file_io, "read_bytes", read_source)
    monkeypatch.setattr(p.os, "walk", walk_source)
    before = p.build_context(repo, "new-run", ["task-a"], output_root=output)["harness"]
    summary_file.write_text('{"old":2}', encoding="utf-8")
    (output / "newer-run").mkdir()
    (output / "newer-run/source.py").write_text("# staged output", encoding="utf-8")
    after = p.build_context(repo, "new-run", ["task-a"], output_root=output)["harness"]
    assert after["files"] == before["files"]
    assert after["source_fingerprint"] == before["source_fingerprint"]
    (repo / "eval/new-source.py").write_text("# actual implementation", encoding="utf-8")
    changed = p.build_context(repo, "new-run", ["task-a"], output_root=output)["harness"]
    assert changed["source_fingerprint"] != before["source_fingerprint"]
    assert "eval/new-source.py" in changed["files"]


@pytest.mark.parametrize("relative", [
    ".", "eval", "plugins", "scripts", ".github", ".github/plugin",
    "eval/deepeval", "eval/pipeline", "eval/pipeline/custom-eval/tasks/task-a",
    "eval/deepeval/requirements.lock.txt",
    "eval/python", "eval/python/agile_eval", "eval/python/agile_eval/grading.py",
])
def test_output_root_cannot_conceal_authoritative_sources(repo, relative):
    with pytest.raises(ValueError, match="authoritative source"):
        p.build_context(repo, "run", ["task-a"], output_root=repo / relative)


def test_canonical_package_source_bytes_are_bound_even_with_sibling_output(repo):
    source_root = Path(__file__).resolve().parents[2] / "python/agile_eval"
    package = repo / "eval/python/agile_eval"
    shutil.copytree(source_root, package, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    output = repo / "eval/custom-output"
    before = p.build_context(repo, "run", ["task-a"], output_root=output)["harness"]
    source = package / "grading.py"
    assert "eval/python/agile_eval/grading.py" in before["files"]
    source.write_bytes(source.read_bytes() + b"\n# source identity changed\n")
    after = p.build_context(repo, "run", ["task-a"], output_root=output)["harness"]
    assert before["source_fingerprint"] != after["source_fingerprint"]
    assert before["files"] != after["files"]


def test_output_exclusions_validate_paths_before_normalizing(repo, tmp_path, monkeypatch):
    output = repo / "eval/custom-output"
    output.mkdir()
    monkeypatch.chdir(repo)
    assert p.source_files(repo, output_root=Path("eval/custom-output")) == p.source_files(
        repo, output_root=output,
    )
    with pytest.raises(ValueError, match="traversal"):
        p.source_files(repo, output_root=output / "../other")
    link = tmp_path / "linked-output"
    link.symlink_to(output, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink/reparse"):
        p.source_files(repo, output_root=link)


def test_native_start_captures_before_manifest_and_excludes_parent_output(repo, monkeypatch):
    output = repo / "eval/custom-output"
    run = output / "new-run"
    run.mkdir(parents=True)
    (output / "old-run").mkdir()
    (output / "old-run/summary.json").write_text("{}", encoding="utf-8")
    original_build = p.build_context

    def capture_before_manifest(*args, **kwargs):
        assert not (run / p.MANIFEST).exists()
        assert kwargs["output_root"] == output
        return original_build(*args, **kwargs)

    monkeypatch.setattr(p, "build_context", capture_before_manifest)
    monkeypatch.setattr(sys, "argv", [
        "provenance", "start", "--run-dir", str(run), "--run-id", run.name,
        "--output-root", str(output), "--task-id", "task-a",
    ])
    assert p.main() == 0
    context = file_io.read_json(run / p.MANIFEST)["context"]
    assert not any(name.startswith("eval/custom-output/") for name in context["harness"]["files"])


@pytest.mark.parametrize("root_argument", [None, "other-root"])
def test_native_start_requires_declared_parent_output_root(repo, tmp_path, monkeypatch, root_argument):
    run = tmp_path / "output/new-run"
    run.mkdir(parents=True)
    argv = ["provenance", "start", "--run-dir", str(run), "--run-id", run.name,
            "--task-id", "task-a"]
    if root_argument:
        argv += ["--output-root", str(tmp_path / root_argument)]
    monkeypatch.setattr(sys, "argv", argv)
    assert p.main() == 2
    assert file_io.read_json(run / p.MANIFEST)["attribution"] == "unavailable"


@pytest.mark.parametrize("outside_tree", [False, True])
def test_standalone_capture_excludes_outputs_before_writing(repo, monkeypatch, outside_tree):
    from agile_eval.prepare_inputs import prepare

    actual_tasks = Path(__file__).resolve().parents[2] / "pipeline/custom-eval/tasks"
    task_id = "task-10-helm-to-kustomize"
    task = repo / "eval/pipeline/custom-eval/tasks" / task_id
    shutil.copytree(actual_tasks / task_id, task)
    output = repo / "eval/custom-output"
    run = output / "standalone"
    workspace = run / "ws" / task_id
    prepare(task, workspace, run / "baseline" / task_id)
    path = (repo / "eval" if outside_tree else run) / "result.json"
    sidecar = path.with_name(path.name + ".provenance.json")
    result = parse_result("1. UNVERIFIED - offline\nVERDICT: UNVERIFIED", 1)
    original_build = p.build_context

    def capture_before_write(*args, **kwargs):
        assert not path.exists() and not sidecar.exists()
        return original_build(*args, **kwargs)

    with monkeypatch.context() as first:
        first.setattr(p, "build_context", capture_before_write)
        write_result(result, path, workspace=workspace, acceptance=task / "acceptance.md")
    before = file_io.read_json(sidecar)["context"]["harness"]
    (output / "older-run").mkdir()
    (output / "older-run/summary.json").write_text('{"retained":true}', encoding="utf-8")
    write_result(result, path, workspace=workspace, acceptance=task / "acceptance.md")
    after = file_io.read_json(sidecar)["context"]["harness"]
    assert after["files"] == before["files"]
    assert after["source_fingerprint"] == before["source_fingerprint"]
    assert not any(name.startswith("eval/custom-output/") for name in after["files"])
    assert "eval/result.json" not in after["files"]
    assert "eval/result.json.provenance.json" not in after["files"]
    (repo / "eval/changed.py").write_text("# real change", encoding="utf-8")
    write_result(result, path, workspace=workspace, acceptance=task / "acceptance.md")
    assert file_io.read_json(sidecar)["context"]["harness"]["source_fingerprint"] != before["source_fingerprint"]


@pytest.mark.parametrize("parent", ["arbitrary", "ws"])
def test_standalone_cannot_infer_output_root_from_unvalidated_workspace(repo, tmp_path, parent):
    workspace = tmp_path / "run" / parent / "task-a"
    workspace.mkdir(parents=True)
    path = repo / "eval/result.json"
    with pytest.raises((ValueError, OSError)):
        write_result(parse_result("1. UNVERIFIED - offline\nVERDICT: UNVERIFIED", 1),
                     path, workspace=workspace, acceptance=acceptance(repo))
    assert not path.exists()


@pytest.mark.parametrize("declarations,count", [
    ([], 2),
    ([{"source": "one.py", "destination": "one.py", "required": True}], 3),
    ([{"source": "folder", "destination": "src", "required": True}], 4),
    ([{"source": "one.py", "destination": "one.py", "required": True},
      {"source": "folder", "destination": "src", "required": True}], 5),
    ([{"source": "folder", "destination": "src", "required": True},
      {"source": "one.py", "destination": "one.py", "required": True}], 5),
])
@pytest.mark.parametrize("over_limit", [False, True])
def test_canonical_inventory_limit_covers_every_insertion(
    repo, monkeypatch, declarations, count, over_limit,
):
    from agile_eval.workspace_inputs import _canonical_baseline_files

    task = acceptance(repo).parent
    (task / "one.py").write_text("# explicit", encoding="utf-8")
    (task / "folder").mkdir()
    for name in ("two.py", "three.py"):
        (task / "folder" / name).write_text("# expanded", encoding="utf-8")
    file_io.write_json(task / "inputs.json", {"version": 1, "inputs": declarations})
    monkeypatch.setattr(file_io, "MAX_FILES", count - int(over_limit))
    if over_limit:
        with pytest.raises(ValueError, match="canonical input inventory exceeds file limit"):
            _canonical_baseline_files("task-a", task.parent)
    else:
        files, _ = _canonical_baseline_files("task-a", task.parent)
        assert len(files) == count


def summary(expected):
    return {
        "run_id": expected["run_id"], "total": 2, "resolved": 0, "partial": 0,
        "failed": 0, "unverified": 0, "skipped": 1, "setup_error_count": 1,
        "blocked_approval_count": 0,
        "tasks": [{"id": "task-a", "status": "skipped"}, {"id": "task-b", "status": "setup_error"}],
    }


def test_summary_binds_every_selected_terminal_task(repo, tmp_path):
    expected = context(repo)
    run = tmp_path / expected["run_id"]
    run.mkdir()
    file_io.write_json(run / "summary.json", summary(expected))
    p.finalize(run, expected)
    row = file_io.read_json(run / p.MANIFEST)
    p.validate_manifest(row, expected)
    assert row["result_bindings"] == [p.binding(run / "summary.json", expected, None)]


@pytest.mark.parametrize("change", ["missing_task", "unknown_status", "count", "run"])
def test_invalid_summary_denominator_or_status_fails(repo, tmp_path, change):
    expected = context(repo)
    run = tmp_path / expected["run_id"]
    run.mkdir()
    row = summary(expected)
    if change == "missing_task":
        row["tasks"].pop()
    elif change == "unknown_status":
        row["tasks"][0]["status"] = "unknown"
    elif change == "count":
        row["skipped"] = 2
    else:
        row["run_id"] = "different"
    file_io.write_json(run / "summary.json", row)
    with pytest.raises(ValueError, match="summary|unknown task"):
        p.finalize(run, expected)
    assert not (run / p.MANIFEST).exists()


def test_summary_cannot_aggregate_unbound_legacy_credit(repo, tmp_path):
    expected = context(repo)
    run = tmp_path / expected["run_id"]
    run.mkdir()
    row = summary(expected)
    row["tasks"][0]["status"] = "resolved"
    row["skipped"], row["resolved"] = 0, 1
    file_io.write_json(run / "summary.json", row)
    with pytest.raises(ValueError, match="unbound credit"):
        p.finalize(run, expected)
