"""Turning an uploaded file into per-page text.

Output is a list of pages rather than one string, because a citation has to be
able to say "p. 12". Losing page boundaries here cannot be recovered later, so
they are carried from the first step even though everything downstream works on
text.

NO OCR IS PERFORMED. A scanned PDF - an image of a page with no text layer -
extracts to nothing, and this module says so rather than returning empty pages.
That distinction matters more here than in most places: a document that appears
to have been read and contributed nothing is indistinguishable from one that was
read and had nothing relevant, and only one of those is a problem the user can
act on.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)

#: Below this many characters across the whole document, treat extraction as
#: having failed. A genuine text PDF clears it in a paragraph; a scanned one
#: yields only stray artefacts from page furniture.
MIN_USEFUL_CHARS = 40

SUPPORTED_MIME_TYPES = ("application/pdf", "text/plain", "text/markdown")


class ExtractionError(RuntimeError):
    """The file could not be turned into text, with a reason worth showing."""


class Page:
    """One page of extracted text.

    `number` is 1-based, matching what a reader sees on the page and what a
    citation must print. Text files are a single page numbered 1, which keeps
    every downstream consumer free of special cases.
    """

    __slots__ = ("number", "text")

    def __init__(self, number: int, text: str) -> None:
        self.number = number
        self.text = text

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Page(number={self.number}, chars={len(self.text)})"


def extract(content: bytes, mime_type: str, *, filename: str = "") -> list[Page]:
    """Extract text pages from an uploaded file.

    Raises ExtractionError with a message intended for the user, not a stack
    trace: this text ends up in `documents.error` and on screen.
    """
    if mime_type == "application/pdf":
        pages = _extract_pdf(content)
    elif mime_type in ("text/plain", "text/markdown"):
        pages = _extract_text(content)
    else:
        raise ExtractionError(
            f"{mime_type} is not a supported document type. "
            f"Supported: {', '.join(SUPPORTED_MIME_TYPES)}."
        )

    total = sum(len(p.text.strip()) for p in pages)
    if total < MIN_USEFUL_CHARS:
        raise ExtractionError(
            "No readable text could be extracted"
            + (f" from {filename}" if filename else "")
            + ". If this is a scanned document, it contains images of text "
            "rather than text, and this system does not perform OCR. Upload a "
            "text-based PDF or a text file instead."
        )

    return pages


def _extract_pdf(content: bytes) -> list[Page]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(content))
    except PyPdfError as exc:
        raise ExtractionError(f"This file is not a readable PDF: {exc}") from exc
    except Exception as exc:
        # Broad on purpose: pypdf raises a wide assortment on damaged files, and
        # every one of them means the same thing to the person who uploaded it.
        raise ExtractionError(f"This PDF could not be opened: {exc}") from exc

    if getattr(reader, "is_encrypted", False):
        # An empty-password decrypt covers PDFs encrypted only to restrict
        # printing, which is common for regulatory documents and perfectly
        # readable. A real password is refused rather than guessed at.
        try:
            if reader.decrypt("") == 0:
                raise ExtractionError(
                    "This PDF is password-protected. Remove the password and "
                    "upload it again."
                )
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(
                f"This PDF is encrypted and could not be opened: {exc}"
            ) from exc

    pages: list[Page] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            # One unreadable page does not condemn the document. Record the gap
            # and carry on; the total-length check still catches a file where
            # every page failed.
            logger.warning("Page %d could not be extracted: %s", index, exc)
            text = ""
        pages.append(Page(index, _normalise(text)))

    return pages


def _extract_text(content: bytes) -> list[Page]:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return [Page(1, _normalise(content.decode(encoding)))]
        except UnicodeDecodeError:
            continue
    raise ExtractionError(
        "This file's text encoding could not be determined. Save it as UTF-8 "
        "and upload it again."
    )


def _normalise(text: str) -> str:
    """Tidy extractor output without changing what it says.

    PDF extraction routinely emits a line break per visual line, which turns one
    sentence into six fragments and degrades both chunking and embedding. Runs
    of blank lines are meaningful (paragraph breaks) and are kept; single breaks
    inside a paragraph are not, and are joined.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "")  # soft hyphens, invisible but tokenised

    out: list[str] = []
    for block in text.split("\n\n"):
        lines = [line.strip() for line in block.split("\n")]
        joined = " ".join(line for line in lines if line)
        if joined:
            out.append(joined)
    return "\n\n".join(out)


__all__ = [
    "MIN_USEFUL_CHARS",
    "SUPPORTED_MIME_TYPES",
    "ExtractionError",
    "Page",
    "extract",
]
