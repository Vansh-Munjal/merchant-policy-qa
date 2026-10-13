# AI usage

**Tool:** Claude Code (Anthropic, Claude Opus 5.5 model), run in VS Code, with the source documents and assignment screenshots as input.

**What it did:**
- Read the three source documents and listed the effective dates, superseded and deleted clauses, FAQ errors, and the 4.2/4.3 contradiction. I then checked these against the documents myself.
- Proposed the design (timeline + grounded fact table + rule-based handlers + Decimal calculator, no network) and wrote the first version of every file: `src/*`, `ask.py`, `evaluate.py`, `tests/`, `eval.json`, and these markdown files.
- Ran the unit tests, the eval and ad-hoc probe questions, and fixed the bugs they turned up:
  - an off-topic question ("interest on held settlements") was answered by the settlement handler, which led to the unknown-concept guard;
  - pending-amendment notes cited circular item B on large-merchant questions;
  - a capitalization bug lowercased citation names;
  - "charged" and "4000 rupees" weren't recognised.
- Wrote eval.json expected answers from the documents. It chose the three cases in WHERE_IT_BREAKS.md by probing the system with new phrasings.

**What it did not do:**
- There are no LLM calls at runtime. The assistant is deterministic Python with no API key.
- Expected answers in eval.json were not produced by the system under test. Note, though, that the eval set was written by the same AI that wrote the system, after seeing many of its answers (see README "Evaluation limits").

**My verification:**
- [ ] I checked each expected value in eval.json by hand against `ai-2-data/` (e.g. 0.50% × 4,000 = 20 < 25 cap; 18% × 20 = 3.60).
- [ ] I read every module and can explain the precedence, status and rounding decisions in DECISIONS.md.

