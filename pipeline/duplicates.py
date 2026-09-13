"""Deprecated Phase 1 stub — superseded by pipeline/duplicate_detection.py
(Phase 9), which implements the real five-layer, booking-aware duplicate
policy described in DESIGN.md. Kept only so any historical import of this
module path doesn't break; new code should import from
pipeline.duplicate_detection directly.
"""
from __future__ import annotations

from pipeline.duplicate_detection import DuplicateCheck, DuplicateVerdict  # noqa: F401
