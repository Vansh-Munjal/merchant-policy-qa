"""Plain data types shared across the assistant."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Optional


class Status(str, Enum):
    ANSWERED = "ANSWERED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    CANNOT_ANSWER = "CANNOT_ANSWER"


# Document authority. Lower number = more authoritative when two sources disagree
# about the same clause on the same date (see DECISIONS.md).
AUTHORITY = {"circular": 0, "master": 1, "faq": 2}


@dataclass(frozen=True)
class Clause:
    """One citable unit of a source document, exactly as written."""
    document: str          # file name, e.g. "policy_master_v1.md"
    doc_kind: str          # "master" | "circular" | "faq"
    clause_id: str         # "2.3" (master), "C" (circular), "Q2" (FAQ position)
    text: str              # verbatim clause text
    section: str = ""      # heading the clause sits under (master) or the FAQ question
    effective_from: Optional[date] = None
    # Circular items only: what they do to the master.
    op: Optional[str] = None             # "replaced" | "deleted" | "amended"
    target: Optional[str] = None         # master clause id the op applies to
    also_affects: tuple = ()             # other master clauses named in the item


@dataclass(frozen=True)
class Citation:
    document: str
    clause: str
    quote: str  # verbatim excerpt, so a reviewer (and evaluate.py) can check grounding

    def short(self) -> str:
        return f"{self.document} §{self.clause}"


@dataclass
class Answer:
    answer: str
    citations: list[Citation]
    status: Status
    resolution: Optional[str] = None      # how a conflict was resolved (CONFLICT_RESOLVED only)
    as_of_date: Optional[date] = None
    diagnostics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        d["as_of_date"] = self.as_of_date.isoformat() if self.as_of_date else None
        return d
