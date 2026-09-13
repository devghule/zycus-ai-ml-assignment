"""Central logging configuration.

Every module gets a logger via ``logging.getLogger(__name__)``; this module
just wires up a single, consistent handler/formatter for the whole run so
per-document failures are visible without crashing the batch.
"""
from __future__ import annotations

import logging
import sys

from config import LOG_LEVEL


def configure_logging(level: str = LOG_LEVEL) -> None:
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. re-entrant calls in tests) — don't double up.
        return
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
