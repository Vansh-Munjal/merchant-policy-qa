"""ask(question, as_of_date) -> Answer.

Pipeline:
  1. resolve as_of_date (argument > date written in the question > 15 Aug 2026)
  2. parse entities (amounts, tier, method, timing) and retrieve matching passages
  3. route to a topic handler (settlement, fee, refund, limits, closure, FAQ check)
  4. the handler reads the clause versions in force on as_of_date, computes with
     calculator.py, and compares against the superseded master text and the FAQ
  5. status = CONFLICT_RESOLVED only if a superseded clause or the FAQ would have
     produced a *different* answer; CANNOT_ANSWER when the documents don't settle it
Unrouted questions fall back to retrieval, and only answer if one in-force clause
covers most of the question.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Union

from .calculator import add_working_days, fmt_inr, upi_fee, FeeBreakdown
from .document_loader import DATA_DIR, load_corpus
from .models import Answer, Citation, Status
from .policy_engine import FAQ_CLAIMS, PolicyEngine, cite, to_decimal
from .question_parser import LAKH, Parsed, find_date, parse
from .retriever import Retriever

DEFAULT_AS_OF = date(2026, 8, 15)
CIRCULAR_NAME = "Circular MS/2026/17"


def _d(x: date) -> str:
    return x.strftime("%d %b %Y")


@dataclass
class Draft:
    """Accumulates one answer while a handler works."""
    lines: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)   # how each conflict was resolved
    notes: list[str] = field(default_factory=list)
    cannot_answer: bool = False
    trace: dict = field(default_factory=dict)

    def say(self, line: str) -> None:
        self.lines.append(line)

    def cite(self, *cites: Citation) -> None:
        for c in cites:
            if all((c.document, c.clause) != (x.document, x.clause) for x in self.citations):
                self.citations.append(c)

    def status(self) -> Status:
        if self.cannot_answer:
            return Status.CANNOT_ANSWER
        return Status.CONFLICT_RESOLVED if self.conflicts else Status.ANSWERED


class Assistant:
    def __init__(self, data_dir: Path = DATA_DIR):
        corpus = load_corpus(data_dir)
        self.engine = PolicyEngine(corpus)
        self.retriever = Retriever(corpus)

    # ------------------------------------------------------------------ entry point
    def ask(self, question: str, as_of_date: Union[date, str, None] = None) -> Answer:
        as_of, date_source = self._resolve_date(question, as_of_date)
        p = parse(question, as_of)
        hits = self.retriever.search(question)
        d = Draft()

        if not self.engine.in_scope(as_of):
            d.cannot_answer = True
            d.say(f"No policy document in the corpus is in force on {_d(as_of)}: the Master "
                  f"Document takes effect on {_d(self.engine.master_effective)}.")
            d.cite(cite(self.engine.master["1.1"]))
            intent = "out_of_scope_date"
        else:
            intent = self._route(question.lower())
            getattr(self, f"_h_{intent}")(p, as_of, d, hits)

        answer = " ".join(d.lines + d.notes)
        return Answer(
            answer=answer,
            citations=d.citations,
            status=d.status(),
            resolution=" ".join(d.conflicts) if d.conflicts and not d.cannot_answer else None,
            as_of_date=as_of,
            diagnostics={
                "intent": intent,
                "as_of_source": date_source,
                "entities": {k: (str(v) if v is not None else None) for k, v in vars(p).items() if k != "text"},
                "retrieved": [f"{h.clause.document} §{h.clause.clause_id} ({h.coverage:.2f})" for h in hits],
                **d.trace,
            },
        )

    @staticmethod
    def _resolve_date(question: str, as_of_date) -> tuple[date, str]:
        if isinstance(as_of_date, str):
            return date.fromisoformat(as_of_date), "argument"
        if isinstance(as_of_date, date):
            return as_of_date, "argument"
        in_q = find_date(question)
        return (in_q, "question") if in_q else (DEFAULT_AS_OF, "default")

    @staticmethod
    def _route(q: str) -> str:
        if "annexure" in q or re.search(r"(what|which|how).*(enhanced kyc).*(require|document|need|involve|process)", q):
            return "missing_reference"
        if "faq" in q:
            return "faq_check"
        if re.search(r"refund|reversal|reverse", q):
            return "refund"
        if re.search(r"\bclos(e|ed|ing|ure)\b", q) and "account" in q:
            return "closure"
        if re.search(r"settle|settlement|receive .*money|get (my |the )?(upi |card )?money|payout|credited|when will i (get|receive)", q):
            return "settlement"
        if re.search(r"\bmdr\b|\bfees?\b|\bgst\b|charges?\b|commission|what do(es)? (they|i|we|the merchant) pay|how much .*pay", q):
            return "fee"
        if re.search(r"limit|maximum|\bmax\b|twice|in (one|a) day|per day|daily|can (a |the |my )?customers? pay|accept", q):
            return "limits"
        return "fallback"

    # ------------------------------------------------------------------ helpers
    def _v(self, clause_id: str, as_of: date):
        return self.engine.version(clause_id, as_of)

    def _pending_note(self, d: Draft, *versions) -> None:
        for v in versions:
            for item in v.pending:
                d.notes.append(f"Note: {CIRCULAR_NAME} item {item.clause_id} changes clause {v.clause_id} "
                               f"from {_d(item.effective_from)}; it is not yet in force on this date.")
                d.cite(cite(item))

    # ------------------------------------------------------------------ settlement
    def _h_settlement(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        q = p.text.lower()
        wants_same_day = bool(re.search(r"same day|same-day|instant|t\+0|today", q))
        methods = [p.method] if p.method else ["upi", "card"]
        v11, v12, v13 = self._v("1.1", as_of), self._v("1.2", as_of), self._v("1.3", as_of)

        if "card" in methods:
            card = v12.facts()["card"]
            if wants_same_day:
                d.say(f"No. Card transactions settle {card} (clause 1.2); the policy has no same-day option for cards.")
            else:
                d.say(f"Card transactions settle {card} (clause 1.2).")
            d.cite(*v12.citations())
            if v11.superseded and "A" in [c.clause_id for c in v11.applied]:
                d.say(f"The T+0 'Instant Settlement' option introduced by {CIRCULAR_NAME} item A applies to UPI only, not cards.")
                d.cite(*v11.citations())

        if "upi" in methods:
            f = v11.facts()
            if p.tier:
                d.say("Settlement timing does not depend on merchant size (small/large).")
            if "upi_instant" in f:
                instant, std = f["upi_instant"], f["upi_standard"]
                if p.instant_addon is True:
                    d.say(f"UPI: {instant} (same day, by 11:59 PM) because the merchant has an active Instant Settlement add-on ({CIRCULAR_NAME} item A, replacing clause 1.1).")
                elif p.instant_addon is False:
                    d.say(f"UPI: {std}, i.e. next working day ({CIRCULAR_NAME} item A, replacing clause 1.1); same-day settlement needs the Instant Settlement add-on.")
                else:
                    d.say(f"UPI: {std} (next working day) by default; {instant} (same day, by 11:59 PM) only if the merchant has an active "
                          f"\"Instant Settlement\" add-on ({CIRCULAR_NAME} item A, which replaced clause 1.1 from "
                          f"{_d(v11.applied[-1].effective_from)}).")
                if p.instant_addon is not False:
                    d.conflicts.append(
                        f"Master clause 1.1 (and FAQ Q1, 'Next working day') say T+1 for everyone; {CIRCULAR_NAME} item A "
                        f"replaced clause 1.1 from {_d(v11.applied[-1].effective_from)} and is later and explicitly amending, "
                        f"so it prevails: T+0 is available with the Instant Settlement add-on.")
                    d.cite(cite(self.engine.faq_entry("Q1")))
                d.cite(*v11.citations())
            else:
                std = f["upi_standard"]
                if wants_same_day:
                    d.say(f"No. On {_d(as_of)} UPI settlement is {std} (next working day) for all merchants (clause 1.1).")
                else:
                    d.say(f"UPI settles {std}: the next working day (clause 1.1).")
                d.cite(*v11.citations())
                self._pending_note(d, v11)
            if not wants_same_day or "upi_instant" not in f:
                nxt = add_working_days(as_of, 1)
                d.say(f"For a UPI payment received on {as_of.strftime('%a %d %b %Y')}, T+1 is {nxt.strftime('%a %d %b %Y')} "
                      f"counting only Sundays as non-working; if that is a bank holiday, settlement moves to the next working "
                      f"day (clause 1.3). The documents contain no bank-holiday calendar, so check one.")
                d.cite(cite(v13.base))

    # ------------------------------------------------------------------ fees
    def _fee_terms(self, tier: str, as_of: date, original: bool = False) -> tuple[Decimal, Optional[Decimal], Decimal]:
        rate_v = self._v("2.1" if tier == "small" else "2.2", as_of)
        cap_v, gst_v = self._v("2.3", as_of), self._v("2.4", as_of)
        rf = rate_v.original_facts() if original else rate_v.facts()
        cf = cap_v.original_facts() if original else cap_v.facts()
        cap = cf.get("cap_all") or cf.get(f"cap_{tier}")
        return to_decimal(rf["rate_pct"]), (to_decimal(cap) if cap else None), to_decimal(gst_v.facts()["gst_pct"])

    def _h_fee(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        v21, v22, v23, v24 = (self._v(c, as_of) for c in ("2.1", "2.2", "2.3", "2.4"))
        if p.method == "card":
            d.cannot_answer = True
            d.say("The documents only set MDR for UPI transactions (clauses 2.1–2.4). There is no card MDR rate in the "
                  "Master Document, the circular or the FAQ, so a card fee cannot be stated or calculated.")
            d.cite(cite(v21.base), cite(v22.base))
            return

        tiers = [p.tier] if p.tier else ["small", "large"]
        if not p.amounts:
            for tier in tiers:
                rate, cap, gst = self._fee_terms(tier, as_of)
                label = "up to ₹10 lakh monthly volume" if tier == "small" else "above ₹10 lakh monthly volume"
                d.say(f"UPI MDR for merchants {label}: {rate}% of the transaction value, capped at {fmt_inr(cap)} per transaction; "
                      f"GST at {gst}% is charged on the MDR on top of the cap.")
                o_rate, o_cap, _ = self._fee_terms(tier, as_of, original=True)
                if (o_rate, o_cap) != (rate, cap):
                    d.conflicts.append(f"Master Document terms for this tier ({o_rate}%, cap {fmt_inr(o_cap)}) were replaced by "
                                       f"{CIRCULAR_NAME} (effective 01 Aug 2026), which prevails as the later amending document.")
            d.cite(*(v21.citations() if "small" in tiers else []), *(v22.citations() if "large" in tiers else []),
                   *v23.citations(), cite(v24.base))
            self._faq_fee_note(d, faq_differs=True)
            self._pending_note(d, v21, v22, v23)
            return

        amount = p.amounts[0]
        if p.method is None:
            d.notes.append("(The documents define MDR only for UPI, so this assumes a UPI payment.)")
        if not self._fee_limit_check(p, amount, as_of, d):
            return  # amount can never be accepted; no fee to compute

        d.trace["calculations"] = []
        faq_differs = False
        for tier in tiers:
            rate, cap, gst = self._fee_terms(tier, as_of)
            fee = upi_fee(amount, rate, cap, gst)
            d.trace["calculations"].append({"tier": tier, **{k: str(v) for k, v in vars(fee).items()}})
            label = {"small": "Merchant with monthly volume up to ₹10 lakh", "large": "Merchant with monthly volume above ₹10 lakh"}[tier]
            d.say(f"{label}: MDR {fmt_inr(fee.mdr)} + GST {fmt_inr(fee.gst)} = {fmt_inr(fee.total)} total. ({fee.explain()}.)")

            o_rate, o_cap, _ = self._fee_terms(tier, as_of, original=True)
            original = upi_fee(amount, o_rate, o_cap, gst)
            if original.mdr != fee.mdr:
                changed = [c.clause_id for v in (v21 if tier == "small" else v22, v23) for c in v.applied]
                d.conflicts.append(
                    f"[{tier}] The Master Document alone ({o_rate}%, cap {fmt_inr(o_cap)}) would give MDR {fmt_inr(original.mdr)}; "
                    f"{CIRCULAR_NAME} item(s) {', '.join(changed)} replaced those clauses from 01 Aug 2026 and, as the later "
                    f"amending document, prevail → MDR {fmt_inr(fee.mdr)}.")
            faq_rate = to_decimal(FAQ_CLAIMS["Q2"][f"rate_{tier}"])
            faq_fee = upi_fee(amount, faq_rate, None, gst)  # FAQ claims "no upper limit"
            if faq_fee.mdr != fee.mdr:
                faq_differs = True
                d.conflicts.append(
                    f"[{tier}] FAQ Q2 (12 Mar 2026: {faq_rate}%, \"no upper limit\") would give MDR {fmt_inr(faq_fee.mdr)}; the FAQ is "
                    f"informal, predates the circular, and contradicts the cap in clause 2.3, so it is not followed.")
        if not p.tier:
            d.notes.append("The merchant's monthly volume was not given, so both tiers are shown.")
        d.cite(*(v21.citations() if "small" in tiers else []), *(v22.citations() if "large" in tiers else []),
               *v23.citations(), cite(v24.base))
        if faq_differs:
            d.cite(cite(self.engine.faq_entry("Q2")))
        self._pending_note(d, v21, v22, v23)

    def _faq_fee_note(self, d: Draft, faq_differs: bool) -> None:
        if faq_differs:
            d.conflicts.append("FAQ Q2 says there is no upper limit on the fee; that contradicts clause 2.3 (a cap has existed "
                               "since 01 Jan 2026), so the FAQ is not followed.")
            d.cite(cite(self.engine.faq_entry("Q2")))

    def _fee_limit_check(self, p: Parsed, amount: Decimal, as_of: date, d: Draft) -> bool:
        """Flags amounts above the UPI per-transaction limits. Returns False if the payment can never be accepted."""
        v41, v42, v43, v44 = (self._v(c, as_of) for c in ("4.1", "4.2", "4.3", "4.4"))
        per_txn = to_decimal(v41.facts()["per_txn"])
        enhanced = to_decimal(v42.facts()["enhanced_per_txn"])
        daily = to_decimal(v43.facts()["daily"])
        if amount <= per_txn:
            return True
        d.cite(cite(v41.base), cite(v42.base), cite(v44.base), *v43.citations())
        if amount > enhanced:
            d.say(f"A single UPI payment of {fmt_inr(amount)} cannot be accepted: it exceeds the standard per-transaction limit of "
                  f"{fmt_inr(per_txn)} (clause 4.1) and even the enhanced {fmt_inr(enhanced)} limit (clauses 4.2/4.4). No MDR arises.")
            return False
        d.say(f"Limit check first: {fmt_inr(amount)} is above the standard UPI per-transaction limit of {fmt_inr(per_txn)} (clause 4.1), "
              f"so an ordinary merchant cannot accept it as one UPI payment. Only \"Capital Markets\" or \"Insurance\" merchants that "
              f"completed enhanced KYC (Annexure C) may accept up to {fmt_inr(enhanced)} per transaction (clauses 4.2, 4.4) — and even "
              f"then the per-customer daily limit of {fmt_inr(daily)} (clause 4.3) would block a single payment this large; the "
              f"documents do not say which of 4.2 and 4.3 prevails. If the payment were processed, the charges would be:")
        return True

    # ------------------------------------------------------------------ refunds
    def _h_refund(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        v31, v32, v33 = self._v("3.1", as_of), self._v("3.2", as_of), self._v("3.3", as_of)
        window_days = int(v31.facts()["refund_window_days"])
        if p.days_elapsed is not None and p.days_elapsed > window_days:
            d.say(f"A refund {p.days_elapsed} days after the transaction is outside the {window_days}-day refund window "
                  f"(clause 3.1), so the merchant cannot initiate it under the policy.")
            d.cite(cite(v31.base))
            return

        reversal_hours = Decimal(v33.original_facts()["reversal_hours"])
        within = None  # is the refund within the 24-hour window?
        if p.hours_elapsed is not None:
            within = p.hours_elapsed <= reversal_hours
        elif p.days_elapsed == 0:
            within = True  # same calendar day is always under 24 hours
        d.trace["refund_within_24h"] = within
        assumed = f"(assuming the refund is initiated on {_d(as_of)})"

        if v33.deleted:
            item = next(c for c in v33.applied if c.target == "3.3")
            d.say(f"No. MDR on a refunded transaction is not returned {assumed}: clause 3.3 (24-hour reversal) was deleted by "
                  f"{CIRCULAR_NAME} item {item.clause_id} effective {_d(item.effective_from)}, and clause 3.2 now applies without exception.")
            d.cite(cite(v32.base), cite(item), cite(v33.base))
            if within is not False:
                d.conflicts.append(
                    f"Master clause 3.3 and FAQ Q3 say MDR is reversed for refunds within 24 hours; {CIRCULAR_NAME} item "
                    f"{item.clause_id} deleted clause 3.3 from {_d(item.effective_from)}. The circular is the later, explicitly "
                    f"amending document and is in force on {_d(as_of)}, so it prevails over the master and the stale FAQ.")
                d.cite(cite(self.engine.faq_entry("Q3")))
            return

        if within is True:
            d.say(f"Yes. A refund initiated within {reversal_hours} hours of the transaction gets the MDR reversed in full "
                  f"(clause 3.3, the exception to clause 3.2) {assumed}.")
        elif within is False:
            d.say(f"No. The refund is more than {reversal_hours} hours after the transaction, so clause 3.2 applies: MDR is not returned.")
        else:
            d.say(f"It depends on timing: if the refund is initiated within {reversal_hours} hours of the transaction the MDR is "
                  f"reversed in full (clause 3.3); otherwise it is not returned (clause 3.2).")
        d.cite(cite(v32.base), cite(v33.base))
        self._pending_note(d, v33)

    # ------------------------------------------------------------------ limits
    def _h_limits(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        v41, v42, v43, v44 = (self._v(c, as_of) for c in ("4.1", "4.2", "4.3", "4.4"))
        per_txn = to_decimal(v41.facts()["per_txn"])
        enhanced = to_decimal(v42.facts()["enhanced_per_txn"])
        daily = to_decimal(v43.facts()["daily"])
        bank_rule = "bank_limit_rule" in v43.facts()
        d.cite(cite(v41.base), *v43.citations())

        if not p.amounts:
            d.say(f"UPI limits: {fmt_inr(per_txn)} per transaction (4.1); \"Capital Markets\" and \"Insurance\" merchants with enhanced "
                  f"KYC may accept up to {fmt_inr(enhanced)} per transaction (4.2, 4.4); a customer account may pay at most "
                  f"{fmt_inr(daily)} per day across all UPI transactions (4.3)"
                  + (f", or the customer's own bank limit if lower ({CIRCULAR_NAME} item E)." if bank_rule else "."))
            d.cite(cite(v42.base), cite(v44.base))
            if bank_rule:
                d.conflicts.append(f"Master 4.3 sets a flat ₹1,00,000 daily limit; {CIRCULAR_NAME} item E (in force) adds the "
                                   f"'whichever is lower' bank-limit rule and prevails as the later amendment.")
            self._pending_note(d, v43)
            return

        amount = p.amounts[0]
        n = p.count or (len(p.amounts) if len(p.amounts) > 1 else 1)
        total = amount * n if len(p.amounts) == 1 else sum(p.amounts)
        enhanced_ok = p.category is not None and p.enhanced_kyc is True
        txn_limit = enhanced if enhanced_ok else per_txn
        eff_daily = min(daily, p.bank_limit) if (bank_rule and p.bank_limit is not None) else daily
        d.trace["limits"] = {"per_txn_limit": str(txn_limit), "daily_limit": str(eff_daily), "total": str(total), "count": n}

        if amount > per_txn and amount <= enhanced and p.category is not None and p.enhanced_kyc is not False:
            d.cannot_answer = True
            d.say(f"The documents conflict. Clause 4.2 lets a {p.category} merchant"
                  + (" with enhanced KYC" if enhanced_ok else " (only if enhanced KYC is completed, clause 4.4)")
                  + f" accept up to {fmt_inr(enhanced)} per transaction, but clause 4.3 caps each customer account at {fmt_inr(daily)} "
                  f"per day across all UPI transactions, which would block a single {fmt_inr(amount)} payment. Neither clause says "
                  f"which prevails, so this needs confirmation from the policy owner.")
            d.cite(cite(v42.base), cite(v44.base))
            return

        txn_ok = amount <= txn_limit
        daily_ok = total <= eff_daily
        times = f"{n} × {fmt_inr(amount)} = {fmt_inr(total)}" if n > 1 else fmt_inr(total)
        if txn_ok and daily_ok:
            d.say(f"Yes. Each payment is within the {fmt_inr(txn_limit)} per-transaction limit and the day's total ({times}) is "
                  f"within the {fmt_inr(eff_daily)} per-customer daily limit.")
        else:
            reasons = []
            if not txn_ok:
                reasons.append(f"{fmt_inr(amount)} exceeds the {fmt_inr(txn_limit)} per-transaction limit (clause 4.1"
                               + (", 4.2" if enhanced_ok else "") + ")")
            if not daily_ok:
                src = (f"the lower of ₹1,00,000 and the customer's bank limit ({CIRCULAR_NAME} item E)"
                       if eff_daily != daily else "clause 4.3" + (f" as amended by {CIRCULAR_NAME} item E" if bank_rule else ""))
                reasons.append(f"the day's total ({times}) exceeds the per-customer daily UPI limit of {fmt_inr(eff_daily)} ({src})")
            msg = "; and ".join(reasons)
            d.say("No. " + msg[0].upper() + msg[1:] + ".")
        if p.category and not enhanced_ok:
            d.cite(cite(v42.base), cite(v44.base))

        # Would the master's original 4.3 (no bank-limit rule) give a different outcome?
        master_daily_ok = total <= to_decimal(v43.original_facts()["daily"])
        if bank_rule and p.bank_limit is not None and master_daily_ok != daily_ok:
            d.conflicts.append(f"Master clause 4.3 alone (flat {fmt_inr(daily)}) would allow this; {CIRCULAR_NAME} item E amended "
                               f"4.3 from 01 Aug 2026 to use the customer's bank limit if lower, and prevails as the later amendment.")
        if not bank_rule and p.bank_limit is not None:
            d.notes.append("On this date the policy's daily limit does not refer to the customer's bank limit; the bank may still "
                           "apply its own limit, which is outside this policy.")
        if n > 1 and not daily_ok:
            d.notes.append("FAQ Q4 mentions only the per-transaction limit and omits the daily limit, so it is incomplete here.")
        self._pending_note(d, v43)

    # ------------------------------------------------------------------ account closure
    def _h_closure(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        v51, v52, v11, v13 = (self._v(c, as_of) for c in ("5.1", "5.2", "1.1", "1.3"))
        n = int(v52.facts()["release_working_days"])
        closed = p.event_date or find_date(p.text)
        d.say(f"Pending settlements are released within {n} working days of closure, after deducting any outstanding dues (clause 5.2).")
        d.cite(cite(v52.base))
        faq_days = int(re.match(r"\d+", FAQ_CLAIMS["Q5"]["release_days"]).group())
        if closed:
            by = add_working_days(closed, n)
            d.trace["closure"] = {"closed_on": closed.isoformat(), "release_by": by.isoformat()}
            d.say(f"Account closed on {closed.strftime('%a %d %b %Y')} → money due by {by.strftime('%a %d %b %Y')} at the latest, "
                  f"counting Sundays as non-working days. Working days also exclude bank holidays (clause 1.1 definition; clause 1.3), "
                  f"but the documents give no holiday calendar, so any bank holiday in that window pushes the date later.")
            d.cite(cite(v11.base), cite(v13.base))
        else:
            d.notes.append("Give the closure date to get a calculated date.")
        d.conflicts.append(f"FAQ Q5 says pending money is released 'within {faq_days} days'; clause 5.2 of the Master Document "
                           f"(authoritative, not amended by the circular) says {n} *working* days, which is longer, and prevails.")
        d.cite(cite(self.engine.faq_entry("Q5")))
        d.notes.append(f"Closure itself requires {v51.facts()['notice_days']} days' written notice (clause 5.1).")
        d.cite(cite(v51.base))

    # ------------------------------------------------------------------ FAQ audit
    def _h_faq_check(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        q = p.text.lower()
        topics = []
        if re.search(r"\bcap\b|mdr|fee|charge|pay on|upper limit|gst", q): topics.append("Q2")
        if "refund" in q: topics.append("Q3")
        if re.search(r"clos", q): topics.append("Q5")
        if re.search(r"settle|when will i get|receive", q) and "Q5" not in topics: topics.append("Q1")
        if re.search(r"\blimit\b|maximum", q) and "Q2" not in topics: topics.append("Q4")
        topics = topics or ["Q1", "Q2", "Q3", "Q4", "Q5"]
        wrong = False
        for t in topics:
            entry = self.engine.faq_entry(t)
            d.say(f"FAQ {t} (\"{entry.section}\") says: \"{entry.text}\".")
            d.cite(cite(entry))
            findings = getattr(self, f"_audit_{t.lower()}")(as_of, d)
            d.say(" ".join(findings))
            wrong |= any(f.startswith(("Wrong", "Stale", "Incomplete", "Inaccurate")) for f in findings)
        if wrong:
            d.conflicts.append(f"The FAQ (last updated 12 Mar 2026) is informal and predates {CIRCULAR_NAME}; where it disagrees, "
                               f"the Master Document as amended by the circular in force on {_d(as_of)} prevails.")

    def _audit_q1(self, as_of, d):
        v11, v12 = self._v("1.1", as_of), self._v("1.2", as_of)
        d.cite(*v11.citations(), cite(v12.base))
        out = []
        if "upi_instant" in v11.facts():
            out.append(f"Incomplete: UPI is T+1 by default but T+0 for merchants with the Instant Settlement add-on ({CIRCULAR_NAME} item A).")
        else:
            out.append("Correct on this date: UPI settles T+1 (clause 1.1).")
        out.append(f"Card: policy says {v12.facts()['card']} (clause 1.2), consistent with the FAQ.")
        return out

    def _audit_q2(self, as_of, d):
        v21, v22, v23, v24 = (self._v(c, as_of) for c in ("2.1", "2.2", "2.3", "2.4"))
        d.cite(*v21.citations(), cite(v22.base), *v23.citations(), cite(v24.base))
        out = []
        small, large = to_decimal(v21.facts()["rate_pct"]), to_decimal(v22.facts()["rate_pct"])
        if small != to_decimal(FAQ_CLAIMS["Q2"]["rate_small"]):
            out.append(f"Stale: the small-merchant rate is {small}% from 01 Aug 2026 ({CIRCULAR_NAME} item B), not {FAQ_CLAIMS['Q2']['rate_small']}%.")
        large_ok = large == to_decimal(FAQ_CLAIMS["Q2"]["rate_large"])
        out.append(f"The large-merchant rate of {large}% (clause 2.2) {'matches' if large_ok else 'does not match'} the FAQ.")
        f23 = v23.facts()
        if "cap_all" in f23:
            out.append(f"Wrong on the cap: MDR on any single UPI transaction cannot exceed {fmt_inr(to_decimal(f23['cap_all']))} (clause 2.3).")
            caps = {"small": to_decimal(f23["cap_all"]), "large": to_decimal(f23["cap_all"])}
        else:
            caps = {"small": to_decimal(f23["cap_small"]), "large": to_decimal(f23["cap_large"])}
            out.append(f"Wrong on the cap: there is an upper limit — {fmt_inr(caps['small'])} per transaction for merchants up to ₹10 lakh "
                       f"monthly volume and {fmt_inr(caps['large'])} above ₹10 lakh ({CIRCULAR_NAME} item C, replacing clause 2.3).")
        out.append(f"The FAQ was wrong even when written: clause 2.3 has capped MDR since {_d(self.engine.master_effective)}, before the FAQ's 12 Mar 2026 date.")
        # Above which amount the cap binds (computed, not guessed).
        thresholds = {t: caps[t] / (r / 100) for t, r in (("small", small), ("large", large))}
        out.append(f"So larger transactions do not keep costing more: MDR stops rising at {fmt_inr(thresholds['small'])} (small) and "
                   f"{fmt_inr(thresholds['large'])} (large). GST at {v24.facts()['gst_pct']}% is charged on the MDR on top of the cap (clause 2.4), which the FAQ omits.")
        return out

    def _audit_q3(self, as_of, d):
        v33 = self._v("3.3", as_of)
        d.cite(*v33.citations())
        if v33.deleted:
            return [f"Wrong on this date: clause 3.3 was deleted by {CIRCULAR_NAME} item D from 01 Sep 2026; MDR on refunds is no longer returned (clause 3.2)."]
        out = ["Correct on this date: clause 3.3 reverses MDR for refunds within 24 hours."]
        if v33.pending:
            out.append(f"But it becomes wrong from {_d(v33.pending[0].effective_from)}, when {CIRCULAR_NAME} item D deletes clause 3.3.")
            d.cite(*[cite(c) for c in v33.pending])
        return out

    def _audit_q4(self, as_of, d):
        v43 = self._v("4.3", as_of)
        d.cite(cite(self.engine.master["4.1"]), cite(self.engine.master["4.2"]), cite(self.engine.master["4.4"]), *v43.citations())
        return ["Per-transaction limits match clauses 4.1/4.2.",
                "Incomplete: the ₹2,00,000 limit applies only after enhanced KYC (clause 4.4), and the FAQ omits the per-customer daily limit (clause 4.3"
                + (f", amended by {CIRCULAR_NAME} item E)." if v43.superseded else ").")]

    def _audit_q5(self, as_of, d):
        d.cite(cite(self.engine.master["5.1"]), cite(self.engine.master["5.2"]))
        return ["Notice period matches clause 5.1 (30 days).",
                "Inaccurate: clause 5.2 says 10 *working* days, not 10 days, and money is released after deducting outstanding dues."]

    # ------------------------------------------------------------------ missing cross-reference
    def _h_missing_reference(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        d.cannot_answer = True
        d.say("Clause 4.4 refers to \"enhanced KYC (Annexure C)\", but Annexure C is not among the supplied documents, so its "
              "requirements cannot be stated.")
        d.cite(cite(self.engine.master["4.4"]))

    # ------------------------------------------------------------------ retrieval fallback
    def _h_fallback(self, p: Parsed, as_of: date, d: Draft, hits) -> None:
        for h in hits:
            c = h.clause
            if c.doc_kind != "master" or h.coverage < 0.6 or len(h.matched) < 2:
                continue
            v = self._v(c.clause_id, as_of)
            if v.deleted:
                continue
            in_force = v.in_force
            d.say(f"The closest rule in force on {_d(as_of)} is {in_force.document} §{in_force.clause_id}: \"{in_force.text}\"")
            d.cite(*v.citations())
            if v.superseded:
                d.conflicts.append(f"Master clause {c.clause_id} was amended by {CIRCULAR_NAME}; the amended text is used.")
            d.trace["fallback_match"] = {"clause": c.clause_id, "coverage": round(h.coverage, 2), "matched": h.matched}
            return
        d.cannot_answer = True
        d.say("The supplied documents do not contain a rule that answers this question, so I won't guess.")
