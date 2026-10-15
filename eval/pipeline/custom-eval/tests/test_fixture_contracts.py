"""Task-specific source contracts, not execution of generated benchmark answers."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import yaml

CUSTOM_EVAL = Path(__file__).resolve().parents[1]
ROOT = CUSTOM_EVAL.parents[2]
TASKS = CUSTOM_EVAL / "tasks"
sys.path.insert(0, str(CUSTOM_EVAL))
sys.path.insert(0, str(ROOT / "eval"))

from prepare_inputs import SetupError, prepare, validate_profile  # noqa: E402
from grading import immutable_inputs  # noqa: E402

TASK04 = TASKS / "task-04-adr-library-tradeoff"
TASK07 = TASKS / "task-07-test-coverage-uplift"
TASK10 = TASKS / "task-10-helm-to-kustomize"
OLD_ADR = "docs/adr/0007-http-resilience-library.md"
NEW_ADR = "docs/adr/0014-http-resilience-library.md"
PRODUCTION = {
    "Reconciliation.slnx",
    "src/Reconciliation/Dependencies.cs",
    "src/Reconciliation/Payment.cs",
    "src/Reconciliation/PaymentReconciler.cs",
    "src/Reconciliation/PaymentRepository.cs",
    "src/Reconciliation/Reconciliation.csproj",
    "src/Reconciliation/SystemClock.cs",
}
INGRESS_CRITERION = (
    "2. **Manifest equivalence** — the rendered output of each overlay is functionally equivalent "
    "to `helm template ./deploy/helm/orders-api -f values-<env>.yaml` (same Kinds, names, "
    "replica counts, image tags, resource limits, ingress hosts). Diff is whitespace/ordering only."
)


def read(path):
    return path.read_text(encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage(task, tmp_path):
    workspace = tmp_path / "ws" / task.name
    baseline = tmp_path / "baseline" / task.name
    result = prepare(task, workspace, baseline)
    return workspace, baseline, result


def assert_task04_contract(task):
    profile, checks = validate_profile(task / "solution-profile.yaml")
    assert profile["documentation"]["adr"]["format"] == "madr"
    assert checks == []
    prompt, acceptance = read(task / "prompt.md"), read(task / "acceptance.md")
    for text in (prompt, acceptance):
        assert set(re.findall(r"`(docs/adr/[^`]+\.md)`", text)) == {OLD_ADR, NEW_ADR}
        assert "architecture-decision-records" in text and "MADR" in text
        assert "**Links**" in text and "**superseded**" in text
        assert "relative Markdown link" in text
        assert "canonical sibling baseline" in text
        assert "six MADR sections" not in text
        assert "Status / Context /" not in text
    assert "historical rationale" in prompt and "historical rationale" in acceptance


def test_task04_uses_selected_madr_and_exact_two_file_supersession_scope():
    assert_task04_contract(TASK04)


@pytest.mark.parametrize("old,new", [
    ("format: madr", "format: nygard"),
    ("format: madr", "format: custom"),
])
def test_task04_format_mutation_is_detected(tmp_path, old, new):
    task = tmp_path / "task"
    shutil.copytree(TASK04, task)
    profile = task / "solution-profile.yaml"
    profile.write_text(read(profile).replace(old, new), encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_task04_contract(task)


def test_task04_prior_decision_matches_skill_madr_without_seeding_answer():
    skill = read(ROOT / "plugins/agile-agents-core/skills/architecture-decision-records/SKILL.md")
    template = skill.split("## MADR template", 1)[1].split("```markdown", 1)[1].split("```", 1)[0]
    original = read(TASK04 / "baseline" / OLD_ADR)
    assert re.findall(r"^## .+$", original, re.M) == re.findall(r"^## .+$", template, re.M)
    assert "### Positive Consequences" in original and "### Negative Consequences" in original
    assert original.startswith("# 0007. ") and "- Status: accepted" in original
    assert '**"Polly directly"**' in original
    assert "0014" not in original and "supersed" not in original.lower()
    assert "Microsoft.Extensions.Http.Resilience" not in original
    assert not (TASK04 / "baseline" / NEW_ADR).exists()
    declaration = json.loads(read(TASK04 / "inputs.json"))
    assert declaration["inputs"] == [{
        "source": f"baseline/{OLD_ADR}", "destination": OLD_ADR, "required": True,
    }]


def test_task04_staging_and_working_copy_updates_preserve_canonical_original(tmp_path):
    source = TASK04 / "baseline" / OLD_ADR
    before = digest(source)
    workspace, baseline, result = stage(TASK04, tmp_path)
    assert result["inputs"] == [{"path": OLD_ADR, "sha256": before}]
    assert digest(workspace / OLD_ADR) == digest(baseline / OLD_ADR) == before
    assert not (workspace / NEW_ADR).exists()
    assert not (baseline / NEW_ADR).exists()
    # Deliberately incomplete synthetic output: tests staging, not an answer or ADR authoring.
    (workspace / OLD_ADR).write_text("working-copy change\n", encoding="utf-8")
    (workspace / NEW_ADR).write_text("new working-copy marker\n", encoding="utf-8")
    assert "Repository-fixture originals verified" in immutable_inputs(workspace, baseline)
    assert digest(source) == digest(baseline / OLD_ADR) == before
    assert not (baseline / NEW_ADR).exists()


def assert_production_inventory(root):
    # Preserve local ignored build output, but never treat it as canonical input.
    files = {
        path.relative_to(root).as_posix() for path in root.rglob("*")
        if path.is_file() and not {"bin", "obj"}.intersection(path.relative_to(root).parts)
    }
    assert files == PRODUCTION
    assert all("class PaymentReconcilerTests" not in read(root / name)
               and "class PaymentReconcilerIntegrationTests" not in read(root / name)
               for name in PRODUCTION if name.endswith(".cs"))


def test_task07_exact_production_inventory_includes_repository_and_no_answers():
    assert_production_inventory(TASK07 / "baseline")
    declaration = json.loads(read(TASK07 / "inputs.json"))
    assert {item["destination"] for item in declaration["inputs"]} == PRODUCTION
    assert all(item["source"] == f"baseline/{item['destination']}"
               and item["required"] is True for item in declaration["inputs"])
    project = ET.fromstring(read(TASK07 / "baseline/src/Reconciliation/Reconciliation.csproj"))
    assert project.find(".//PackageReference[@Include='Npgsql']") is not None


def test_task07_missing_production_dependency_fails_preflight(tmp_path):
    task = tmp_path / "task"
    shutil.copytree(TASK07, task, ignore=shutil.ignore_patterns("bin", "obj"))
    (task / "baseline/src/Reconciliation/Dependencies.cs").unlink()
    with pytest.raises(AssertionError):
        assert_production_inventory(task / "baseline")
    with pytest.raises(SetupError, match="missing"):
        prepare(task, tmp_path / "ws", tmp_path / "baseline")
    assert not (tmp_path / "ws").exists()


@pytest.mark.parametrize("answer", [
    "tests/Reconciliation.Tests/PaymentReconcilerTests.cs",
    "tests/Reconciliation.IntegrationTests/PaymentReconcilerIntegrationTests.cs",
    "src/Reconciliation/PaymentReconcilerTests.cs",
    "coverage.cobertura.xml",
])
def test_task07_seeded_answer_or_coverage_mutation_is_detected(tmp_path, answer):
    baseline = tmp_path / "baseline"
    shutil.copytree(TASK07 / "baseline", baseline, ignore=shutil.ignore_patterns("bin", "obj"))
    path = baseline / answer
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("seeded answer marker", encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_production_inventory(baseline)


def test_task07_real_staging_preserves_hashes_and_excludes_tests_coverage_and_build_output(tmp_path):
    before = {name: digest(TASK07 / "baseline" / name) for name in PRODUCTION}
    workspace, baseline, result = stage(TASK07, tmp_path)
    assert {item["path"]: item["sha256"] for item in result["inputs"]} == before
    assert {name: digest(workspace / name) for name in PRODUCTION} == before
    assert {name: digest(baseline / name) for name in PRODUCTION} == before
    assert {path.relative_to(workspace).as_posix() for path in workspace.rglob("*")
            if path.is_file()} == PRODUCTION | {
                "solution-profile.yaml", ".github/solution-profile.yaml",
            }
    assert "Repository-fixture originals verified" in immutable_inputs(workspace, baseline)
    assert {name: digest(TASK07 / "baseline" / name) for name in PRODUCTION} == before


def test_task07_changed_staged_production_is_not_unchanged_evidence(tmp_path):
    workspace, baseline, _ = stage(TASK07, tmp_path)
    before = {name: digest(TASK07 / "baseline" / name) for name in PRODUCTION}
    changed = "src/Reconciliation/PaymentReconciler.cs"
    (workspace / changed).write_text("// changed production\n", encoding="utf-8")
    # Authenticate sibling originals first; the workspace is never its own authority.
    assert "Repository-fixture originals verified" in immutable_inputs(workspace, baseline)
    differences = {name for name in PRODUCTION
                   if digest(workspace / name) != digest(baseline / name)}
    assert differences == {changed}
    assert {name: digest(baseline / name) for name in PRODUCTION} == before
    assert {name: digest(TASK07 / "baseline" / name) for name in PRODUCTION} == before


def test_task07_new_test_projects_can_restore_and_build_in_declared_commands():
    solution = ET.fromstring(read(TASK07 / "baseline/Reconciliation.slnx"))
    assert [node.attrib["Path"] for node in solution.iter("Project")] == [
        "src/Reconciliation/Reconciliation.csproj",
    ]
    _, resolved = validate_profile(TASK07 / "solution-profile.yaml")
    checks = {item["check"]: item["argv"] for item in resolved}
    unit = ["dotnet", "test", "tests/Reconciliation.Tests/Reconciliation.Tests.csproj"]
    assert checks["unit_test"] == unit
    assert checks["integration_test"] == [
        "dotnet", "test", "tests/Reconciliation.IntegrationTests/Reconciliation.IntegrationTests.csproj",
    ]
    assert checks["coverage"] == unit + [
        "/p:CollectCoverage=true", "/p:Threshold=90", "/p:ThresholdType=line",
    ]


def assert_ingress_criterion(text):
    assert INGRESS_CRITERION in " ".join(text.split())


def assert_six_resources(chart):
    kinds = []
    for template in (chart / "templates").glob("*.yaml"):
        kinds.extend(re.findall(r"^kind: (\S+)$", read(template), re.M))
    assert sorted(kinds) == sorted([
        "ConfigMap", "Deployment", "HorizontalPodAutoscaler",
        "NetworkPolicy", "Service", "ServiceAccount",
    ])
    assert "PUBLIC_BASE_URL: {{ .Values.ingress.host | quote }}" in read(
        chart / "templates/configmap.yaml",
    )


def test_task10_literal_criterion_and_six_resource_no_ingress_inventory():
    assert_ingress_criterion(read(TASK10 / "acceptance.md"))
    assert_six_resources(TASK10 / "baseline/deploy/helm/orders-api")


@pytest.mark.parametrize("replacement", ["", "PUBLIC_BASE_URL"])
def test_task10_removed_or_reinterpreted_ingress_criterion_is_detected(replacement):
    mutated = read(TASK10 / "acceptance.md").replace("ingress hosts", replacement)
    with pytest.raises(AssertionError):
        assert_ingress_criterion(mutated)


@pytest.mark.parametrize("mutation", ["add-ingress", "remove-service"])
def test_task10_changed_resource_inventory_is_detected(tmp_path, mutation):
    chart = tmp_path / "chart"
    shutil.copytree(TASK10 / "baseline/deploy/helm/orders-api", chart)
    if mutation == "add-ingress":
        (chart / "templates/ingress.yaml").write_text("kind: Ingress\n", encoding="utf-8")
    else:
        (chart / "templates/service.yaml").unlink()
    with pytest.raises(AssertionError):
        assert_six_resources(chart)


def test_task10_real_staging_preserves_original_six_resources_after_chart_removal(tmp_path):
    workspace, baseline, result = stage(TASK10, tmp_path)
    before = {item["path"]: digest(TASK10 / "baseline" / item["path"])
              for item in result["inputs"]}
    assert {item["path"]: item["sha256"] for item in result["inputs"]} == before
    chart = "deploy/helm/orders-api"
    assert_six_resources(workspace / chart)
    assert_six_resources(baseline / chart)
    shutil.rmtree(workspace / chart)
    assert "Repository-fixture originals verified" in immutable_inputs(workspace, baseline)
    assert {name: digest(baseline / name) for name in before} == before


@pytest.mark.parametrize("path,required", [
    (TASK10 / "baseline/README.md",
     ("no `Ingress` object", "must not be silently treated as proof of Ingress equivalence")),
    (CUSTOM_EVAL / "README.md",
     ("must use UNVERIFIED", "not infer equivalence from `PUBLIC_BASE_URL`")),
    (CUSTOM_EVAL.parent / "scoring-rubric.md",
     ("literal ingress-host equivalence is unresolved", "mark UNVERIFIED")),
    (ROOT / "plugins/agile-agents-core/skills/acceptance-grading/SKILL.md",
     ("six-resource, no-Ingress baseline", "mark that criterion `UNVERIFIED`")),
])
def test_task10_discrepancy_guidance_and_its_removal_are_guarded(path, required):
    text = " ".join(read(path).split())

    def assert_guidance(candidate):
        assert all(phrase in candidate for phrase in required)

    assert_guidance(text)
    with pytest.raises(AssertionError):
        assert_guidance(text.replace(required[0], ""))
