# Decisions and ambiguities

Each entry has two parts: **Source** is what the documents actually say, and **Choice** is what I decided as an engineering safeguard. Nothing under "Choice" is official policy.

## 1. Which document wins
- **Source:** The circular says it amends "the following clauses of the Master Document v1.0" and that "All other clauses remain unchanged" (item F). The FAQ is dated 12 Mar 2026, which is before the circular was issued (20 Jul 2026), and it claims no authority.
- **Choice:** Precedence is circular item in force on as_of_date > master > FAQ. The FAQ never overrides anything. It is used only to *detect* conflicts, so the system can say "the FAQ says X, but the rule is Y".

## 2. Effective dates
- **Source:** Master: "Effective 01 January 2026". Circular: "Issued 20 July 2026 — Effective 01 August 2026 unless stated otherwise". Item D ends with "(Effective 01 September 2026.)".
- **Choice:**
  - An item applies when `effective_from <= as_of_date`, so it is in force from the start of the effective date.
  - The issue date has no legal effect. Between 20 and 31 Jul 2026 the master still applies, and the answer notes the pending change.
  - The parenthetical inside D applies to item D only, not E or F. It is indented under D and comes before E.
  - Any date before 01 Jan 2026 gets CANNOT_ANSWER, because no policy in the corpus covers it.

## 3. Which date governs an event
- **Source:** Silent. The documents don't say whether the transaction date or the refund date decides which version of 3.3 applies.
- **Choice:** The whole question is evaluated on as_of_date, and the event is assumed to happen on that date. The refund answer states this assumption explicitly. If a refund question mentions dates on both sides of item D's effective date (e.g. sale 31 Aug, refund 1 Sep), the answer is CANNOT_ANSWER with both readings, because the documents give no transition rule (eval E25).
- If no as_of_date is passed, a date written in the question is used, otherwise 15 Aug 2026 (as the assignment says).

## 4. Superseded and deleted clauses
- **Source:**
  - A, B and C replace 1.1, 2.1 and 2.3. D deletes 3.3 and says "Clause 3.2 now applies without exception". E amends 4.3.
  - Master 2.2 says "subject to the cap in 2.3". This cross-reference follows the *current* 2.3, which is circular C from 01 Aug 2026.
- **Choice:**
  - A replaced clause is cited together with the circular item that replaced it, so a reviewer sees both.
  - A deleted clause is never used as a rule after its deletion date. It is cited only to explain the conflict.
  - Item D also affects 3.2, and that is recorded as `also_affects` (parsed from the text).

## 5. What counts as CONFLICT_RESOLVED
- **Choice:** Each handler recomputes its answer twice more: once with the superseded master text and once with the FAQ's claims. The status is CONFLICT_RESOLVED only if one of those **gives a different answer**. Otherwise it's ANSWERED, even if an amended clause was used. This is why Q6 (₹1,00,000 twice) is ANSWERED, and why a refund 30 hours after the sale is ANSWERED on both 20 Aug and 5 Sep.

## 6. When to say CANNOT_ANSWER
- The rule doesn't exist: card MDR, chargeback penalties, interest.
- A referenced document wasn't supplied: Annexure C (4.4).
- The as_of_date is before the master took effect.
- **Internal contradiction with no stated precedence: 4.2 vs 4.3.** 4.2 allows ₹2,00,000 per transaction for Capital Markets/Insurance merchants with enhanced KYC. 4.3 caps every customer at ₹1,00,000 per day across all UPI payments. A single ₹1,50,000 payment satisfies 4.2 and breaks 4.3. One could argue that the specific rule overrides the general one, but the documents don't say so, so the system abstains instead of picking.
- **Guard:** if under half of the question's content words appear anywhere in the documents (plus a small list of everyday question words), the system abstains. The aim is to stop questions like "interest on held settlements" from reaching the settlement handler just because they contain the word "settle".

## 7. Arithmetic and rounding
- **Source:** Rates (0.30%, 0.25%, 0.50%), caps (₹15, ₹25), and "GST at 18% is charged on the MDR amount and is not part of the MDR cap" (2.4). No rounding rule is given.
- **Choice:**
  - Everything uses `Decimal`; no floats.
  - MDR = rate × amount, rounded half-up to 2 dp, then capped. GST = 18% × the rounded, capped MDR, rounded to 2 dp.
  - Rounding per line item is an assumption. It only makes a difference at fractions of a paisa.
- The numbers come from `FACTS`, and `tests/test_policy_engine.py` checks that every value appears word-for-word in the clause it cites.

## 8. Tier boundary
- **Source:** "up to ₹10 lakh" (2.1/B) and "above ₹10 lakh" (2.2/C).
- **Choice:** Exactly ₹10 lakh is the small tier, because "up to" is inclusive (eval E12). If the tier isn't given, both tiers are calculated and shown, rather than guessing one.

## 9. Transactions above the per-transaction limit (Q3)
- **Source:** 4.1 sets a ₹1,00,000 per-transaction limit, and the question asks about ₹1,50,000.
- **Choice:**
  - The answer starts by saying an ordinary merchant can't accept this payment, and it raises the 4.2/4.4 exception and the 4.3 contradiction.
  - It then gives the fee *if* the payment were processed (capped at ₹25 + ₹4.50 GST = ₹29.50), because that is what the question asks.
  - Status is CONFLICT_RESOLVED because the cap changed (master ₹15 → circular ₹25) and the FAQ's "no cap" would give ₹750.
  - Above ₹2,00,000 there is no case where the payment can be accepted, so no fee is calculated.

## 10. Working days and dates
- **Source:**
  - Only master 1.1 defines working days: "exclude Sundays and bank holidays".
  - Circular A replaced 1.1 without restating that definition.
  - 1.3 still refers to bank holidays.
  - No document includes a holiday calendar.
- **Choice:**
  - Keep the 1.1 definition, since it's the only one in the documents. 1.3 shows bank holidays still matter.
  - Calculated dates skip Sundays only, and every such answer warns that bank holidays can make the date later.
  - I don't bring in a real-world holiday list, because that would be facts from outside the documents.

## 11. Closure (Q7)
- **Source:** 5.2 says "within 10 working days of closure, after deducting outstanding dues". FAQ Q5 says "within 10 days".
- **Choice:**
  - "Yesterday" means as_of_date − 1, so 14 Aug 2026 by default. Ten working days after that is 26 Aug 2026 (Sundays skipped).
  - The FAQ's "10 days" would give 24 Aug, so the answer is CONFLICT_RESOLVED in favour of 5.2.
  - The answer also mentions the 30-day notice requirement in 5.1.

## 12. Settlement (Q1, Q8)
- **Source:** A gives T+0 only with an active Instant Settlement add-on and T+1 otherwise, for UPI only. Card settlement is T+2 (1.2, never amended).
- **Choice:**
  - "Small merchant" doesn't affect settlement, and the answer says so.
  - If add-on status is unknown, both branches are shown.
  - Card same-day is "No", with a note that the T+0 option is UPI-only.

## 13. Problems I found in the documents but couldn't resolve
- 4.2 vs 4.3 (see §6).
- Whether the cut-off for 3.3's deletion is the transaction date or the refund date (see §3).
- Whether "T+2" for cards means working days. The FAQ says "two working days" and the master doesn't say. The system states "T+2" and doesn't calculate a card settlement date.
- Annexure C is referenced but not supplied.
- The working-day definition was dropped when 1.1 was replaced (see §10).
- The FAQ was already wrong about the cap when it was published (the cap dates from 01 Jan 2026), so it isn't only out of date.
