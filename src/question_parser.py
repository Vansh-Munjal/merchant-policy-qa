"""Rule-based extraction of what a question is about and the numbers in it.

Deliberately conservative: when a value cannot be read reliably it stays None,
and the handler decides whether it can still answer (or must say CANNOT_ANSWER).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

LAKH = Decimal(100000)

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + _MONTHS + r")[a-z]*\.?,?\s+(\d{4})\b"
    r"|\b(\d{4})-(\d{2})-(\d{2})\b", re.I)

# "Rs.4,000" "Rs 1.5 lakh" "₹1,00,000" "INR 500" "4000 rupees"
_AMOUNT_RE = re.compile(
    r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?"
    r"|([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?\s*(?:rupees|inr)\b", re.I)

_WORD_COUNTS = {"once": 1, "twice": 2, "thrice": 3, "two": 2, "three": 3, "four": 4, "five": 5}


@dataclass
class Parsed:
    text: str
    amounts: list[Decimal] = field(default_factory=list)   # transaction amounts
    monthly_volume: Optional[Decimal] = None
    tier: Optional[str] = None            # "small" (<= 10 lakh) | "large" (> 10 lakh)
    method: Optional[str] = None          # "upi" | "card"
    count: Optional[int] = None           # "twice" -> 2
    hours_elapsed: Optional[Decimal] = None
    days_elapsed: Optional[int] = None
    event_date: Optional[date] = None     # e.g. closure date from "yesterday"
    category: Optional[str] = None        # "Insurance" | "Capital Markets"
    enhanced_kyc: Optional[bool] = None
    instant_addon: Optional[bool] = None
    asks_kyc_requirement: bool = False    # "do they need enhanced KYC?" is a question, not a fact
    bank_limit: Optional[Decimal] = None


def _to_amount(num: str, unit: Optional[str]) -> Decimal:
    value = Decimal(num.replace(",", ""))
    if unit and unit.lower() in ("lakh", "lac"):
        value *= LAKH
    elif unit and unit.lower() == "crore":
        value *= 100 * LAKH
    return value


def _match_to_date(m: re.Match) -> date:
    if m.group(4):
        return date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
    month = m.group(2)[:3].title()
    return datetime.strptime(f"{m.group(1)} {month} {m.group(3)}", "%d %b %Y").date()


def find_date(text: str) -> Optional[date]:
    m = _DATE_RE.search(text)
    return _match_to_date(m) if m else None


def find_all_dates(text: str) -> list[date]:
    return [_match_to_date(m) for m in _DATE_RE.finditer(text)]


def parse(question: str, as_of: date) -> Parsed:
    q = question.lower()
    p = Parsed(text=question)

    # --- Monthly volume / merchant tier (read and removed before amounts) ---------
    vol_pattern = re.compile(
        r"((?:up to|upto|below|under|less than|above|over|more than|exceeding|of|exactly)?\s*)"
        r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?\s*"
        r"(?:a month|per month|monthly|/month|(?:in )?monthly volume|monthly turnover)", re.I)
    vol_pattern_2 = re.compile(
        r"monthly (?:volume|turnover)(?: of| is)?\s*((?:up to|below|under|above|over|more than|exactly)?\s*)"
        r"(?:(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore)?|([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore))", re.I)
    scrubbed = question
    for pat in (vol_pattern, vol_pattern_2):
        m = pat.search(scrubbed)
        if m:
            qualifier = (m.group(1) or "").strip().lower()
            g = m.groups()
            vol = _to_amount(g[1], g[2]) if g[1] else _to_amount(g[3], g[4])
            p.monthly_volume = vol
            ten_lakh = 10 * LAKH
            if qualifier in ("above", "over", "more than", "exceeding"):
                p.tier = "large" if vol >= ten_lakh else None
            elif qualifier in ("up to", "upto", "below", "under", "less than"):
                p.tier = "small" if vol <= ten_lakh else None
            else:  # an exact volume: "up to ₹10 lakh" is inclusive (clause 2.1)
                p.tier = "large" if vol > ten_lakh else "small"
            scrubbed = scrubbed[:m.start()] + scrubbed[m.end():]
            break
    if p.tier is None:
        if re.search(r"\b(large|big)\b", q):
            p.tier = "large"
        elif re.search(r"\bsmall\b", q):
            p.tier = "small"

    # --- Bank-imposed limit ("my bank's limit is ₹50,000") ------------------------
    bm = re.search(r"bank[^.?]*?limit[^.?\d₹]*?(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac)?", scrubbed, re.I)
    if bm:
        p.bank_limit = _to_amount(bm.group(1), bm.group(2))
        scrubbed = scrubbed[:bm.start()] + scrubbed[bm.end():]

    # --- Transaction amounts --------------------------------------------------------
    p.amounts = [_to_amount(n1 or n2, u1 or u2) for n1, u1, n2, u2 in _AMOUNT_RE.findall(scrubbed)]

    # --- Payment method -------------------------------------------------------------
    if re.search(r"\b(card|credit card|debit card)s?\b", q):
        p.method = "card"
    elif "upi" in q:
        p.method = "upi"

    # --- Count ("twice", "3 payments") ---------------------------------------------
    for word, n in _WORD_COUNTS.items():
        if re.search(rf"\b{word}\b", q):
            p.count = n
            break
    if m := re.search(r"\b(\d+)\s+(?:payments|transactions|times)\b", q):
        p.count = int(m.group(1))

    # --- Elapsed time (refund timing) ----------------------------------------------
    if m := re.search(r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|minutes?|mins?)\b", q):
        val = Decimal(m.group(1))
        p.hours_elapsed = val / 60 if m.group(2).startswith("min") else val
    elif m := re.search(r"(\d+)\s*(days?|weeks?)\b(?:\s+(?:after|later|since))", q):
        n = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
        p.days_elapsed = n
        p.hours_elapsed = Decimal(n * 24)
    elif re.search(r"\bsame day\b", q) and "refund" in q:
        p.hours_elapsed = None  # same calendar day: < 24h but exact hours unknown
        p.days_elapsed = 0

    # --- Relative / explicit event dates -------------------------------------------
    if "yesterday" in q:
        p.event_date = as_of - timedelta(days=1)
    elif "today" in q:
        p.event_date = as_of

    # --- Merchant category / KYC / add-on --------------------------------------------
    if "insurance" in q:
        p.category = "Insurance"
    elif "capital market" in q:
        p.category = "Capital Markets"
    if re.search(r"(without|no|not|haven't|hasn't|incomplete)\s+(?:completed\s+)?(?:enhanced )?kyc", q):
        p.enhanced_kyc = False
    elif re.search(r"\b(need|needs|require|required|requires|must|have to|has to)\b[^.?]*enhanced kyc", q):
        p.asks_kyc_requirement = True
    elif "enhanced kyc" in q:
        p.enhanced_kyc = True
    if re.search(r"(without|no|not have|don't have)\s+(?:an?\s+|the\s+)?(?:active\s+)?instant settlement", q):
        p.instant_addon = False
    elif "instant settlement" in q:
        p.instant_addon = True
    return p
