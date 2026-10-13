"""Plain keyword retrieval over clauses. No embeddings, no network.

Used for two things: (1) diagnostics — every answer lists the passages that
matched the question; (2) the fallback for questions no topic handler covers,
where we only answer if a clause in force covers most of the question's words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Clause

STOPWORDS = set("""
a an the is are was were be been do does did can could will would should may might must
i me my we our you your they their it its this that these those of to in on at by for with
from as and or if then than what when where which who how much many any all per into about
there here have has had get gets got not no yes so
""".split())


def stem(tok: str) -> str:
    for suf in ("ing", "ed", "es", "s", "e"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    return tok


def tokens(text: str) -> list[str]:
    raw = re.findall(r"[a-z]+", text.lower())
    return [stem(t) for t in raw if t not in STOPWORDS and len(t) > 1]


@dataclass
class Hit:
    clause: Clause
    coverage: float      # share of the question's content words found in the clause
    matched: list[str]


class Retriever:
    def __init__(self, corpus: list[Clause]):
        self.corpus = corpus
        self.index = {id(c): set(tokens(c.text + " " + c.section)) for c in corpus}

    def search(self, question: str, k: int = 5) -> list[Hit]:
        q = list(dict.fromkeys(tokens(question)))
        if not q:
            return []
        hits = []
        for c in self.corpus:
            matched = [t for t in q if t in self.index[id(c)]]
            if matched:
                hits.append(Hit(c, len(matched) / len(q), matched))
        hits.sort(key=lambda h: (-h.coverage, h.clause.doc_kind != "master"))
        return hits[:k]
