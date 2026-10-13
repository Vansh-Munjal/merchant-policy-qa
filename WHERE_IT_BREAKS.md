# Where it breaks

Three concrete cases, each reproduced against the current code (`python3 ask.py "<question>" --date <date>`).

## 1. The assignment's literal Q3: "Same merchant, a Rs.1,50,000 payment. What do they pay?" (as_of 2026-08-15)

**What the system does:** It flags the ₹1,00,000 per-transaction limit correctly, but then shows the fee for *both* tiers: small (₹15 cap) and large (₹25 cap). The question refers back to the large merchant from Q2.

**Why:** `ask()` is stateless by design. Each call sees only its own question, so "same merchant" carries no information.

**Missing evidence:** The merchant's monthly volume, which only exists in the previous question.

**Consequence:** Mild, because both figures are correct for their tier, but an agent has to pick the right line. In a chat setting, a wrong pick would quote ₹15 + ₹2.70 instead of ₹25 + ₹4.50.

**Fix:** Add an optional `context` argument (previous parsed entities) that fills in only the missing entities, and record in diagnostics where each value came from. In eval.json, Q3 is written out in full for now (E03).

## 2. Calculated payout and settlement dates that ignore bank holidays (Q7)

**Question:** "I closed my account yesterday. When will I get my money?" (as_of 2026-08-15)

**What the system does:** Closure is 14 Aug 2026, and it adds 10 working days, skipping only Sundays, to get **Wed 26 Aug 2026**. The answer does warn that bank holidays push the date later.

**Why it shouldn't be trusted:**
- The documents say working days exclude "Sundays and bank holidays" but include no holiday calendar.
- The count treats Sat 15 Aug 2026 as a working day. In practice it is very likely a bank holiday, and Saturdays may be too. The real latest date is probably later than 26 Aug.
- The definition of working days also sits in clause 1.1, which circular A replaced without restating it, so even the definition is on shaky ground.

**Consequence:** A merchant is given a date that passes with no payout. That generates escalations and erodes trust.

**Fix:** Add the bank's official holiday calendar as a versioned data file and use it in `calculator.is_working_day`. Policy should restate the working-day definition after circular A.

## 3. "Does an insurance merchant need enhanced KYC to accept Rs.1,50,000 in one UPI payment?" (as_of 2026-08-15)

**What the system does:** The parser sees the phrase "enhanced KYC" and records that the merchant *has* it. The system then returns the 4.2 vs 4.3 contradiction with CANNOT_ANSWER. It never gives the direct answer: "yes, clause 4.4 makes enhanced KYC a precondition for the ₹2,00,000 limit".

**Why:** Entity extraction is regex-based and can't tell asking about a requirement apart from stating it has been met. A similar parsing gap: "a ninety thousand rupee payment" isn't read as a number, so no fee is calculated.

**Consequence:** Here the system abstains, which is safe, but it misses an answer that is clearly in the documents. In other phrasings the same mistake could wrongly assume KYC is complete and report a higher limit than applies.

**Fix:** Treat "need/require/must X" as a question about X instead of a fact about the merchant. Add number-word parsing. Optionally, use an LLM only for entity extraction, validate its output against a schema, and keep the arithmetic and citations deterministic.

## Fixed since the first version
- **"Is Saturday a working day for settlement?"** This used to get the generic settlement summary. A working-day handler now answers it directly from clauses 1.1 and 1.3 (eval E26).
- **Refund straddling 01 Sep 2026** ("paid 11 PM on 31 August 2026, refunded 2 hours later on 1 September 2026"). The system used to answer "Yes" based on the first date only. Now, when the question's dates fall on both sides of item D's effective date, it returns CANNOT_ANSWER and explains both readings, because the documents give no transition rule. Covered by eval case E25.

## Also worth knowing
- **Recall of the fact table:** If a new circular adds a clause, the handlers won't know about it until someone adds a `FACTS` row. The grounding test catches a wrong number but not a missing one.
