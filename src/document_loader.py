"""Parse the three markdown sources into Clause objects.

Nothing here is hard-coded per document: clause numbers, effective dates and
amendment operations are read from the text with a few regexes. If a file is
missing, loading fails loudly instead of silently answering from less data.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from .models import Clause

DATA_DIR = Path(__file__).resolve().parent.parent / "ai-2-data"

MASTER_FILE = "policy_master_v1.md"
CIRCULAR_FILE = "circular_2026_08_amendment.md"
FAQ_FILE = "merchant_faq_2026-03.md"

_DATE = r"(\d{1,2} [A-Za-z]+ \d{4})"


def parse_doc_date(text: str) -> date:
    """'01 August 2026' / '1 Aug 2026' -> date."""
    text = text.strip()
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognised document date: {text!r}")


def load_master(path: Path) -> list[Clause]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Effective " + _DATE, text)
    if not m:
        raise ValueError(f"{path.name}: no effective date found")
    effective = parse_doc_date(m.group(1))

    clauses, section = [], ""
    for line in text.splitlines():
        if h := re.match(r"^##\s+\d+\.\s+(.*)", line):
            section = h.group(1).strip()
        elif c := re.match(r"^(\d+\.\d+)\s+(.*)", line):
            clauses.append(Clause(path.name, "master", c.group(1), c.group(2).strip(),
                                  section=section, effective_from=effective))
    return clauses


def load_circular(path: Path) -> list[Clause]:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"Effective " + _DATE, text)
    if not m:
        raise ValueError(f"{path.name}: no default effective date found")
    default_effective = parse_doc_date(m.group(1))

    # Lettered items ("A. ...") with indented continuation lines.
    items: list[tuple[str, str]] = []
    for line in text.splitlines():
        if it := re.match(r"^([A-Z])\.\s+(.*)", line):
            items.append((it.group(1), it.group(2).strip()))
        elif items and line.startswith((" ", "\t")) and line.strip():
            letter, body = items[-1]
            items[-1] = (letter, body + " " + line.strip())

    clauses = []
    for letter, body in items:
        # A per-item "(Effective <date>.)" overrides the circular-wide date.
        override = re.search(r"\(Effective " + _DATE + r"\.?\)", body)
        effective = parse_doc_date(override.group(1)) if override else default_effective
        op = re.search(r"Clause (\d+\.\d+) is (replaced|deleted|amended)", body)
        mentioned = re.findall(r"Clause (\d+\.\d+)", body)
        target = op.group(1) if op else None
        clauses.append(Clause(
            path.name, "circular", letter, body, section="Circular MS/2026/17",
            effective_from=effective,
            op=op.group(2) if op else None,
            target=target,
            also_affects=tuple(c for c in mentioned if c != target),
        ))
    return clauses


def load_faq(path: Path) -> list[Clause]:
    """The FAQ has no clause numbers, so entries are identified by position (Q1..Qn)
    plus the question heading. We never invent a numbering beyond that."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"last updated " + _DATE, text)
    updated = parse_doc_date(m.group(1)) if m else None
    clauses = []
    for i, (q, a) in enumerate(re.findall(r"\*\*(.+?)\*\*\s*\n(.+?)(?=\n\s*\n|\n\*\*|\Z)", text, re.S), 1):
        clauses.append(Clause(path.name, "faq", f"Q{i}", a.strip(), section=q.strip(),
                              effective_from=updated))
    return clauses


def load_corpus(data_dir: Path = DATA_DIR) -> list[Clause]:
    paths = {name: data_dir / name for name in (MASTER_FILE, CIRCULAR_FILE, FAQ_FILE)}
    missing = [n for n, p in paths.items() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing source documents in {data_dir}: {missing}")
    return (load_master(paths[MASTER_FILE]) + load_circular(paths[CIRCULAR_FILE])
            + load_faq(paths[FAQ_FILE]))
