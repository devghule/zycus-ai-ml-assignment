"""Stage: input discovery.

Finds every supported document under ``documents/`` at runtime. The corpus
size is NEVER assumed — not 35, not 42, not any other fixed number. Whatever
is on disk when the run starts is what gets processed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from config import DOCUMENTS_DIR, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredDocument:
    """One input file found on disk, before any processing."""

    path: Path
    stem: str  # filename without extension, used for output naming


def discover_documents(documents_dir: Path = DOCUMENTS_DIR) -> list[DiscoveredDocument]:
    """Return every supported document under ``documents_dir``, sorted for
    deterministic, reproducible ordering across runs.

    Raises FileNotFoundError if the directory itself is missing — that is a
    setup error, not a per-document failure, so it is not swallowed here.
    """
    if not documents_dir.exists():
        raise FileNotFoundError(f"documents directory not found: {documents_dir}")
    if not documents_dir.is_dir():
        raise NotADirectoryError(f"not a directory: {documents_dir}")

    found: list[DiscoveredDocument] = []
    for path in documents_dir.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            logger.debug("skipping unsupported file: %s", path.name)
            continue
        found.append(DiscoveredDocument(path=path, stem=path.stem))

    found.sort(key=lambda d: d.path.name.lower())
    logger.info("discovered %d document(s) in %s", len(found), documents_dir)
    return found


def iter_documents(documents_dir: Path = DOCUMENTS_DIR) -> Iterable[DiscoveredDocument]:
    """Convenience generator form of discover_documents()."""
    yield from discover_documents(documents_dir)
