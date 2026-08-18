"""Splitting extracted pages into embeddable chunks.

Two properties matter and everything here serves them:

  * EVERY CHUNK KNOWS ITS PAGE. That is what makes a citation say "p. 12"
    instead of naming a file and leaving the reader to search it. A chunk that
    spans a page boundary is attributed to the page it *starts* on, because
    that is where a reader sent to it should begin.

  * CHUNKS OVERLAP. A sentence split across a boundary is retrievable from
    neither half without it. The cost is some duplicated text; the cost of not
    doing it is a fact present in the document that no query can reach.

Splitting is on paragraph boundaries where possible and sentence boundaries
otherwise, so a chunk is a unit of meaning rather than a fixed slice of
characters.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.documents.extract import Page

#: Target chunk size in characters. Roughly 250-300 tokens for English prose,
#: which sits well within the embedding model's window and keeps a retrieved
#: passage small enough to read in a citation panel.
TARGET_CHARS = 1200

#: Carried from the end of one chunk into the start of the next.
OVERLAP_CHARS = 200

#: Below this a chunk is not worth embedding or citing - a page number, a
#: running header, the fragment left at the end of a section.
MIN_CHARS = 80

#: A heading: short, and not ending in sentence punctuation. Used to label
#: chunks so a citation can name the section as well as the page.
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?([A-Z][^.!?]{2,80})$")

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

#: Characters per token, for the stored `token_count`. An estimate, and labelled
#: as one - the real count is the tokeniser's business and is not worth a
#: dependency here, since nothing downstream makes a decision on it.
_CHARS_PER_TOKEN = 4


def chunk_pages(pages: list[Page]) -> list[dict]:
    """Turn extracted pages into chunk rows ready for insertion.

    Returns dicts matching the `document_chunks` columns, with `chunk_index`
    contiguous across the whole document so ordering is stable and the unique
    (document_id, chunk_index) constraint holds.

    Headings are recognised while walking units, before anything is joined
    together. Detecting them afterwards cannot work: by then a heading has been
    concatenated onto the paragraph beneath it and is no longer a short line on
    its own, which is the only thing that distinguishes it from prose.
    """
    chunks: list[dict] = []
    heading: str | None = None

    for page in pages:
        current = ""

        for unit in _units(page.text):
            candidate = _heading_of(unit)
            if candidate is not None:
                # A heading introduces what comes after it. Close whatever
                # preceded it under the old heading, then label the rest.
                if len(current.strip()) >= MIN_CHARS:
                    chunks.append(_row(len(chunks), current, page.number, heading))
                current = ""
                heading = candidate
                continue

            if current and len(current) + len(unit) + 1 > TARGET_CHARS:
                chunks.append(_row(len(chunks), current, page.number, heading))
                current = f"{_tail(current)} {unit}"
            else:
                current = f"{current} {unit}".strip() if current else unit

        tail = current.strip()
        if len(tail) >= MIN_CHARS:
            chunks.append(_row(len(chunks), tail, page.number, heading))
        elif tail and chunks and chunks[-1]["page_number"] == page.number:
            # A short remainder joins the chunk before it rather than becoming a
            # fragment too small to mean anything - but only within the same
            # page, or the merged chunk's page number would be a lie.
            merged = f"{chunks[-1]['content']} {tail}"
            chunks[-1]["content"] = merged
            chunks[-1]["token_count"] = max(1, len(merged) // _CHARS_PER_TOKEN)

    return chunks


def _row(index: int, content: str, page_number: int, heading: str | None) -> dict:
    text = content.strip()
    return {
        "chunk_index": index,
        "content": text,
        "page_number": page_number,
        "section_heading": heading,
        "token_count": max(1, len(text) // _CHARS_PER_TOKEN),
    }


def _units(text: str) -> list[str]:
    """Paragraphs, further split into sentences when a paragraph is oversized."""
    units: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= TARGET_CHARS:
            units.append(paragraph)
            continue
        for sentence in _SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) <= TARGET_CHARS:
                units.append(sentence)
            else:
                # A single sentence longer than the target - a table row, or a
                # run of text with no punctuation. Hard-split it; there is no
                # meaningful boundary to find.
                units.extend(
                    sentence[i : i + TARGET_CHARS]
                    for i in range(0, len(sentence), TARGET_CHARS)
                )
    return units


def _tail(text: str) -> str:
    """The overlap carried into the next chunk, cut at a word boundary."""
    if len(text) <= OVERLAP_CHARS:
        return text.strip()
    tail = text[-OVERLAP_CHARS:]
    space = tail.find(" ")
    return tail[space + 1 :].strip() if space != -1 else tail.strip()


def _heading_of(unit: str) -> str | None:
    """Whether this unit is *entirely* a heading.

    Requiring the whole unit rules out a paragraph that merely begins with a
    capitalised clause. It matters because a unit identified as a heading is not
    emitted as a chunk - if the test were looser, body text would be silently
    dropped from the searchable corpus rather than merely mislabelled.
    """
    text = unit.strip()
    if not text or len(text) > 90 or "\n" in text:
        return None
    match = _HEADING.match(text)
    return match.group(1).strip() if match else None


__all__ = [
    "MIN_CHARS",
    "OVERLAP_CHARS",
    "TARGET_CHARS",
    "chunk_pages",
]
