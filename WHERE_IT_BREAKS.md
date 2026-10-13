# Where it breaks

Three concrete cases, each reproduced against the current code (`python3 ask.py "<question>" --date <date>`).

## 1. A refund that crosses the 01 Sep 2026 deletion of clause 3.3

**Question (no `--date`):** "A customer paid at 11 PM on 31 August 2026 and the merchant refunded 2 hours later on 1 September 2026. Is the MDR returned?"

**What the system does:** It picks the *first* date in the question (31 Aug 2026) as as_of_date. It then answers **"Yes … reversed in full (clause 3.3)"** with status ANSWERED.

**Why that is wrong or unsafe:**
- The refund was initiated on 1 Sep, the day circular item D deleted 3.3. If the refund date governs, the answer is "No".
- The documents don't say whether the transaction date or the refund date decides which rule applies. The safe answer here is CANNOT_ANSWER, or at least a flagged conflict.
- The system models only one date per question, so it can't see that the two events fall on different sides of the effective date.

**Missing evidence:** Transition rules for item D, i.e. whether it covers transactions before 1 Sep that are refunded after it.

**Consequence:** Support tells a merchant the fee will come back when it won't, or the reverse. This creates disputes and manual reversals around the cut-over.

**Fix:** Pull out every event date in the question (transaction, refund). If any amendment's effective date falls between them, return CANNOT_ANSWER and explain both readings. Policy should also state the transition rule.

## 2. Calculated payout and settlement dates that ignore bank holidays (Q7)

**Question:** "I closed my account yesterday. When will I get my money?" (as_of 2026-08-15)

**What the system does:** Closure is 14 Aug 2026, and it adds 10 working days, skipping only Sundays, to get **Wed 26 Aug 2026**. The answer does warn that bank holidays push the date later.

**Why it shouldn't be trusted:**
- The documents say working days exclude "Sundays and bank holidays" but include no holiday calendar.
- The count treats Sat 15 Aug 2026 as a working day. In practice it is very likely a bank holiday, and Saturdays may be too. The real latest date is probably later than 26 Aug.
- The definition of working days also sits in clause 1.1, which circular A replaced without restating it, so even the definition is on shaky ground.

**Consequence:** A merchant is given a date that passes with no payout. That generates escalations and erodes trust.

**Fix:** Add the bank's official holiday calendar as a versioned data file and use it in `calculator.is_working_day`. Policy should restate the working-day definition after circular A.

## 3. Questions that hit a topic keyword but ask something else

**Questions (as_of 2026-08-15):**
- (a) "Is Saturday a working day for settlement?"
- (b) "Does an insurance merchant need enhanced KYC to accept Rs.1,50,000 in one UPI payment?"
- (c) "What MDR applies to a ninety thousand rupee UPI payment for a large merchant?"

**What the system does:**
- (a) Goes to the settlement handler and returns the generic T+0/T+1/T+2 summary (CONFLICT_RESOLVED). It never says that the documents exclude only Sundays and bank holidays, so a Saturday that isn't a bank holiday counts as a working day.
- (b) The parser sees the phrase "enhanced KYC" and assumes the merchant *has* it. The system returns the 4.2 vs 4.3 conflict (CANNOT_ANSWER). The direct answer, "yes, 4.4 requires enhanced KYC", is never given.
- (c) "ninety thousand" isn't parsed as a number, so it returns the rate and cap description with no fee calculation.

**Why:**
- Routing and entity extraction are hand-written regexes.
- Nothing checks whether the answer actually responds to what was asked; there is only a check on whether the question's words appear in the documents.
- None of these answers states anything false, but (a) and (b) leave the actual question unanswered while looking confident.

**Consequence:** An agent copies a fluent answer that doesn't address what the merchant asked.

**Fix:**
- Add a question-type classifier (yes/no vs amount vs date) and require the answer to match that type.
- Treat "need/require X" as a question about the requirement, not a statement that X is done.
- Add number-word parsing.
- Optionally, an LLM could do only the *entity extraction* step, with its output validated and the arithmetic and citations still deterministic.

## Also worth knowing
- **Statelessness:** The assignment's Q3 ("Same merchant, a Rs.1,50,000 payment") has no tier in it. The system shows both tiers instead of carrying over "large" from Q2.
- **Recall of the fact table:** If a new circular adds a clause, the handlers won't know about it until someone adds a `FACTS` row. The grounding test catches a wrong number but not a missing one.
