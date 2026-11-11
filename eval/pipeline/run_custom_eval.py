"""Run one custom-eval task live through dev-lead (see agile_eval.custom_eval.runner)."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from agile_eval.custom_eval.runner import main

    raise SystemExit(main())
