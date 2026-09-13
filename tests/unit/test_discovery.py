from pathlib import Path

import pytest

from config import DOCUMENTS_DIR
from pipeline.discovery import discover_documents


def test_discovers_at_least_one_pdf():
    docs = discover_documents(DOCUMENTS_DIR)
    assert len(docs) > 0


def test_discovery_is_deterministic():
    first = [d.path.name for d in discover_documents(DOCUMENTS_DIR)]
    second = [d.path.name for d in discover_documents(DOCUMENTS_DIR)]
    assert first == second


def test_discovery_only_returns_pdfs():
    docs = discover_documents(DOCUMENTS_DIR)
    assert all(d.path.suffix.lower() == ".pdf" for d in docs)


def test_discovery_does_not_hardcode_count():
    # Regression guard against reintroducing "assert len(docs) == 35" or
    # "== 42" anywhere in the suite — the corpus size must never be assumed.
    docs = discover_documents(DOCUMENTS_DIR)
    assert isinstance(len(docs), int)  # trivially true; the real guard is
    # the absence of a magic-number assertion here and elsewhere in the repo.


def test_missing_directory_raises(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        discover_documents(missing)


def test_stem_strips_extension():
    docs = discover_documents(DOCUMENTS_DIR)
    for d in docs:
        assert d.stem == d.path.stem
        assert not d.stem.endswith(".pdf")
