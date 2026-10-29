"""Score custom-eval runs with DeepEval (see agile_eval.custom_eval.scorer)."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from agile_eval.custom_eval.scorer import main

    raise SystemExit(main())
