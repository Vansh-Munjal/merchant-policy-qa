"""Unit tests. Run: python3 -m unittest discover -s tests -v"""
import unittest
from datetime import date
from decimal import Decimal

from src.assistant import Assistant
from src.calculator import add_working_days, fmt_inr, upi_fee
from src.document_loader import load_corpus
from src.models import Status
from src.policy_engine import FACTS, FAQ_CLAIMS, PolicyEngine
from src.question_parser import parse

CORPUS = load_corpus()
ENGINE = PolicyEngine(CORPUS)
ASSISTANT = Assistant()


class TestGrounding(unittest.TestCase):
    """Every hand-encoded number must appear verbatim in the clause it is attributed to."""

    def test_facts_are_literal_substrings_of_their_clause(self):
        by_key = {(c.doc_kind, c.clause_id): c for c in CORPUS}
        for key, facts in FACTS.items():
            self.assertIn(key, by_key, f"fact table refers to non-existent clause {key}")
            for name, literal in facts.items():
                self.assertIn(literal, by_key[key].text, f"{key}.{name}={literal!r} not in clause text")

    def test_faq_claims_are_literal(self):
        for entry, claims in FAQ_CLAIMS.items():
            for name, literal in claims.items():
                self.assertIn(literal, ENGINE.faq_entry(entry).text, f"FAQ {entry}.{name}")


class TestTimeline(unittest.TestCase):
    def test_circular_dates_parsed_from_text(self):
        items = {c.clause_id: c for c in CORPUS if c.doc_kind == "circular"}
        self.assertEqual(items["B"].effective_from, date(2026, 8, 1))
        self.assertEqual(items["D"].effective_from, date(2026, 9, 1))  # per-item override
        self.assertEqual((items["D"].op, items["D"].target), ("deleted", "3.3"))

    def test_clause_versions_by_date(self):
        self.assertEqual(ENGINE.version("2.3", date(2026, 7, 31)).in_force.doc_kind, "master")
        self.assertEqual(ENGINE.version("2.3", date(2026, 8, 1)).in_force.clause_id, "C")
        self.assertFalse(ENGINE.version("3.3", date(2026, 8, 31)).deleted)
        self.assertTrue(ENGINE.version("3.3", date(2026, 9, 1)).deleted)
        self.assertEqual([c.clause_id for c in ENGINE.version("3.3", date(2026, 8, 20)).pending], ["D"])
        self.assertFalse(ENGINE.version("1.2", date(2026, 12, 1)).superseded)


class TestCalculator(unittest.TestCase):
    def test_cap_and_gst(self):
        f = upi_fee(Decimal("150000"), Decimal("0.50"), Decimal("25"), Decimal("18"))
        self.assertEqual((f.mdr, f.gst, f.total), (Decimal("25.00"), Decimal("4.50"), Decimal("29.50")))
        self.assertTrue(f.cap_applied)

    def test_rounding_half_up_to_paisa(self):
        f = upi_fee(Decimal("333"), Decimal("0.25"), Decimal("15"), Decimal("18"))  # 0.8325 -> 0.83
        self.assertEqual((f.mdr, f.gst), (Decimal("0.83"), Decimal("0.15")))

    def test_working_days_skip_sundays(self):
        self.assertEqual(add_working_days(date(2026, 8, 14), 10), date(2026, 8, 26))
        self.assertEqual(add_working_days(date(2026, 8, 15), 1), date(2026, 8, 17))

    def test_indian_format(self):
        self.assertEqual(fmt_inr(Decimal("150000")), "₹1,50,000.00")


class TestParser(unittest.TestCase):
    def test_volume_not_mistaken_for_amount(self):
        p = parse("A large merchant (above Rs.10 lakh monthly) receives a Rs.4,000 UPI payment.", date(2026, 8, 15))
        self.assertEqual((p.tier, p.amounts), ("large", [Decimal("4000")]))

    def test_exactly_ten_lakh_is_small(self):
        p = parse("Monthly volume of exactly Rs.10 lakh, Rs.8,000 payment", date(2026, 8, 15))
        self.assertEqual(p.tier, "small")

    def test_yesterday_relative_to_as_of(self):
        self.assertEqual(parse("I closed my account yesterday", date(2026, 8, 15)).event_date, date(2026, 8, 14))


class TestAssistant(unittest.TestCase):
    def test_refund_answer_depends_on_date(self):
        q = "A merchant refunds a customer 3 hours after the sale. Do they get the MDR back?"
        before, after = ASSISTANT.ask(q, "2026-08-20"), ASSISTANT.ask(q, "2026-09-05")
        self.assertTrue(before.answer.startswith("Yes"))
        self.assertEqual(before.status, Status.ANSWERED)
        self.assertTrue(after.answer.startswith("No"))
        self.assertEqual(after.status, Status.CONFLICT_RESOLVED)

    def test_unknown_topic_abstains(self):
        self.assertEqual(ASSISTANT.ask("What interest do I earn on held settlements?").status, Status.CANNOT_ANSWER)

    def test_before_policy_effective(self):
        self.assertEqual(ASSISTANT.ask("What is the UPI MDR?", "2025-12-31").status, Status.CANNOT_ANSWER)

    def test_citations_are_real(self):
        known = {(c.document, c.clause_id): c.text for c in CORPUS}
        for q in ["When does a small merchant receive UPI money?",
                  "What does the FAQ say about the MDR cap, and is the FAQ right?",
                  "I closed my account yesterday. When will I get my money?"]:
            for c in ASSISTANT.ask(q).citations:
                self.assertEqual(known[(c.document, c.clause)], c.quote)

    def test_date_in_question_used_when_no_argument(self):
        r = ASSISTANT.ask("On 5 September 2026 a merchant refunds a sale after 3 hours. Is MDR returned?")
        self.assertEqual(r.as_of_date, date(2026, 9, 5))


if __name__ == "__main__":
    unittest.main()
