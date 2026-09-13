"""Buyer/business-unit matching against master_data/chart_of_books.json
(Phase 8).

Locked policy: buyer/BU inference from country is allowed ONLY when the
buyer's country maps to EXACTLY ONE valid business unit. If a country maps
to zero or multiple business units, the result is blank — never "closest"
guessing. Supplier country must never be used to infer the BUYER's BU.

Country association: this master's business units don't carry an explicit
`country` field, but each `business_unit_code` is itself scoped by a
2-letter country prefix (e.g. "EE001", "GH001") — this is genuine
structural evidence in the master data itself, not an inferred heuristic
layered on top. Estonia ("EE") has two business units in the sample data
(EE001, EE004), which is exactly the ambiguous case the locked policy exists
to handle: it must resolve to blank, not a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.index import load_master_json
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.normalize import normalize_country

_BU_CODE_COUNTRY_RE = re.compile(r"^([A-Z]{2})\d+$")


@dataclass
class BuyerCodes:
    company_code: str = ""
    business_unit_code: str = ""
    location_code: str = ""


@dataclass
class BuyerUnit:
    """Internal flattened representation of one (company, business_unit,
    location) combination for matching purposes."""

    company_code: str
    business_unit_code: str
    location_code: str
    country: str  # derived from the business_unit_code prefix


class ChartOfBooksIndex:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        data = load_master_json(master_data_dir / "chart_of_books.json")
        self.companies: list[dict] = data.get("companies", [])

        self._units: list[BuyerUnit] = []
        self._by_bu_code: dict[str, BuyerUnit] = {}
        self._by_country: dict[str, list[BuyerUnit]] = {}

        for company in self.companies:
            company_code = company.get("company_code", "")
            for bu in company.get("business_units", []):
                bu_code = bu.get("business_unit_code", "")
                m = _BU_CODE_COUNTRY_RE.match(bu_code)
                country = m.group(1) if m else ""
                for loc in bu.get("locations", []):
                    unit = BuyerUnit(
                        company_code=company_code,
                        business_unit_code=bu_code,
                        location_code=loc.get("location_code", ""),
                        country=country,
                    )
                    self._units.append(unit)
                    if bu_code:
                        self._by_bu_code[bu_code] = unit
                    if country:
                        self._by_country.setdefault(country, []).append(unit)

    def match_by_explicit_bu_code(self, business_unit_code: str) -> MatchResult:
        """Exact evidence path: the document/extraction already identified a
        specific business_unit_code (e.g. from a known buyer reference)."""
        code = (business_unit_code or "").strip().upper()
        unit = self._by_bu_code.get(code)
        if unit:
            return MatchResult(status=MatchStatus.MATCHED, matched_id=unit.business_unit_code,
                                method="exact_bu_code", score=1.0, candidate_count=1)
        return MatchResult(status=MatchStatus.UNMATCHED, reason=f"BU code {business_unit_code!r} not in master")

    def match_by_buyer_country(self, buyer_country: str) -> MatchResult:
        """Country-inference path. NEVER pass a supplier's country here —
        this must only ever be called with the BUYER's (tenant's) country."""
        norm = normalize_country(buyer_country)
        if not norm:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="no buyer country evidence")

        candidates = self._by_country.get(norm, [])
        if not candidates:
            return MatchResult(status=MatchStatus.UNMATCHED, candidate_count=0,
                                reason=f"no business unit found for country {norm!r}")

        distinct_bu_codes = {u.business_unit_code for u in candidates}
        if len(distinct_bu_codes) > 1:
            return MatchResult(
                status=MatchStatus.AMBIGUOUS,
                candidate_count=len(distinct_bu_codes),
                reason=f"{len(distinct_bu_codes)} business units exist for country {norm!r}: "
                f"{sorted(distinct_bu_codes)} — refusing to pick one",
            )

        unit = candidates[0]
        return MatchResult(
            status=MatchStatus.MATCHED,
            matched_id=unit.business_unit_code,
            method="country_unique_bu",
            score=1.0,
            candidate_count=1,
        )

    def to_buyer_codes(self, business_unit_code: str) -> BuyerCodes:
        """Given a resolved business_unit_code, return the full triple
        (company_code, business_unit_code, location_code). Returns an empty
        BuyerCodes if the code doesn't exist (fail safe, never fabricate)."""
        unit = self._by_bu_code.get((business_unit_code or "").strip().upper())
        if not unit:
            return BuyerCodes()
        return BuyerCodes(
            company_code=unit.company_code,
            business_unit_code=unit.business_unit_code,
            location_code=unit.location_code,
        )

    def match_by_country(self, country: str) -> BuyerCodes:
        """Convenience wrapper combining match_by_buyer_country + to_buyer_codes,
        kept for callers that just want the final codes (blank on any
        non-MATCHED result)."""
        result = self.match_by_buyer_country(country)
        if result.status != MatchStatus.MATCHED:
            return BuyerCodes()
        return self.to_buyer_codes(result.matched_id)

    def exists(self, business_unit_code: str) -> bool:
        return (business_unit_code or "").strip().upper() in self._by_bu_code
