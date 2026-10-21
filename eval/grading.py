"""Compatibility entrypoint for grading status and parser diagnostics."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
    from agile_eval.grading import main

    raise SystemExit(main())
