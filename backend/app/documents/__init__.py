"""Uploaded document ingest: storage, extraction, chunking and embedding.

The pieces here turn a file the user uploaded into rows in `document_chunks`
that the research graph can retrieve and cite. Nothing in this package decides
what a document *means* - it only makes the text available, with enough
structure that a citation can name a page.
"""
