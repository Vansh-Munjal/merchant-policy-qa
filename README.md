# Merchant Policy Q&A Assistant

A small, offline question-answering assistant for merchant-support staff. It answers questions about settlement, MDR/GST, refunds, limits and account closure from the three documents in `ai-2-data/`. Every answer includes the date it applies to, real citations and a status.

```python
from src.assistant import Assistant
r = Assistant().ask("A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?", "2026-09-05")
r.status       # Status.CONFLICT_RESOLVED
r.answer       # "No. MDR on a refunded transaction is not returned ... clause 3.3 ... deleted by Circular MS/2026/17 item D ..."
r.resolution   # how the conflict was resolved (CONFLICT_RESOLVED only)
r.citations    # [Citation(document, clause, quote=<verbatim clause text>), ...]
r.diagnostics  # intent, parsed entities, retrieved passages, calculations
```

## Requirements and setup

- Python 3.10 or newer. Only the standard library is used, so there is nothing to install and no API key is needed.

```bash
git clone <repo-url> && cd ai_assignment
python3 --version          # 3.10+
```

## Running it

```bash
# Ask a question. --date sets as_of_date (YYYY-MM-DD).
python3 ask.py "When does a small merchant receive UPI money?" --date 2026-08-15

# Without --date: a date written in the question is used, otherwise 15 Aug 2026.
python3 ask.py "A large merchant (above Rs.10 lakh monthly) receives a Rs.4,000 UPI payment. What MDR and GST do they pay?"

# Full structured output, including diagnostics
python3 ask.py "I closed my account yesterday. When will I get my money?" --json

# Same question, two dates, two different correct answers
python3 ask.py "A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?" --date 2026-08-20
python3 ask.py "A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?" --date 2026-09-05

# Unit tests (16) and evaluation suite (25 cases)
python3 -m unittest discover -s tests -v
python3 evaluate.py            # add --verbose to see every answer
```

## How it works

```
question, as_of_date
   │
   ├─ question_parser.py   amounts (₹/Rs/lakh, Indian digit grouping), merchant tier, UPI/card,
   │                       hours elapsed, "yesterday", category, KYC, add-on
   ├─ retriever.py         keyword retrieval (diagnostics + fallback) and an "unknown concept" guard
   ├─ assistant.py         routes to a topic handler: settlement / fee / refund / limits / closure /
   │                       FAQ audit / missing cross-reference / retrieval fallback
   ├─ policy_engine.py     which text of each clause is in force on as_of_date (timeline), plus a
   │                       small fact table (rates, caps, limits) tied to each clause version
   └─ calculator.py        Decimal arithmetic for MDR, cap and GST, and working-day dates
```

| File | Responsibility |
|---|---|
| `src/document_loader.py` | Parses the markdown into `Clause` objects. Clause numbers, effective dates (including item D's own "Effective 01 September 2026"), and each circular item's operation (replaced/deleted/amended) and target clause are all read from the text. |
| `src/policy_engine.py` | `version(clause_id, as_of)` returns the master text, the circular item that replaced it, or *deleted*, along with amendments that are still pending. `FACTS` holds the numbers each clause version states, and a unit test asserts that each one appears word-for-word in its clause. |
| `src/calculator.py` | `upi_fee()`: MDR = rate × amount, capped, then 18% GST on the MDR outside the cap. All values are `Decimal`, rounded half-up to the paisa. `add_working_days()` skips Sundays. |
| `src/assistant.py` | The handlers. Each handler reads the clause versions in force, computes the answer, and then **recomputes it using the superseded master text and the FAQ's claims**. |
| `eval.json`, `evaluate.py` | 25 hand-written cases (15 adversarial) and a scorer that runs the real system. |

### Statuses and conflict resolution

- **ANSWERED**: the documents in force on `as_of_date` settle the question, and no other source would change the answer.
- **CONFLICT_RESOLVED**: a superseded master clause or the FAQ would give a *different* answer. `resolution` explains which source won and why. The precedence order is: circular item in force > master > FAQ (see DECISIONS.md). A conflict that wouldn't change the result is not reported. For example, the circular amended clause 4.3, but "can a customer pay ₹1,00,000 twice?" is "No" under both versions, so that answer is ANSWERED.
- **CANNOT_ANSWER**: the documents don't contain the rule (card MDR, chargeback penalties, Annexure C), the date is before any policy was in force, the documents contradict each other with no stated precedence (4.2 vs 4.3), or most of the question's terms appear nowhere in the documents.

### Citations

A citation is `(document, clause, quote)`. The quote is the verbatim clause text as loaded from disk, so anyone can check it. The FAQ has no clause numbers, so its entries are cited by position (`Q1`–`Q5`), and `Clause.section` holds the question heading. `evaluate.py` checks that every citation the system produces exists and that its quote matches the source exactly.

### Offline mode

There is no LLM, embedding model or network call anywhere (`grep -rE "requests|urllib|openai|anthropic" src` finds nothing). There are also no cached answers: everything is computed from the documents each time `Assistant()` is created.

## Evaluation results (current)

```
Overall pass 25/25 · Status 25/25 · Answer facts 25/25 · Expected citations 25/25
Citation grounding 92/92 verbatim · Adversarial 15/15
```

**What that score does and doesn't mean (evaluation limits):**
- I wrote the eval cases while building the system, after seeing how it answers. 100% on my own suite is weak evidence. `WHERE_IT_BREAKS.md` lists questions it gets wrong.
- Answer checking only looks for exact facts (amounts, dates, rule names, yes/no openings) and banned trap strings. Wording is not judged, so a correct number inside a misleading sentence would still pass.
- The expected citations are a minimum set. Extra citations are allowed as long as they are real.

## What works / what doesn't

**Works:**
- The eight assignment questions.
- Date-dependent answers across 01 Jan / 01 Aug / 01 Sep 2026.
- MDR/GST arithmetic, including caps, tier boundaries and limit checks.
- Detecting where the FAQ is stale or wrong.
- Refusing to answer about missing rules and missing annexes.
- Questions with relative dates ("yesterday").

**Doesn't, or only partly:**
- Question understanding is regex-based. Unusual phrasing ("ninety thousand rupees", "is Saturday a working day?") can get a generic or off-target answer (see WHERE_IT_BREAKS.md).
- The system is stateless. The assignment's Q3 says "Same merchant…", so it must be restated with the merchant's tier; otherwise both tiers are shown.
- There is no bank-holiday calendar, so calculated dates only skip Sundays and are flagged as earliest-case.
- One `as_of_date` is used for the whole question. The only exception: a refund question that mentions dates on both sides of the 01 Sep 2026 deletion of 3.3 gets CANNOT_ANSWER instead of a guess.
- The fact table only covers clauses that exist today. A new circular needs new `FACTS` rows (the grounding test will flag a mismatch, but not a missing row).
