"""PO matching against master_data/po_master.json (Phase 8).

Exact identifier matching only — never fuzzy-matched, never "corrected". A
PO number that doesn't exist in the master is blank, not the nearest
lookalike. Supplier/currency cross-checks are advisory diagnostics only: a
mismatch is surfaced via the match reason, never auto-corrected.
"""
from __future__ import annotations

from pathlib import Path

from config import MASTER_DATA_DIR
from pipeline.matching.index import load_master_json
from pipeline.matching.match_result import MatchResult, MatchStatus
from pipeline.matching.normalize import normalize_po_number


class PurchaseOrderIndex:
    def __init__(self, master_data_dir: Path = MASTER_DATA_DIR) -> None:
        data = load_master_json(master_data_dir / "po_master.json")
        self.records: list[dict] = data.get("purchase_orders", [])
        self._by_number: dict[str, dict] = {
            normalize_po_number(r["po_number"]): r for r in self.records if r.get("po_number")
        }

    def match_exact(self, po_number: str) -> str:
        """Legacy simple accessor, retained for compatibility — prefer
        `match` for the full diagnostic result."""
        return self.match(po_number).id_or_blank

    def match(self, po_number: str, supplier_id: str = "", currency: str = "") -> MatchResult:
        norm = normalize_po_number(po_number)
        if not norm:
            return MatchResult(status=MatchStatus.UNMATCHED, reason="no PO number given")

        record = self._by_number.get(norm)
        if not record:
            return MatchResult(status=MatchStatus.UNMATCHED, candidate_count=0,
                                reason=f"PO {po_number!r} not found in PO master (no fuzzy fallback)")

        reason = ""
        if supplier_id and record.get("supplier_id") and record["supplier_id"] != supplier_id:
            reason = (
                f"PO {po_number!r} matched but its master supplier_id "
                f"({record['supplier_id']!r}) does not match the resolved supplier "
                f"({supplier_id!r}) — kept as matched (never auto-corrected), flagged for review"
            )
        if currency and record.get("currency") and record["currency"] != currency:
            extra = f"PO {po_number!r} currency ({record.get('currency')!r}) does not match document currency ({currency!r})"
            reason = f"{reason}; {extra}" if reason else extra

        return MatchResult(
            status=MatchStatus.MATCHED,
            matched_id=record["po_id"],
            method="exact_po_number",
            score=1.0,
            candidate_count=1,
            reason=reason,
        )

    def exists(self, po_id: str) -> bool:
        return any(r.get("po_id") == po_id for r in self.records)
