"""Required dependency-present CI gate. No judge, credentials or model calls."""
from __future__ import annotations

import importlib.metadata
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))


def verify() -> None:
    # Must precede imports; this is telemetry configuration, NOT OS isolation.
    from agile_eval.metrics.local_model import configure_offline

    configure_offline()
    import deepeval
    from deepeval.metrics import BaseMetric, ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall, ToolCallParams
    from agile_eval.metrics.acceptance import AcceptanceMetric
    from agile_eval.metrics.local_model import stub_model

    if importlib.metadata.version("deepeval") != "4.1.8":
        raise RuntimeError("ADR 0015 requires deepeval==4.1.8")
    if not issubclass(AcceptanceMetric, BaseMetric):
        raise RuntimeError("AcceptanceMetric must use the real DeepEval BaseMetric")
    # Exercise ADR 0015's deterministic constructor + score contract. This model
    # raises if called, rather than falling back to a real provider.
    metric = ToolCorrectnessMetric(
        model=stub_model(), async_mode=False, threshold=1.0,
        evaluation_params=[ToolCallParams.INPUT_PARAMETERS],
    )
    metric.measure(LLMTestCase(
        input="dependency smoke test", actual_output="offline",
        tools_called=[ToolCall(name="skill", input_parameters={"skill": "fixture-skill"})],
        expected_tools=[ToolCall(name="skill", input_parameters={"skill": "fixture-skill"})],
    ), _show_indicator=False)
    if metric.score != 1.0:
        raise RuntimeError("DeepEval deterministic metric contract failed")
    print(f"DeepEval 4.1.8 real import and offline metric OK: {deepeval.__file__}")


if __name__ == "__main__":
    verify()
