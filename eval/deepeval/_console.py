"""Console setup shared by the eval entry points.

Kept in one place rather than copied into each script: a fix duplicated across files is
the drift pattern this harness has been bitten by repeatedly.
"""

from __future__ import annotations

import sys


def use_utf8_stdio() -> None:
    """Make stdout/stderr tolerate non-latin-1 output.

    Judge responses and agent logs contain box-drawing characters, em dashes and emoji.
    Windows consoles default to cp1252, where printing one raises UnicodeEncodeError —
    which once destroyed a grade that had already been paid for, after the judging work
    was complete. Replacement characters are strictly better than losing the output.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):  # pragma: no cover - non-reconfigurable stream
            pass
