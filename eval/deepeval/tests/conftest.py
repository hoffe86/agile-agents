"""Keep lightweight parsing optional, but never skip CI's required integration."""
import importlib
import os

import pytest


@pytest.fixture
def deepeval_module():
    if os.environ.get("EVAL_REQUIRE_DEEPEVAL") == "1":
        # An absent/broken dependency is a failure, not an importorskip.
        return importlib.import_module("deepeval")
    return pytest.importorskip("deepeval", reason="DeepEval not installed")
