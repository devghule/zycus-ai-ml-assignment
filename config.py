"""Central configuration for the Bookable Payable pipeline.

No secrets live here. Paths are resolved relative to this file so the tool
works regardless of the caller's current working directory.
"""
from __future__ import annotations

from pathlib import Path

# Project root = the directory this file lives in (the kit root: documents/,
# master_data/, erp.py, etc. are all siblings of this file).
ROOT_DIR = Path(__file__).resolve().parent

DOCUMENTS_DIR = ROOT_DIR / "documents"
OUTPUT_DIR = ROOT_DIR / "output"
MASTER_DATA_DIR = ROOT_DIR / "master_data"

# Cache for rendered page images / extracted text, so re-runs don't re-render.
CACHE_DIR = ROOT_DIR / ".cache"

SUPPORTED_EXTENSIONS = {".pdf"}

LOG_LEVEL = "INFO"
