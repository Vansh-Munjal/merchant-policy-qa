"""Run the real assistant on eval.json and print a score table.

    python3 evaluate.py            # table + failures
    python3 evaluate.py --verbose  # also print every answer

A case passes only if all four checks pass:
  status    - exact match with expected_status
  answer    - every must_contain present, no must_not_contain present,
              and answer_starts_with matched if given (case-insensitive)
  citations - every expected (document, clause) is cited
  grounded  - every citation the system produced exists in the corpus and its
              quote is the verbatim clause text (no invented clauses)
Answer wording is otherwise not compared; see README "Evaluation limits".
"""
import argparse
import json
import sys
from pathlib import Path

from src.assistant import Assistant
from src.document_loader import load_corpus

ROOT = Path(__file__).resolve().parent


def check_case(case, result, corpus_index):
    ans = result.answer.lower()
    reasons = []

    status_ok = result.status.value == case["expected_status"]
    if not status_ok:
        reasons.append(f"status {result.status.value} != {case['expected_status']}")

    missing = [s for s in case.get("must_contain", []) if s.lower() not in ans]
    forbidden = [s for s in case.get("must_not_contain", []) if s.lower() in ans]
    start = case.get("answer_starts_with")
    start_ok = start is None or ans.startswith(start.lower())
    answer_ok = not missing and not forbidden and start_ok
    if missing:
        reasons.append(f"answer missing {missing}")
    if forbidden:
        reasons.append(f"answer contains trap text {forbidden}")
    if not start_ok:
        reasons.append(f"answer does not start with {start!r}")

    cited = {(c.document, c.clause) for c in result.citations}
    expected = {tuple(c) for c in case.get("expected_citations", [])}
    bad_expected = [c for c in expected if c not in corpus_index]
    if bad_expected:
        reasons.append(f"eval.json expects non-existent clause(s) {bad_expected}")
    missing_cites = sorted(expected - cited)
    cites_ok = not missing_cites and not bad_expected
    if missing_cites:
        reasons.append(f"missing citations {missing_cites}")

    ungrounded = [(c.document, c.clause) for c in result.citations
                  if corpus_index.get((c.document, c.clause)) != c.quote]
    grounded_ok = not ungrounded
    if ungrounded:
        reasons.append(f"ungrounded citations {ungrounded}")

    return {
        "id": case["id"], "question": case["question"], "as_of": case["as_of_date"],
        "adversarial": case.get("adversarial", False),
        "expected": case["expected_status"], "actual": result.status.value,
        "status_ok": status_ok, "answer_ok": answer_ok, "cites_ok": cites_ok, "grounded_ok": grounded_ok,
        "n_citations": len(result.citations), "n_ungrounded": len(ungrounded),
        "passed": status_ok and answer_ok and cites_ok and grounded_ok,
        "reasons": reasons, "answer": result.answer,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "eval.json"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    cases = json.loads(Path(args.eval).read_text(encoding="utf-8"))["cases"]
    corpus_index = {(c.document, c.clause_id): c.text for c in load_corpus()}
    assistant = Assistant()
    rows = [check_case(c, assistant.ask(c["question"], c["as_of_date"]), corpus_index) for c in cases]

    yn = lambda b: "✓" if b else "✗"
    header = f"{'ID':<4} {'As of':<10} {'Adv':<3} {'Question':<52} {'Expected':<17} {'Actual':<17} {'Ans':<3} {'Cite':<4} {'Grnd':<4} Result"
    print(header)
    print("-" * len(header))
    for r in rows:
        q = r["question"] if len(r["question"]) <= 52 else r["question"][:49] + "..."
        print(f"{r['id']:<4} {r['as_of']:<10} {'Y' if r['adversarial'] else '':<3} {q:<52} {r['expected']:<17} {r['actual']:<17} "
              f"{yn(r['answer_ok']):<3} {yn(r['cites_ok']):<4} {yn(r['grounded_ok']):<4} {'PASS' if r['passed'] else 'FAIL'}")
        if args.verbose:
            print(f"      → {r['answer']}")

    n = len(rows)
    pct = lambda k: f"{sum(r[k] for r in rows)}/{n} ({100 * sum(r[k] for r in rows) / n:.0f}%)"
    adv = [r for r in rows if r["adversarial"]]
    total_cites = sum(r["n_citations"] for r in rows)
    ungrounded = sum(r["n_ungrounded"] for r in rows)
    print()
    print(f"Overall pass         : {pct('passed')}")
    print(f"Status accuracy      : {pct('status_ok')}")
    print(f"Answer facts correct : {pct('answer_ok')}")
    print(f"Expected citations   : {pct('cites_ok')}")
    print(f"Citation grounding   : {total_cites - ungrounded}/{total_cites} citations verbatim in corpus")
    print(f"Adversarial pass     : {sum(r['passed'] for r in adv)}/{len(adv)}")

    failed = [r for r in rows if not r["passed"]]
    if failed:
        print("\nFailures:")
        for r in failed:
            print(f"  {r['id']}: " + "; ".join(r["reasons"]))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
