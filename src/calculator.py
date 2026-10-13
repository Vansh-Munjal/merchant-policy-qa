"""Deterministic money and date arithmetic. No language model is involved.

Rounding: the documents do not specify a rounding rule. We round each charge to
the paisa (2 dp) with ROUND_HALF_UP, and compute GST on the *rounded* MDR,
which is how an invoice line would be built. This is an engineering choice,
recorded in DECISIONS.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

PAISA = Decimal("0.01")


def money(x: Decimal) -> Decimal:
    return x.quantize(PAISA, rounding=ROUND_HALF_UP)


def fmt_inr(x: Decimal) -> str:
    """Indian digit grouping: 150000 -> '₹1,50,000.00'."""
    x = money(x)
    whole, frac = f"{x:.2f}".split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}₹{whole}.{frac}"


@dataclass
class FeeBreakdown:
    amount: Decimal
    rate_pct: Decimal
    uncapped_mdr: Decimal
    cap: Optional[Decimal]
    mdr: Decimal
    gst_pct: Decimal
    gst: Decimal
    total: Decimal

    @property
    def cap_applied(self) -> bool:
        return self.cap is not None and self.uncapped_mdr > self.cap

    def explain(self) -> str:
        s = f"MDR = {self.rate_pct}% × {fmt_inr(self.amount)} = {fmt_inr(self.uncapped_mdr)}"
        if self.cap_applied:
            s += f", capped at {fmt_inr(self.cap)} → MDR {fmt_inr(self.mdr)}"
        elif self.cap is not None:
            s += f" (below the {fmt_inr(self.cap)} cap)"
        s += (f"; GST = {self.gst_pct}% × {fmt_inr(self.mdr)} = {fmt_inr(self.gst)}"
              f"; total charge = {fmt_inr(self.total)}")
        return s


def upi_fee(amount: Decimal, rate_pct: Decimal, cap: Optional[Decimal], gst_pct: Decimal) -> FeeBreakdown:
    """MDR = rate × amount, limited to cap; GST charged on MDR, outside the cap (clause 2.4)."""
    uncapped = money(amount * rate_pct / 100)
    mdr = min(uncapped, cap) if cap is not None else uncapped
    gst = money(mdr * gst_pct / 100)
    return FeeBreakdown(amount, rate_pct, uncapped, cap, mdr, gst_pct, gst, mdr + gst)


def is_working_day(d: date) -> bool:
    """Documents define working days as excluding Sundays and bank holidays, but
    supply no bank-holiday calendar, so only Sundays can be excluded here."""
    return d.weekday() != 6


def add_working_days(start: date, n: int) -> date:
    d, counted = start, 0
    while counted < n:
        d += timedelta(days=1)
        if is_working_day(d):
            counted += 1
    return d
