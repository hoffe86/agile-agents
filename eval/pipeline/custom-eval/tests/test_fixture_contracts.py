"""Task-specific source contracts, not execution of generated benchmark answers."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
import yaml

CUSTOM_EVAL = Path(__file__).resolve().parents[1]
ROOT = CUSTOM_EVAL.parents[2]
TASKS = CUSTOM_EVAL / "tasks"

# Independent expectations for retained data, not a task execution/staging registry.
TASK_CONTRACTS = {
    "task-01-csharp-minimal-api-endpoint": (True, {"lint", "typecheck", "unit_test"}),
    "task-02-python-di-refactor": (True, {"lint", "typecheck", "unit_test"}),
    "task-03-bicep-storage-waf": (False, {"lint", "typecheck"}),
    "task-04-adr-library-tradeoff": (True, set()),
    "task-05-pr-description": (True, set()),
    "task-06-gha-oidc-deploy": (True, {"lint", "typecheck", "unit_test"}),
    "task-07-test-coverage-uplift": (
        True, {"lint", "typecheck", "unit_test", "integration_test", "coverage"},
    ),
    "task-08-threat-model-api": (False, set()),
    "task-09-polly-resilience": (True, {"lint", "typecheck", "unit_test"}),
    "task-10-helm-to-kustomize": (True, {"lint", "typecheck", "integration_test"}),
}
REQUIRED_CONTEXT = (
    ("identity", "project_name"),
    ("identity", "lifecycle_stage"),
    ("documentation", "location"),
    ("backlog", "platform"),
    ("tech_stack", "primary_languages"),
    ("tech_stack", "test_discipline"),
)

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


def assert_input_contract(declaration, task_id):
    assert type(declaration.get("version")) is int and declaration["version"] == 1, "version"
    assert isinstance(declaration.get("inputs"), list), "inputs"
    assert bool(declaration["inputs"]) is TASK_CONTRACTS[task_id][0], "input inventory"


def assert_profile_contract(profile, task_id):
    for section, field in REQUIRED_CONTEXT:
        assert profile.get(section, {}).get(field), f"{section}.{field}"
    languages = profile["tech_stack"]["primary_languages"]
    assert isinstance(languages, list) and all(
        isinstance(language, (str, dict)) and language for language in languages
    ), "primary_languages"
    assert profile["tech_stack"]["test_discipline"] in {"tdd", "bdd", "test-after", "none"}
    assert profile["backlog"].get("create_tasks") is False
    assert profile.get("infrastructure", {}).get("deploy_verify") == "off"
    bar = profile["quality_gates"]["test_bar"]
    expected_checks = TASK_CONTRACTS[task_id][1]
    assert bar.get("enabled") is bool(expected_checks), "test_bar.enabled"
    if not expected_checks:
        assert isinstance(bar.get("skip_reason"), str) and bar["skip_reason"].strip(), "skip_reason"
        return
    for check in ("lint", "typecheck", "unit_test", "integration_test", "coverage", "mutation"):
        definition = bar.get(check, {})
        assert isinstance(definition, dict), check
        # The profile contract defaults these three checks on; other checks opt in.
        enabled = definition.get("enabled", check in {"lint", "typecheck", "unit_test"})
        assert enabled is (check in expected_checks), f"{check}.enabled"
        if check in expected_checks:
            command = definition.get("command")
            assert isinstance(command, list) and command and all(
                isinstance(argument, str) and argument.strip() for argument in command
            ), f"{check}.command"


def test_retained_corpus_has_all_ten_profiles_and_input_manifests():
    assert {path.parent.name for path in TASKS.glob("*/solution-profile.yaml")} == set(TASK_CONTRACTS)
    assert {path.parent.name for path in TASKS.glob("*/inputs.json")} == set(TASK_CONTRACTS)


@pytest.mark.parametrize("task_id", TASK_CONTRACTS)
def test_each_task_preserves_manifest_version_and_intended_input_presence(task_id):
    assert_input_contract(json.loads(read(TASKS / task_id / "inputs.json")), task_id)


@pytest.mark.parametrize("task_id", TASK_CONTRACTS)
def test_each_task_preserves_required_profile_context_and_enabled_checks(task_id):
    assert_profile_contract(yaml.safe_load(read(TASKS / task_id / "solution-profile.yaml")), task_id)


def test_empty_task02_input_declaration_is_detected():
    task_id = "task-02-python-di-refactor"
    declaration = json.loads(read(TASKS / task_id / "inputs.json"))
    declaration["inputs"] = []
    with pytest.raises(AssertionError, match="input inventory"):
        assert_input_contract(declaration, task_id)


@pytest.mark.parametrize("version", [None, 0, 2, "1", True])
def test_manifest_version_mutation_is_detected(version):
    task_id = "task-02-python-di-refactor"
    declaration = json.loads(read(TASKS / task_id / "inputs.json"))
    declaration["version"] = version
    with pytest.raises(AssertionError, match="version"):
        assert_input_contract(declaration, task_id)


@pytest.mark.parametrize("section,field", REQUIRED_CONTEXT)
@pytest.mark.parametrize("value", [None, "", []])
def test_missing_or_empty_profile_context_is_detected(section, field, value):
    profile = yaml.safe_load(read(TASK07 / "solution-profile.yaml"))
    profile[section][field] = value
    with pytest.raises(AssertionError, match=re.escape(f"{section}.{field}")):
        assert_profile_contract(profile, TASK07.name)


@pytest.mark.parametrize("check", sorted(TASK_CONTRACTS[TASK07.name][1]))
def test_disabling_any_task07_required_check_is_detected(check):
    profile = yaml.safe_load(read(TASK07 / "solution-profile.yaml"))
    profile["quality_gates"]["test_bar"][check]["enabled"] = False
    with pytest.raises(AssertionError, match=re.escape(f"{check}.enabled")):
        assert_profile_contract(profile, TASK07.name)


def test_disabling_task07_test_bar_is_detected():
    profile = yaml.safe_load(read(TASK07 / "solution-profile.yaml"))
    profile["quality_gates"]["test_bar"]["enabled"] = False
    with pytest.raises(AssertionError, match=r"test_bar\.enabled"):
        assert_profile_contract(profile, TASK07.name)


@pytest.mark.parametrize("command", [[], "", [""]])
def test_missing_or_invalid_enabled_check_command_is_detected(command):
    profile = yaml.safe_load(read(TASK07 / "solution-profile.yaml"))
    profile["quality_gates"]["test_bar"]["unit_test"]["command"] = command
    with pytest.raises(AssertionError, match=r"unit_test\.command"):
        assert_profile_contract(profile, TASK07.name)


def assert_task04_contract(task):
    profile = yaml.safe_load(read(task / "solution-profile.yaml"))
    assert profile["documentation"]["adr"]["format"] == "madr"
    assert profile["quality_gates"]["test_bar"]["enabled"] is False
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


def test_task07_missing_production_dependency_is_detected(tmp_path):
    task = tmp_path / "task"
    shutil.copytree(TASK07, task, ignore=shutil.ignore_patterns("bin", "obj"))
    (task / "baseline/src/Reconciliation/Dependencies.cs").unlink()
    with pytest.raises(AssertionError):
        assert_production_inventory(task / "baseline")


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


def test_task07_declared_commands_allow_restore_and_build_of_new_test_projects():
    solution = ET.fromstring(read(TASK07 / "baseline/Reconciliation.slnx"))
    assert [node.attrib["Path"] for node in solution.iter("Project")] == [
        "src/Reconciliation/Reconciliation.csproj",
    ]
    profile = yaml.safe_load(read(TASK07 / "solution-profile.yaml"))
    assert_profile_contract(profile, TASK07.name)
    checks = profile["quality_gates"]["test_bar"]
    unit = ["dotnet", "test", "tests/Reconciliation.Tests/Reconciliation.Tests.csproj"]
    assert checks["unit_test"]["command"] == unit
    assert checks["integration_test"]["command"] == [
        "dotnet", "test", "tests/Reconciliation.IntegrationTests/Reconciliation.IntegrationTests.csproj",
    ]
    assert checks["coverage"]["command"] == unit + [
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
