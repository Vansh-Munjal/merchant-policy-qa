"""Date-aware view of the policy.

Two responsibilities:

1. Timeline: for a master clause id and an as_of_date, which text is in force?
   Built purely from what document_loader parsed (circular ops + effective dates).

2. Facts: the handful of numbers each clause version states (rates, caps, limits),
   written down once by hand. Every fact value is a literal substring of the
   clause it belongs to; tests/test_policy_engine.py enforces that, so a fact
   can never drift from (or be invented beyond) the source text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from .models import Citation, Clause

# (doc_kind, clause_id) -> {fact_name: literal text from that clause}
FACTS: dict[tuple[str, str], dict[str, str]] = {
    ("master", "1.1"): {"upi_standard": "T+1", "working_days_exclude": "exclude Sundays and bank holidays"},
    ("circular", "A"): {"upi_standard": "T+1", "upi_instant": "T+0", "instant_addon": "Instant Settlement"},
    ("master", "1.2"): {"card": "T+2"},
    ("master", "2.1"): {"rate_pct": "0.30", "threshold_lakh": "10"},
    ("circular", "B"): {"rate_pct": "0.25", "threshold_lakh": "10"},
    ("master", "2.2"): {"rate_pct": "0.50", "threshold_lakh": "10"},
    ("master", "2.3"): {"cap_all": "15"},
    ("circular", "C"): {"cap_small": "15", "cap_large": "25"},
    ("master", "2.4"): {"gst_pct": "18", "gst_outside_cap": "not part of the MDR cap"},
    ("master", "3.1"): {"refund_window_days": "90"},
    ("master", "3.3"): {"reversal_hours": "24"},
    ("master", "3.4"): {"chargeback_days": "120"},
    ("master", "4.1"): {"per_txn": "1,00,000"},
    ("master", "4.2"): {"enhanced_per_txn": "2,00,000"},
    ("master", "4.3"): {"daily": "1,00,000"},
    ("circular", "E"): {"daily": "1,00,000", "bank_limit_rule": "whichever is lower"},
    ("master", "5.1"): {"notice_days": "30"},
    ("master", "5.2"): {"release_working_days": "10", "deduct_dues": "after deducting outstanding dues"},
}

# What the (non-authoritative) FAQ claims, keyed by FAQ entry. Same literal rule.
FAQ_CLAIMS: dict[str, dict[str, str]] = {
    "Q1": {"upi": "Next working day", "card": "two working days"},
    "Q2": {"rate_small": "0.30", "rate_large": "0.50", "cap": "no upper limit"},
    "Q3": {"reversal_hours": "24"},
    "Q4": {"per_txn": "1,00,000", "enhanced_per_txn": "2,00,000"},
    "Q5": {"notice_days": "30", "release_days": "10 days"},
}


def to_decimal(literal: str) -> Decimal:
    """'1,00,000' -> Decimal('100000'); '0.30' -> Decimal('0.30')."""
    return Decimal(literal.replace(",", ""))


@dataclass
class ClauseVersion:
    """The state of one master clause on a given date."""
    clause_id: str
    base: Clause                                         # the master text
    in_force: Optional[Clause]                           # master or circular item; None if deleted
    applied: list[Clause] = field(default_factory=list)  # circular items in effect on as_of
    pending: list[Clause] = field(default_factory=list)  # circular items not yet in effect

    @property
    def deleted(self) -> bool:
        return self.in_force is None

    @property
    def superseded(self) -> bool:
        return bool(self.applied)

    def facts(self) -> dict[str, str]:
        if self.in_force is None:
            return {}
        return FACTS.get((self.in_force.doc_kind, self.in_force.clause_id), {})

    def original_facts(self) -> dict[str, str]:
        return FACTS.get(("master", self.clause_id), {})

    def citations(self) -> list[Citation]:
        cites = [cite(self.base)]
        cites += [cite(c) for c in self.applied]
        return cites


def cite(clause: Clause) -> Citation:
    return Citation(clause.document, clause.clause_id, clause.text)


class PolicyEngine:
    def __init__(self, corpus: list[Clause]):
        self.corpus = corpus
        self.master = {c.clause_id: c for c in corpus if c.doc_kind == "master"}
        self.circular = [c for c in corpus if c.doc_kind == "circular"]
        self.faq = {c.clause_id: c for c in corpus if c.doc_kind == "faq"}
        self.master_effective = min(c.effective_from for c in self.master.values())

    def in_scope(self, as_of: date) -> bool:
        """No policy document is in force before the master's effective date."""
        return as_of >= self.master_effective

    def version(self, clause_id: str, as_of: date) -> ClauseVersion:
        base = self.master[clause_id]
        v = ClauseVersion(clause_id, base, in_force=base)
        # Circular items touching this clause, applied in effective-date order.
        touching = [c for c in self.circular
                    if c.target == clause_id or clause_id in c.also_affects]
        for item in sorted(touching, key=lambda c: c.effective_from):
            if item.effective_from > as_of:
                v.pending.append(item)
                continue
            v.applied.append(item)
            if item.target == clause_id:
                v.in_force = None if item.op == "deleted" else item
            # also_affects (e.g. item D on 3.2) modifies meaning but not the text in force
        return v

    def fact(self, clause_id: str, name: str, as_of: date) -> Optional[str]:
        return self.version(clause_id, as_of).facts().get(name)

    def faq_entry(self, entry_id: str) -> Clause:
        return self.faq[entry_id]
