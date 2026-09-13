"""Tax-code matching against master_data/tax_master.json (Phase 8).

Priority, strongest evidence first:
  1. explicit tax code as printed/known (if it actually exists in the master)
  2. composite key: country + tax_type + rate, exact — only if exactly one match
  3. country + rate only, when tax_type is unknown/blank — only if exactly one match
  4. blank

Rate alone is never sufficient (many countries/types share a rate, e.g. 19%
VAT in Germany vs. a different country's tax at the same nominal rate).
An explicit document tax code always wins over a re-derived candidate.
"""
from __future__ import annotations

from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.index import load_master_json
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.normalize import normalize_country

_RATE_TOLERANCE = 0.005  # percentage points; guards against float noise, not real ambiguity


def _rates_equal(a: float, b: float) -> bool:
    return abs(a - b) <= _RATE_TOLERANCE


class TaxIndex:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        data = load_master_json(master_data_dir / "tax_master.json")
        self.records: list[dict] = data.get("taxes", [])
        self._by_code: dict[str, dict] = {r["code"]: r for r in self.records if r.get("code")}

    def match_by_explicit_code(self, tax_code: str) -> MatchResult:
        code = (tax_code or "").strip()
        record = self._by_code.get(code)
        if record:
            return MatchResult(status=MatchStatus.MATCHED, matched_id=record["code"],
                                method="explicit_tax_code", score=1.0, candidate_count=1)
        return MatchResult(status=MatchStatus.UNMATCHED, reason=f"tax code {tax_code!r} not in master")

    def match(self, country: str = "", tax_type: str = "", rate: float | None = None) -> MatchResult:
        norm_country = normalize_country(country)
        norm_type = (tax_type or "").strip().upper()

        if not norm_country or rate is None:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="insufficient evidence (need country + rate)")

        candidates = [r for r in self.records if normalize_country(r.get("country", "")) == norm_country]
        if norm_type:
            type_matched = [r for r in candidates if (r.get("tax_type") or "").strip().upper() == norm_type]
            if type_matched:
                candidates = type_matched
            # If no candidate has this tax_type, fall through and let the
            # country+rate-only path (below) decide — an unrecognized
            # tax_type label shouldn't by itself block a rate-based match
            # when the rate alone is unambiguous within the country.

        rate_matched = [r for r in candidates if _rates_equal(float(r.get("rate", -1)), rate)]

        if not rate_matched:
            return MatchResult(status=MatchStatus.UNMATCHED, candidate_count=0,
                                reason=f"no tax found for country={norm_country!r} rate={rate}")

        distinct_codes = {r["code"] for r in rate_matched}
        if len(distinct_codes) > 1:
            return MatchResult(
                status=MatchStatus.AMBIGUOUS,
                candidate_count=len(distinct_codes),
                reason=f"{len(distinct_codes)} tax codes match country={norm_country!r} rate={rate}: "
                f"{sorted(distinct_codes)} — refusing to pick one",
            )

        method = "country_type_rate" if norm_type else "country_rate_only"
        return MatchResult(status=MatchStatus.MATCHED, matched_id=rate_matched[0]["code"],
                            method=method, score=1.0, candidate_count=1)

    def exists(self, tax_code: str) -> bool:
        return (tax_code or "").strip() in self._by_code
