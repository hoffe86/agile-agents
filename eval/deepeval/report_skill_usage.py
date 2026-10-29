"""Compatibility entrypoint for offline skill-usage reports."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
    from agile_eval.report_skill_usage import main

    raise SystemExit(main())
