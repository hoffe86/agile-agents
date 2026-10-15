"""Required dependency-present CI gate. No judge, credentials or model calls."""
from __future__ import annotations

import importlib.metadata
import os


def verify() -> None:
    # Must precede imports; this is telemetry configuration, NOT OS isolation.
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"
    os.environ["DEEPEVAL_DISABLE_PROGRESS_BAR"] = "1"
    import deepeval
    from deepeval.metrics import BaseMetric, ToolCorrectnessMetric
    from deepeval.test_case import LLMTestCase, ToolCall
    from metrics.acceptance import AcceptanceMetric
    from metrics.local_model import stub_model

    if importlib.metadata.version("deepeval") != "4.1.8":
        raise RuntimeError("ADR 0015 requires deepeval==4.1.8")
    if not issubclass(AcceptanceMetric, BaseMetric):
        raise RuntimeError("AcceptanceMetric must use the real DeepEval BaseMetric")
    # Exercise ADR 0015's deterministic constructor + score contract. This model
    # raises if called, rather than falling back to a real provider.
    metric = ToolCorrectnessMetric(model=stub_model())
    metric.measure(LLMTestCase(
        input="dependency smoke test", actual_output="offline",
        tools_called=[ToolCall(name="skill")],
        expected_tools=[ToolCall(name="skill")],
    ))
    if metric.score != 1.0:
        raise RuntimeError("DeepEval deterministic metric contract failed")
    print(f"DeepEval 4.1.8 real import and offline metric OK: {deepeval.__file__}")


if __name__ == "__main__":
    verify()
