"""Compatibility entrypoint for staging declared task inputs."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
    from agile_eval.prepare_inputs import main

    raise SystemExit(main())
