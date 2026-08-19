"""Extraction, chunking and the guards around ingest.

The theme running through these is that a document must never *appear* to have
been read when it was not. An empty result and a failed one look identical from
the outside, and only one of them is something the user can act on.
"""

from __future__ import annotations

import io

import pytest

from app.documents.chunk import OVERLAP_CHARS, TARGET_CHARS, chunk_pages
from app.documents.extract import ExtractionError, Page, extract


def _pdf(pages: list[str]) -> bytes:
    """A real PDF with a text layer, built with the library that reads it."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in pages:
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestExtractionRefusesToPretend:
    def test_a_pdf_with_no_text_layer_fails_and_says_why(self) -> None:
        """A scan is the common case, and the one worth naming.

        Blank pages extract to nothing, exactly as an image-only scan does.
        Returning empty pages here would leave the document `ready` with no
        chunks - searchable, findable, and containing nothing, with no
        indication that anything went wrong.
        """
        with pytest.raises(ExtractionError) as exc:
            extract(_pdf(["", ""]), "application/pdf", filename="scan.pdf")

        message = str(exc.value)
        assert "scan.pdf" in message
        # It must name OCR. Without that, the reader has no idea what to do
        # differently, and "no readable text" reads like a bug in the system.
        assert "OCR" in message

    def test_an_unsupported_type_is_refused_by_name(self) -> None:
        with pytest.raises(ExtractionError) as exc:
            extract(b"...", "application/msword")
        assert "application/msword" in str(exc.value)

    def test_a_corrupt_pdf_fails_rather_than_raising_something_opaque(self) -> None:
        with pytest.raises(ExtractionError):
            extract(b"this is not a pdf at all", "application/pdf")

    def test_plain_text_is_one_page(self) -> None:
        pages = extract(b"Depot formulations release drug over weeks. " * 4, "text/plain")
        assert [p.number for p in pages] == [1]

    def test_utf16_is_decoded_rather_than_refused(self) -> None:
        """Windows tooling emits UTF-16 text files routinely.

        Decoding it as UTF-8 fails, and as latin-1 "succeeds" into mojibake -
        text that embeds without error and retrieves nothing. The fallback order
        has to try UTF-16 before latin-1, and this is what pins that.
        """
        pages = extract(
            "Depot formulations release drug over weeks.".encode("utf-16"),
            "text/plain",
        )
        assert "Depot formulations" in pages[0].text


class TestChunkingKeepsThePage:
    """Page numbers are the whole point: a citation says "filename, p. 12"."""

    def test_every_chunk_carries_the_page_it_started_on(self) -> None:
        pages = [
            Page(1, "Alpha. " * 400),
            Page(2, "Beta. " * 400),
            Page(3, "Gamma. " * 400),
        ]
        chunks = chunk_pages(pages)

        assert chunks, "long pages must produce chunks"
        for chunk in chunks:
            assert chunk["page_number"] in (1, 2, 3)

        # And each page is actually represented - a chunker that silently drops
        # pages would still satisfy the assertion above.
        assert {c["page_number"] for c in chunks} == {1, 2, 3}

    def test_content_is_attributed_to_the_right_page(self) -> None:
        chunks = chunk_pages([Page(1, "Alpha. " * 300), Page(2, "Beta. " * 300)])
        for chunk in chunks:
            expected = "Alpha" if chunk["page_number"] == 1 else "Beta"
            assert expected in chunk["content"]

    def test_indexes_are_contiguous_across_the_document(self) -> None:
        """The unique (document_id, chunk_index) constraint depends on this."""
        chunks = chunk_pages([Page(n, "Sentence here. " * 200) for n in range(1, 5)])
        assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))

    def test_chunks_overlap_so_a_split_sentence_stays_findable(self) -> None:
        text = " ".join(f"Sentence number {n} about depot formulation." for n in range(200))
        chunks = chunk_pages([Page(1, text)])
        assert len(chunks) > 1

        # The tail of one chunk should reappear at the head of the next.
        first_words = chunks[0]["content"].split()[-8:]
        assert any(w in chunks[1]["content"] for w in first_words)

    def test_fragments_below_the_minimum_are_not_emitted(self) -> None:
        assert chunk_pages([Page(1, "Short.")]) == []

    def test_a_sentence_longer_than_the_target_is_still_split(self) -> None:
        """A table row or an unpunctuated run has no boundary to find."""
        chunks = chunk_pages([Page(1, "x" * (TARGET_CHARS * 3))])
        assert len(chunks) >= 3
        # A chunk is at most one target-sized unit plus the overlap carried in
        # from the chunk before it. Anything larger means the splitter gave up.
        ceiling = TARGET_CHARS + OVERLAP_CHARS + 1
        assert all(len(c["content"]) <= ceiling for c in chunks)

    def test_a_heading_labels_the_chunks_that_follow_it(self) -> None:
        body = "The dissolution profile was measured over 28 days. " * 40
        chunks = chunk_pages([Page(4, f"3.2 Dissolution Testing\n\n{body}")])
        assert chunks
        assert any(c["section_heading"] for c in chunks)


class TestTheEmbeddingDimensionGuard:
    """The column is vector(1536). A mismatch must be caught where it is caused.

    Changing OPENAI_EMBEDDING_MODEL to a 3072-dimension model otherwise fails on
    every insert, with a driver-level message about vector dimensions and no
    mention of the setting responsible.
    """

    async def test_a_wrong_sized_vector_fails_the_document_with_the_reason(self) -> None:
        from app.documents.ingest import _embed_phase

        class WrongSizeModels:
            async def embed(self, texts):
                from app.llm.provider import Usage

                return [[0.0] * 3072 for _ in texts], Usage(model="text-embedding-3-large")

        class Repo:
            async def next_unembedded(self, document_id, limit):
                return [{"id": "c1", "chunk_index": 0, "content": "text"}]

            async def save_embeddings(self, vectors):
                raise AssertionError("nothing should be written at the wrong size")

        with pytest.raises(ExtractionError) as exc:
            await _embed_phase(
                Repo(), WrongSizeModels(), "doc", deadline=_far_future(),
                user_id="u", record_usage=None,
            )

        message = str(exc.value)
        assert "3072" in message and "1536" in message
        # Naming the variable is the difference between a five-second fix and
        # an investigation.
        assert "OPENAI_EMBEDDING_MODEL" in message

    async def test_a_short_batch_is_refused_rather_than_mismatched(self) -> None:
        """Zipping vectors to chunks positionally is only safe if lengths match.

        Two vectors for three chunks would otherwise attach the second chunk's
        vector to the third, and every later search would return confidently
        wrong passages.
        """
        from app.documents.ingest import _embed_phase
        from app.llm.provider import LLMError, Usage

        class ShortModels:
            async def embed(self, texts):
                return [[0.0] * 1536], Usage(model="text-embedding-3-small")

        class Repo:
            async def next_unembedded(self, document_id, limit):
                return [
                    {"id": "c1", "chunk_index": 0, "content": "a"},
                    {"id": "c2", "chunk_index": 1, "content": "b"},
                ]

            async def save_embeddings(self, vectors):
                raise AssertionError("a short batch must not be written")

        with pytest.raises(LLMError):
            await _embed_phase(
                Repo(), ShortModels(), "doc", deadline=_far_future(),
                user_id="u", record_usage=None,
            )


class TestEvidenceMappingCarriesThePage:
    """A citation to an uploaded document must reach a page, not just a file."""

    def _chunk(self, **overrides):
        return {
            "id": "11111111-1111-1111-1111-111111111111",
            "document_id": "22222222-2222-2222-2222-222222222222",
            "content": "The depot released drug over 28 days in vitro.",
            "page_number": 12,
            "section_heading": "Dissolution",
            "filename": "Stability Report.pdf",
            "similarity": 0.71,
            **overrides,
        }

    def test_the_title_names_the_document_and_the_page(self) -> None:
        from app.graph.evidence import chunk_to_evidence

        entry = chunk_to_evidence(self._chunk(), "E101")
        assert entry["title"] == "Stability Report.pdf - p. 12"

    def test_the_chunk_id_is_carried_so_the_citation_resolves(self) -> None:
        """Without this the foreign key stays null and the page is unreachable."""
        from app.graph.evidence import chunk_to_evidence

        entry = chunk_to_evidence(self._chunk(), "E101")
        assert entry["document_chunk_id"] == "11111111-1111-1111-1111-111111111111"

    def test_it_is_typed_as_internal_so_the_report_can_keep_it_separate(self) -> None:
        from app.graph.evidence import chunk_to_evidence

        entry = chunk_to_evidence(self._chunk(), "E101")
        assert entry["source_type"] == "internal_document"
        # No URL: the file is in a private bucket and any link would expire.
        # A dead link in a report is worse than no link.
        assert entry["url"] is None

    def test_a_document_without_pages_still_produces_a_usable_title(self) -> None:
        from app.graph.evidence import chunk_to_evidence

        entry = chunk_to_evidence(self._chunk(page_number=None), "E101")
        assert entry["title"] == "Stability Report.pdf"

    def test_markers_cannot_collide_with_the_other_branches(self) -> None:
        """The branches run concurrently and observe the same pre-fan-out state.

        Deriving a start index from "markers so far" returns 1 in every branch,
        and the additive reducer then concatenates several sets of E1. A
        duplicate marker resolves ambiguously and violates the unique
        (run_id, marker) constraint.
        """
        from app.graph.evidence import marker_block_start

        starts = {
            agent: marker_block_start(agent, 50)
            for agent in ("literature_agent", "patent_agent", "document_agent")
        }
        assert len(set(starts.values())) == 3


class TestRetrievalDoesNotPadWithIrrelevance:
    async def test_passages_below_the_similarity_floor_are_dropped(self) -> None:
        """Nearest is not the same as relevant.

        Vector search always returns its k nearest neighbours. On a small
        corpus the nearest passage to "what is the toxicology profile" may be
        about invoicing, and handing it to the model as a retrieved passage
        invites a claim built on it.
        """
        from app.documents.retrieval import MIN_SIMILARITY, DocumentRetriever
        from app.llm.provider import Usage

        class Models:
            async def embed(self, texts):
                return [[0.0] * 1536], Usage(model="text-embedding-3-small")

        class Repo:
            async def search_chunks(self, **kwargs):
                return [
                    {"id": "a", "content": "relevant", "similarity": MIN_SIMILARITY + 0.4},
                    {"id": "b", "content": "unrelated", "similarity": MIN_SIMILARITY - 0.1},
                ]

        retriever = DocumentRetriever(
            Repo(), Models(), project_id="p", user_id="u", document_count=1
        )
        results = await retriever.search("toxicology profile")

        assert [r["id"] for r in results] == ["a"]

    async def test_a_project_with_no_ready_documents_yields_no_retriever(self) -> None:
        """None, not an empty retriever, so the node can stay silent.

        A report that announces "no internal documents were searched" on every
        run is noise, and noise is what teaches people to stop reading.
        """
        from app.documents.retrieval import DocumentRetriever

        class Repo:
            async def ready_documents(self, project_id, user_id):
                return []

        assert (
            await DocumentRetriever.for_run(
                Repo(), object(), project_id="p", user_id="u"
            )
            is None
        )


class TestConfirmingAnUploadStorageCannotMeasure:
    """Storage gzips text, and a gzipped response has no content-length.

    Two of the three accepted document types are text, so this was not an edge
    case - it was most non-PDF uploads. The failure surfaced as a check
    constraint violation on `size_bytes > 0`, raised from the driver, naming a
    column rather than the upload it belonged to. A PDF is already compressed
    and is not gzipped again, which is why testing with one hid it completely.
    """

    async def test_an_unmeasurable_size_is_refused_not_written(self) -> None:
        from app.documents.repository import DocumentRepository
        from app.documents.storage import SIZE_UNKNOWN

        class Pool:
            def acquire(self):
                raise AssertionError("nothing should reach the database")

        with pytest.raises(ValueError) as exc:
            await DocumentRepository(Pool()).mark_uploaded("u", "d", SIZE_UNKNOWN)

        # It has to say what to do instead, or the next reader reaches for the
        # constraint rather than the caller.
        assert "declared size" in str(exc.value)

    async def test_a_real_size_is_written(self) -> None:
        from app.documents.repository import DocumentRepository

        class Conn:
            async def fetchrow(self, *args):
                assert args[-1] == 1913
                return {"id": "d", "size_bytes": 1913}

        class Acquire:
            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *exc):
                return False

        class Pool:
            def acquire(self):
                return Acquire()

        row = await DocumentRepository(Pool()).mark_uploaded("u", "d", 1913)
        assert row["size_bytes"] == 1913


class TestTheReportAccountsForInternalSources:
    """Found by reading a real report, not by a test.

    A run drawing on uploaded documents printed, in its Limitations section:

        This report is based on 14 retrieved sources (4 publications,
        4 patent families).

    Six sources unaccounted for, in the one section a careful reader turns to
    first. The danger is not the arithmetic - it is that a reader who does not
    reconcile it concludes the report rests on eight published sources, when
    nearly half its citations are internal material nobody outside the
    organisation has reviewed.
    """

    def _entry(self, marker: str, source_type: str, **overrides) -> dict:
        return {
            "marker": marker,
            "source_type": source_type,
            "provider": "Stability Report.pdf" if source_type == "internal_document" else "pubmed",
            "title": "A title",
            "authors": [],
            "identifier_type": "document" if source_type == "internal_document" else "doi",
            "identifier": "x",
            "publication_date": None,
            "url": None,
            "retrieved_text": "text",
            "access_level": "full_text",
            "evidence_category": None,
            "relevance_score": None,
            "retrieved_by_agent": "a",
            **overrides,
        }

    def test_the_breakdown_adds_up_to_the_total(self) -> None:
        from app.graph.nodes.synthesis import _build_limitations

        evidence = [
            self._entry("E1", "literature"),
            self._entry("E2", "patent"),
            self._entry("E21", "internal_document"),
            self._entry("E22", "internal_document"),
        ]
        body = _build_limitations({"evidence_records": evidence}, 0).body_markdown

        assert "4 retrieved sources" in body
        assert "1 publications" in body
        assert "1 patent families" in body
        assert "2 passages from uploaded internal documents" in body

    def test_it_says_the_internal_sources_are_unreviewed(self) -> None:
        from app.graph.nodes.synthesis import _build_limitations

        body = _build_limitations(
            {"evidence_records": [self._entry("E21", "internal_document")]}, 0
        ).body_markdown
        assert "not been peer-reviewed" in body

    def test_a_run_with_no_documents_says_nothing_about_them(self) -> None:
        """A caution printed on every run is one people stop reading."""
        from app.graph.nodes.synthesis import _build_limitations

        body = _build_limitations(
            {"evidence_records": [self._entry("E1", "literature")]}, 0
        ).body_markdown
        assert "internal document" not in body.lower()

    def test_a_reference_to_an_uploaded_document_is_labelled_as_one(self) -> None:
        """`full text` is true of the passage and reads as a retrieval result.

        Beside a peer-reviewed paper obtained in full, it borrows exactly the
        credibility the source has not got - and the provider is the filename,
        which the title already printed.
        """
        from app.graph.nodes.synthesis import _build_references

        body = _build_references([self._entry("E21", "internal_document")]).body_markdown

        assert "internal document, not peer-reviewed" in body
        assert "full text" not in body

    def test_an_external_reference_still_reports_what_was_read(self) -> None:
        from app.graph.nodes.synthesis import _build_references

        body = _build_references(
            [self._entry("E1", "literature", access_level="abstract_only")]
        ).body_markdown
        assert "abstract only" in body


def _far_future() -> float:
    import time

    return time.monotonic() + 300
