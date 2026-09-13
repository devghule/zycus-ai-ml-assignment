"""Stage: final output assembly.

Builds the exact per-file wrapper the brief requires:

    {"file": "X.pdf", "payables": [...], "declined": [...]}

and writes it to output/X.json. This module is real (not a stub) from
Phase 1 on — later phases feed it real payables/declined entries, but the
wrapper shape and file-writing behavior don't change.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import OUTPUT_DIR

logger = logging.getLogger(__name__)


@dataclass
class DocumentResult:
    """Everything produced for one input PDF, before serialization."""

    file_name: str
    payables: list[dict[str, Any]] = field(default_factory=list)
    declined: list[dict[str, Any]] = field(default_factory=list)

    def to_wrapper(self) -> dict[str, Any]:
        return {
            "file": self.file_name,
            "payables": self.payables,
            "declined": self.declined,
        }


def declined_entry(doc_type: str, reason: str) -> dict[str, Any]:
    """Build a schema-shaped declined[] entry (doc_type + reason only)."""
    return {"doc_type": doc_type, "reason": reason}


def write_result(result: DocumentResult, output_dir: Path = OUTPUT_DIR) -> Path:
    """Write one document's result to output/<stem>.json. Output naming is
    deterministic: same stem as the input PDF, .json extension."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(result.file_name).stem
    out_path = output_dir / f"{stem}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result.to_wrapper(), fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    logger.debug("wrote %s", out_path)
    return out_path
