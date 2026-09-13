"""Shared internal match-result contract for every Phase 8 matcher.

Kept separate from the final AUTODRAFT_SCHEMA.md-shaped output — schema
output only ever sees the plain matched ID string (or ""); everything here
(method, score, candidate_count, reason) is internal diagnostic information
for debugging/audit and must never leak into the emitted JSON.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"  # no candidate at all
    AMBIGUOUS = "AMBIGUOUS"  # multiple candidates, none clearly separated


@dataclass
class MatchResult:
    status: MatchStatus
    matched_id: str = ""  # "" unless status == MATCHED
    method: str = ""  # e.g. "exact_vat_id", "country_unique_bu", "fuzzy_name"
    score: float = 0.0
    candidate_count: int = 0
    reason: str = ""

    @property
    def id_or_blank(self) -> str:
        """The only thing that should ever reach the final schema output."""
        return self.matched_id if self.status == MatchStatus.MATCHED else ""
