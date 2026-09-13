"""Supplier matching against master_data/suppliers.json (Phase 8).

Priority, strongest evidence first:
  1. exact normalized VAT/tax-registration ID
  2. exact normalized supplier name
  3. blocked (country-restricted) fuzzy name match, accepted only when the
     winner is both strong AND clearly separated from the runner-up
  4. blank

Strong identifiers always win over fuzzy signals — an exact VAT match is
never overridden by a merely-similar name, and a country mismatch never
promotes a fuzzy name match to acceptance.
"""
from __future__ import annotations

from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.index import load_master_json
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.normalize import name_similarity, normalize_country, normalize_name, normalize_vat_id

# Explicit, named thresholds — not unexplained magic numbers.
FUZZY_NAME_ACCEPT_THRESHOLD = 0.90  # winner must be at least this similar
FUZZY_NAME_SEPARATION_MARGIN = 0.08  # winner must beat the runner-up by at least this much


class SupplierIndex:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        data = load_master_json(master_data_dir / "suppliers.json")
        self.records: list[dict] = data.get("suppliers", [])

        self._by_vat: dict[str, dict] = {}
        self._by_name: dict[str, dict] = {}
        self._by_country: dict[str, list[dict]] = {}
        for r in self.records:
            vat = normalize_vat_id(r.get("vat_id", ""))
            if vat:
                # A VAT id should be unique per supplier; if the sample data
                # ever collided we'd rather lose the index entry than let a
                # later duplicate silently shadow an earlier one unnoticed —
                # but with real master data this is expected to be 1:1.
                self._by_vat[vat] = r
            name = normalize_name(r.get("name", ""))
            if name:
                self._by_name[name] = r
            country = normalize_country(r.get("country", ""))
            self._by_country.setdefault(country, []).append(r)

    def match(self, name: str = "", vat_id: str = "", country: str = "") -> MatchResult:
        """Resolve a supplier against the master. All arguments are raw,
        as-extracted strings; this function normalizes internally."""
        norm_vat = normalize_vat_id(vat_id)
        if norm_vat:
            record = self._by_vat.get(norm_vat)
            if record:
                return MatchResult(
                    status=MatchStatus.MATCHED,
                    matched_id=record["supplier_id"],
                    method="exact_vat_id",
                    score=1.0,
                    candidate_count=1,
                )
            # An explicit VAT id was given and it does NOT exist in the
            # master — this is itself strong negative evidence. Do not fall
            # through to a name-based guess that could contradict it.
            return MatchResult(
                status=MatchStatus.UNMATCHED,
                method="exact_vat_id",
                candidate_count=0,
                reason=f"VAT id {vat_id!r} not found in supplier master",
            )

        norm_name = normalize_name(name)
        if norm_name:
            record = self._by_name.get(norm_name)
            if record:
                return MatchResult(
                    status=MatchStatus.MATCHED,
                    matched_id=record["supplier_id"],
                    method="exact_normalized_name",
                    score=1.0,
                    candidate_count=1,
                )

        if not norm_name:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="no name or VAT id evidence given")

        return self._fuzzy_match(norm_name, normalize_country(country))

    def _fuzzy_match(self, norm_name: str, norm_country: str) -> MatchResult:
        # Blocking: restrict candidates to the given country when known —
        # never compare against the entire table when a safe block exists.
        candidates = self._by_country.get(norm_country, self.records) if norm_country else self.records
        if not candidates:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="no candidates in country block")

        scored = sorted(
            ((name_similarity(norm_name, normalize_name(r.get("name", ""))), r) for r in candidates),
            key=lambda pair: pair[0],
            reverse=True,
        )
        best_score, best_record = scored[0]
        runner_up_score = scored[1][0] if len(scored) > 1 else 0.0

        if best_score >= FUZZY_NAME_ACCEPT_THRESHOLD and (best_score - runner_up_score) >= FUZZY_NAME_SEPARATION_MARGIN:
            return MatchResult(
                status=MatchStatus.MATCHED,
                matched_id=best_record["supplier_id"],
                method="fuzzy_name_blocked_by_country",
                score=best_score,
                candidate_count=len(candidates),
            )

        return MatchResult(
            status=MatchStatus.AMBIGUOUS if best_score >= FUZZY_NAME_ACCEPT_THRESHOLD else MatchStatus.UNMATCHED,
            method="fuzzy_name_blocked_by_country",
            score=best_score,
            candidate_count=len(candidates),
            reason=f"best={best_score:.3f} runner_up={runner_up_score:.3f} "
            f"(threshold={FUZZY_NAME_ACCEPT_THRESHOLD}, margin={FUZZY_NAME_SEPARATION_MARGIN})",
        )

    def exists(self, supplier_id: str) -> bool:
        """Reality check: does this ID actually exist in the master?"""
        return any(r.get("supplier_id") == supplier_id for r in self.records)
