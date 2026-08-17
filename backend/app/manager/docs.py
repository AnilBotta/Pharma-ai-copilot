"""The system's own documentation, searchable as a tool.

WHY THIS EXISTS SEPARATELY FROM THE DATABASE

Two quite different questions arrive in the same sentence. "Which gate is
blocked" is a question about data, and reading a table answers it. "Why can't I
approve this myself" is a question about the *system* - about segregation of
duties, about what a trigger refuses and why - and no amount of reading the data
answers it.

Without this the agent would do what models do when asked a question they cannot
look up: invent a plausible-sounding rule. On a system whose entire purpose is
that nothing reports a state better than it is, an agent confidently explaining
a governance rule it made up would be the worst failure available.

NO EMBEDDINGS, DELIBERATELY

Keyword scoring over heading-split sections. The corpus is three documents in
one repository, written by us, using consistent vocabulary. A vector index would
add a build step, an embedding cost per query, and a second thing to keep in
sync, to search a corpus small enough to fit in memory.
"""

from __future__ import annotations

import functools
import pathlib
import re

#: Repository root, from backend/app/manager/docs.py.
_REPO = pathlib.Path(__file__).resolve().parents[3]

SOURCES = {
    "PDP_MODULE.md": "How the stage-gate module works: roles, gates, readiness.",
    # The agent's own rules. Without this it can describe the gate process in
    # detail and say nothing accurate about itself - which is the question a
    # first-time user is most likely to ask it.
    "MANAGER_AGENT.md": "What this agent may do, may not do, and why.",
    "KNOWN_LIMITATIONS.md": "What is not built, not verified, or deliberately absent.",
    "DEPLOYMENT.md": "How the system is deployed, scheduled and configured.",
    "CURRENT_SYSTEM_AUDIT.md": "The state of the system before the rebuild.",
}

_WORD = re.compile(r"[a-z0-9_]+")
#: Words too common in this corpus to discriminate between sections.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "is", "it", "in", "on", "for",
    "that", "this", "with", "as", "by", "be", "are", "not", "no", "why", "how",
    "what", "which", "can", "i", "you", "we", "does", "do", "if", "at", "from",
}


class Section:
    __slots__ = ("_terms", "body", "document", "heading")

    def __init__(self, document: str, heading: str, body: str) -> None:
        self.document = document
        self.heading = heading
        self.body = body
        self._terms = _tokenise(f"{heading} {heading} {body}")

    def score(self, query_terms: list[str]) -> int:
        # Heading terms count twice, by appearing twice in the source above.
        return sum(self._terms.get(term, 0) for term in query_terms)

    def as_dict(self) -> dict:
        return {
            "document": self.document,
            "heading": self.heading,
            "text": self.body[:4000],
        }


def _tokenise(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for word in _WORD.findall(text.lower()):
        if word in _STOP or len(word) < 3:
            continue
        counts[word] = counts.get(word, 0) + 1
    return counts


@functools.lru_cache(maxsize=1)
def _sections() -> list[Section]:
    """Split every source document at its markdown headings. Cached per process."""
    out: list[Section] = []
    for name in SOURCES:
        path = _REPO / "docs" / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")

        heading = name
        buffer: list[str] = []
        for line in text.splitlines():
            if line.startswith("#"):
                if buffer and any(ln.strip() for ln in buffer):
                    out.append(Section(name, heading, "\n".join(buffer).strip()))
                heading = line.lstrip("# ").strip() or name
                buffer = []
            else:
                buffer.append(line)
        if buffer and any(ln.strip() for ln in buffer):
            out.append(Section(name, heading, "\n".join(buffer).strip()))
    return out


def search(query: str, limit: int = 4) -> list[dict]:
    """Return the sections most relevant to ``query``.

    An empty list when nothing matches, which the agent is instructed to treat
    as "the documentation does not say" rather than as licence to guess.
    """
    terms = [t for t in _WORD.findall(query.lower()) if t not in _STOP and len(t) >= 3]
    if not terms:
        return []

    scored = [(s.score(terms), s) for s in _sections()]
    hits = sorted(
        ((score, s) for score, s in scored if score > 0),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [s.as_dict() for _score, s in hits[:limit]]
