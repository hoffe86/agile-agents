"""Model providers for the DeepEval spike.

Two concerns live here, both driven by findings recorded in ADR 0015.

**Telemetry.** DeepEval sends event names, metric names, an anonymous UUID and the
caller's public IP to PostHog unless opted out. `configure_offline()` disables it, and is
imported for its side effect before any DeepEval import that might initialise telemetry.

**Model selection.** Some metrics need a real model (Task Completion, Plan Adherence);
others need one only to satisfy a constructor and never call it (`ToolCorrectness` scored
correctly with `llm_calls=0`). `StubModel` covers the latter without a key, so the
skill-bypass measurement runs with no credentials and no network at all.
"""

from __future__ import annotations

import os

# Set before DeepEval is imported anywhere -- opting out after the fact is too late.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
os.environ.setdefault("DEEPEVAL_DISABLE_PROGRESS_BAR", "1")


def configure_offline() -> None:
    """Force the no-telemetry, no-cloud posture. Safe to call repeatedly."""
    os.environ["DEEPEVAL_TELEMETRY_OPT_OUT"] = "1"


class StubModelCalled(AssertionError):
    """Raised if a metric assumed deterministic actually invokes the model."""


def stub_model(name: str = "stub-no-llm"):
    """A model that satisfies a metric's constructor but must never be called.

    `ToolCorrectnessMetric.__init__` calls `initialize_model()`, which reaches for
    `OPENAI_API_KEY` and raises without one -- even though the metric never invokes the
    model while scoring (verified: `llm_calls=0` with a correct score). Passing this stub
    keeps the deterministic metrics free of credentials and network.

    DeepEval type-checks the model with `isinstance`, so this must genuinely subclass
    `DeepEvalBaseLLM`; duck typing is rejected. The class is built lazily so this module
    stays importable without DeepEval installed.

    It raises if anything ever does generate, so a future version quietly starting to
    call the model surfaces loudly instead of silently costing tokens.
    """
    configure_offline()
    from deepeval.models import DeepEvalBaseLLM

    class _StubModel(DeepEvalBaseLLM):
        def __init__(self) -> None:
            super().__init__(model=name)

        def load_model(self, *args, **kwargs):
            return self

        def get_model_name(self, *args, **kwargs) -> str:
            return name

        def generate(self, *args, **kwargs):
            raise StubModelCalled(
                "stub_model() was asked to generate. A metric assumed deterministic now "
                "needs an LLM -- pick a real provider rather than widening this stub."
            )

        async def a_generate(self, *args, **kwargs):
            return self.generate(*args, **kwargs)

    return _StubModel()


def azure_openai_model(**overrides):
    """Azure OpenAI provider, for the metrics that genuinely need a model.

    Reads the standard DeepEval Azure variables. Supports Entra ID via
    `azure_ad_token_provider`, so CI can stay passwordless rather than holding a key:

        AZURE_OPENAI_ENDPOINT     e.g. https://<resource>.openai.azure.com/
        AZURE_DEPLOYMENT_NAME     the deployment, not the model
        AZURE_MODEL_NAME          e.g. gpt-4.1
        OPENAI_API_VERSION        e.g. 2025-01-01-preview
        AZURE_OPENAI_API_KEY      omit when using Entra ID
    """
    configure_offline()
    from deepeval.models import AzureOpenAIModel

    return AzureOpenAIModel(**overrides)
