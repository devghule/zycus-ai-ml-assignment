"""Shared master-data loading helpers.

Each matcher (suppliers.py, chart_of_books.py, ...) builds its own index
structure on top of this — see DESIGN.md for why matching strategy differs
per master file (VAT-ID exact vs. country-inference vs. composite-key vs.
exact-only PO) rather than one generic fuzzy-matcher over everything.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_master_json(path: Path) -> Any:
    """Load one master-data JSON file. Raises if missing/malformed — a
    missing master file is a setup error, not a per-document one."""
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
