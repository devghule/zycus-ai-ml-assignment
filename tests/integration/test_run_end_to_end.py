"""Phase 1 end-to-end proof: python run.py discovers every real PDF in
documents/ and writes one schema-shaped output/<stem>.json per PDF.

Runs against a temp copy of the output directory (via monkeypatching config)
so repeated test runs don't depend on / clobber a real output/ folder state
in a way that hides bugs, while still exercising the real documents/ corpus
and the real discovery/render/segment/classify stub chain.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
import run
from pipeline.discovery import discover_documents


def test_run_produces_one_output_file_per_discovered_pdf(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run, "OUTPUT_DIR", output_dir)

    discovered = discover_documents(config.DOCUMENTS_DIR)
    assert len(discovered) > 0, "expected at least one real PDF under documents/"

    exit_code = run.main()
    assert exit_code == 0

    output_files = sorted(output_dir.glob("*.json"))
    assert len(output_files) == len(discovered)

    discovered_stems = {d.stem for d in discovered}
    output_stems = {f.stem for f in output_files}
    assert discovered_stems == output_stems


def test_every_output_file_has_required_top_level_keys(tmp_path: Path, monkeypatch):
    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run, "OUTPUT_DIR", output_dir)

    run.main()

    for out_file in output_dir.glob("*.json"):
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert set(data.keys()) == {"file", "payables", "declined"}
        assert isinstance(data["payables"], list)
        assert isinstance(data["declined"], list)


def test_a_single_bad_pdf_does_not_crash_the_batch(tmp_path: Path, monkeypatch):
    """Error isolation: one unreadable file among many must not stop the
    other files from being processed."""
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    (documents_dir / "good.pdf").write_bytes(b"%PDF-1.4 not a real pdf but a file")
    (documents_dir / "corrupt.pdf").write_bytes(b"")  # empty / unreadable

    output_dir = tmp_path / "output"
    monkeypatch.setattr(config, "DOCUMENTS_DIR", documents_dir)
    monkeypatch.setattr(config, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(run, "DOCUMENTS_DIR", documents_dir)
    monkeypatch.setattr(run, "OUTPUT_DIR", output_dir)

    exit_code = run.main()
    assert exit_code == 0
    assert (output_dir / "good.json").exists()
    assert (output_dir / "corrupt.json").exists()
