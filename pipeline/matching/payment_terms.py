"""Payment-term matching against master_data/payment_terms.json (Phase 8).

Priority:
  1. exact normalized text match against a master record's text_aliases
  2. unique day-count match (only when exactly one master record has that
     day count — the sample master data has TWO records sharing days=0
     ["Immediate" and "Monthly_in_advance"], which is exactly the kind of
     ambiguity this must resolve to blank rather than guess)
  3. blank

Text and day-count evidence are independent: if the raw text yields a
match, that's used directly (text is closer to the source document than a
derived day count); day-count inference is a fallback for when a
recognizable payment-term string is not directly evidenced but explicit
invoice/due dates are.
"""
from __future__ import annotations

from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.index import load_master_json
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.normalize import normalize_payment_term_text


class PaymentTermIndex:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        data = load_master_json(master_data_dir / "payment_terms.json")
        self.records: list[dict] = data.get("payment_terms", [])

        self._by_alias: dict[str, dict] = {}
        self._by_days: dict[int, list[dict]] = {}
        for r in self.records:
            for alias in r.get("text_aliases", []):
                self._by_alias[normalize_payment_term_text(alias)] = r
            days = r.get("days")
            if days is not None:
                self._by_days.setdefault(int(days), []).append(r)

    def match_by_text(self, text: str) -> MatchResult:
        norm = normalize_payment_term_text(text)
        if not norm:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="no payment-term text given")
        record = self._by_alias.get(norm)
        if record:
            return MatchResult(status=MatchStatus.MATCHED, matched_id=record["payment_term_id"],
                                method="exact_text_alias", score=1.0, candidate_count=1)
        return MatchResult(status=MatchStatus.UNMATCHED, reason=f"{text!r} matches no known alias")

    def match_by_days(self, days: int) -> MatchResult:
        candidates = self._by_days.get(days, [])
        if not candidates:
            return MatchResult(status=MatchStatus.UNMATCHED, candidate_count=0,
                                reason=f"no payment term with days={days}")
        distinct_ids = {r["payment_term_id"] for r in candidates}
        if len(distinct_ids) > 1:
            return MatchResult(
                status=MatchStatus.AMBIGUOUS,
                candidate_count=len(distinct_ids),
                reason=f"{len(distinct_ids)} payment terms share days={days}: {sorted(distinct_ids)} "
                "— refusing to pick one",
            )
        return MatchResult(status=MatchStatus.MATCHED, matched_id=candidates[0]["payment_term_id"],
                            method="unique_day_count", score=1.0, candidate_count=1)

    def match_by_dates(self, invoice_date: str, due_date: str) -> MatchResult:
        """Derive a day count from two ISO dates and match by it. Returns
        UNMATCHED (not a raised error) for missing/malformed dates — this
        is a best-effort fallback path, not a required one."""
        from datetime import date

        try:
            d1 = date.fromisoformat(invoice_date)
            d2 = date.fromisoformat(due_date)
        except (TypeError, ValueError):
            return MatchResult(status=MatchStatus.UNMATCHED, reason="invoice_date/due_date not both valid ISO dates")
        days = (d2 - d1).days
        if days < 0:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="due_date precedes invoice_date")
        return self.match_by_days(days)

    def exists(self, payment_term_id: str) -> bool:
        return any(r.get("payment_term_id") == payment_term_id for r in self.records)
