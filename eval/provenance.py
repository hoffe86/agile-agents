"""Compatibility entrypoint for offline run provenance."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
    from agile_eval.provenance import main

    raise SystemExit(main())
