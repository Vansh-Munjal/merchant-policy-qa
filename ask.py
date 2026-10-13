"""Command-line entry point.

    python3 ask.py "When does a small merchant receive UPI money?" --date 2026-08-15
    python3 ask.py "..." --json        # full structured output incl. diagnostics
"""
import argparse
import json
import sys

from src.assistant import Assistant


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask the merchant policy assistant a question.")
    ap.add_argument("question")
    ap.add_argument("--date", help="as_of_date, YYYY-MM-DD (default: date in the question, else 2026-08-15)")
    ap.add_argument("--json", action="store_true", help="print the full structured result")
    args = ap.parse_args()

    result = Assistant().ask(args.question, args.date)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0
    print(f"as_of_date : {result.as_of_date}")
    print(f"status     : {result.status.value}")
    print(f"answer     : {result.answer}")
    if result.resolution:
        print(f"resolution : {result.resolution}")
    print("citations  :")
    for c in result.citations:
        print(f"  - {c.short()}: {c.quote}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
