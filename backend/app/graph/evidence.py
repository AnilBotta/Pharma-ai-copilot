"""Turning retrieved records into evidence entries.

This is where citation integrity is established. Markers are allocated here,
from records that were actually retrieved, *before* any synthesis node runs.
Synthesis is then given the marker list and nothing else to cite from, and the
reviewer rejects anything outside it.

Marker allocation is centralised so numbering is contiguous and unique within a
run even though literature and patent branches produce evidence concurrently.
"""

from __future__ import annotations

from app.graph.state import EvidenceEntry
from app.models.records import LiteratureRecord, PatentRecord

#: Characters of retrieved text carried into the prompt per source. Enough for
#: a full abstract; beyond that the context cost outweighs the benefit.
MAX_EVIDENCE_TEXT = 4000


def literature_to_evidence(
    record: LiteratureRecord,
    marker: str,
    *,
    agent: str = "literature_agent",
    evidence_category: str | None = None,
    relevance_score: float | None = None,
) -> EvidenceEntry:
    """Build an evidence entry from a retrieved publication.

    `access_level` comes from the record's own accounting of what was
    retrieved, never from an assumption. A paper known to be open access but
    whose body was not fetched is abstract_only, and the report must describe
    it that way.
    """
    identifier_type, identifier = _literature_identifier(record)
    text = record.full_text or record.abstract

    return EvidenceEntry(
        marker=marker,
        source_type="literature",
        provider=record.provider,
        title=record.title,
        authors=record.authors[:20],
        identifier_type=identifier_type,
        identifier=identifier,
        publication_date=(
            record.publication_date.isoformat() if record.publication_date else None
        ),
        url=record.best_url,
        retrieved_text=text[:MAX_EVIDENCE_TEXT] if text else None,
        access_level=record.access_level.value,
        evidence_category=evidence_category,
        relevance_score=relevance_score,
        retrieved_by_agent=agent,
    )


def patent_to_evidence(
    record: PatentRecord,
    marker: str,
    *,
    agent: str = "patent_agent",
    relevance_score: float | None = None,
) -> EvidenceEntry:
    """Build an evidence entry from a retrieved patent document."""
    return EvidenceEntry(
        marker=marker,
        source_type="patent",
        provider=record.provider,
        title=record.title or record.publication_number,
        authors=(record.applicants or record.inventors)[:20],
        identifier_type="patent_number",
        identifier=record.publication_number,
        publication_date=(
            record.publication_date.isoformat() if record.publication_date else None
        ),
        url=record.best_url,
        retrieved_text=(
            record.abstract[:MAX_EVIDENCE_TEXT] if record.abstract else None
        ),
        access_level=record.access_level.value,
        evidence_category=record.record_type.value,
        relevance_score=relevance_score,
        retrieved_by_agent=agent,
    )


def chunk_to_evidence(
    chunk: dict,
    marker: str,
    *,
    agent: str = "document_agent",
    relevance_score: float | None = None,
) -> EvidenceEntry:
    """Build an evidence entry from a passage of an uploaded document.

    THE TITLE CARRIES THE PAGE. `title` is what a reader sees beside a citation,
    so "Stability Report.pdf - p. 12" is the difference between being sent to a
    place and being sent to a file. `document_chunk_id` then resolves it to the
    exact passage.

    `access_level` is `full_text` and that is accurate rather than generous: the
    chunk's text was read in full. It says nothing about the document as a
    whole, which is the same distinction the literature agent draws when it
    records that it saw an abstract and not a paper.

    `provider` is the filename rather than a service name. There is no provider
    here - the user supplied this - and naming the file is what makes the
    origin obvious wherever evidence is listed.
    """
    page = chunk.get("page_number")
    filename = chunk.get("filename") or "Uploaded document"
    title = f"{filename} - p. {page}" if page else filename

    text = chunk.get("content") or ""

    return EvidenceEntry(
        marker=marker,
        source_type="internal_document",
        provider=filename,
        title=title,
        authors=[],
        identifier_type="document",
        # Human-readable and stable, so the same passage cited in two runs is
        # recognisably the same passage.
        identifier=f"{filename}#p{page}" if page else filename,
        publication_date=None,
        # No URL: the file lives in a private bucket and any link would be a
        # signed URL that expires. A dead link in a report is worse than none.
        url=None,
        retrieved_text=text[:MAX_EVIDENCE_TEXT],
        access_level="full_text",
        evidence_category="internal_document",
        relevance_score=relevance_score,
        retrieved_by_agent=agent,
        document_chunk_id=str(chunk["id"]),
    )


def _literature_identifier(record: LiteratureRecord) -> tuple[str | None, str | None]:
    """Pick the most resolvable identifier available."""
    if record.doi:
        return "doi", record.doi
    if record.pmid:
        return "pmid", record.pmid
    if record.pmcid:
        return "pmcid", record.pmcid
    if record.url:
        return "url", record.url
    return None, None


def allocate_markers(start_index: int, count: int) -> list[str]:
    """Allocate `count` sequential markers starting at E{start_index}."""
    return [f"E{start_index + offset}" for offset in range(count)]


def next_marker_index(existing: list[EvidenceEntry]) -> int:
    """Next free marker number given already-allocated evidence.

    Only correct when allocation is sequential. Concurrent branches must use
    :func:`marker_block_start` instead - see the note there.
    """
    highest = 0
    for entry in existing:
        try:
            highest = max(highest, int(entry["marker"][1:]))
        except (ValueError, KeyError, IndexError):
            continue
    return highest + 1


#: Branch order determines each branch's marker block. Adding a branch means
#: appending here, never inserting, so existing blocks keep their ranges.
_MARKER_BLOCKS = ("literature_agent", "patent_agent", "document_agent")


def marker_block_start(agent: str, max_results: int) -> int:
    """First marker number reserved for `agent`.

    The literature and patent agents run concurrently, so both observe the same
    pre-fan-out state. Deriving a start index from "markers allocated so far"
    therefore returns 1 in both branches, and the additive state reducer then
    concatenates two sets of E1, E2, ... Duplicate markers make a citation
    resolve ambiguously and violate the database's unique (run_id, marker)
    constraint.

    Each branch is given a disjoint, statically known block instead, so no
    coordination is needed and collisions are impossible by construction.
    Numbering is contiguous within a block; the gaps between blocks are
    cosmetic and harmless, since markers are identifiers rather than counts.
    """
    block_size = max(max_results, 1)
    try:
        index = _MARKER_BLOCKS.index(agent)
    except ValueError:
        index = len(_MARKER_BLOCKS)
    return index * block_size + 1


def format_evidence_for_prompt(entries: list[EvidenceEntry]) -> str:
    """Render evidence for inclusion in a prompt.

    Retrieved text is *not* fenced individually here; the caller wraps the
    whole block with wrap_untrusted, which is cheaper and equally safe since
    the entire block is untrusted.
    """
    if not entries:
        return "No evidence was retrieved."

    blocks = []
    for entry in entries:
        header = (
            f"[{entry['marker']}] {entry['title']}\n"
            f"  source: {entry['provider']} ({entry['source_type']})\n"
            f"  identifier: {entry.get('identifier') or 'none'}\n"
            f"  date: {entry.get('publication_date') or 'unknown'}\n"
            f"  access: {entry['access_level']}"
        )
        if entry.get("authors"):
            header += f"\n  authors: {', '.join(entry['authors'][:5])}"
        text = entry.get("retrieved_text")
        body = f"\n  text: {text}" if text else "\n  text: (none retrieved)"
        blocks.append(header + body)

    return "\n\n".join(blocks)
