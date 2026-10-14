"""Bounded text/PDF extraction with offsets into extracted page text. No OCR or network."""

import hashlib
import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from .source_models import SourceDocument, SourcePage, SourcePassage

MAX_BYTES = 5_000_000
MAX_PAGES = 50
MAX_TEXT_CHARS = 100_000
MAX_PASSAGES = 200
MAX_PASSAGE_CHARS = 1600
MAX_PAGE_STREAM_BYTES = 2_000_000


class SourceError(ValueError):
    """Safe extraction error; never includes local paths or document contents."""


def read_source(path: str | Path) -> SourceDocument:
    path = Path(path)
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    return ingest_source(data, path.name)


def ingest_source(data: bytes, filename: str) -> SourceDocument:
    if not data or len(data) > MAX_BYTES:
        raise SourceError("Provide a nonempty source under 5 MB.")
    suffix = Path(filename).suffix.lower()
    kinds = {".txt": "text", ".md": "markdown", ".pdf": "pdf"}
    if suffix not in kinds:
        raise SourceError("Supported sources are UTF-8 text, Markdown and text-based PDF.")
    kind = kinds[suffix]
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            raise SourceError("The file is not a PDF.")
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise SourceError("Encrypted PDFs are not supported. Provide an unlocked source.")
            if not 0 < len(reader.pages) <= MAX_PAGES:
                raise SourceError("Use a PDF excerpt of at most 50 pages.")
            pages = []
            total = 0
            for index, page in enumerate(reader.pages, 1):
                content = page.get_contents()
                if content is not None and len(content.get_data()) > MAX_PAGE_STREAM_BYTES:
                    raise SourceError(
                        "PDF page content is too large to extract safely in this demo."
                    )
                text = page.extract_text() or ""
                total += len(text)
                if total > MAX_TEXT_CHARS:
                    raise SourceError("Use an excerpt with at most 100,000 extracted characters.")
                pages.append(SourcePage(number=index, text=text))
        except SourceError:
            raise
        except Exception as exc:
            raise SourceError(
                "PDF text could not be extracted. Provide a text/Markdown excerpt."
            ) from exc
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise SourceError("Text and Markdown sources must use UTF-8.") from exc
        if "\x00" in text:
            raise SourceError("Binary content is not a supported text source.")
        if len(text) > MAX_TEXT_CHARS:
            raise SourceError("Use an excerpt with at most 100,000 characters.")
        pages = [SourcePage(number=1, text=text)]
    if not any(page.text.strip() for page in pages):
        raise SourceError(
            "No extractable text was found. Scanned PDFs require OCR, which is not supported."
        )
    digest = hashlib.sha256(data).hexdigest()
    document_id = f"document:{digest[:24]}"
    passages = []
    section = None
    for page in pages:
        # Split at paragraph boundaries, preserving exact extracted text and page offsets.
        for match in re.finditer(r"\S[\s\S]*?(?=\n\s*\n|\Z)", page.text):
            start, end = match.span()
            block = match.group()
            # PDF plain text frequently has no blank lines; split around Markdown headings too.
            boundaries = [
                0,
                *[m.start() for m in re.finditer(r"(?m)^#{1,6}\s+", block) if m.start()],
                len(block),
            ]
            for left, right in zip(boundaries, boundaries[1:]):
                region = block[left:right]
                heading = re.match(r"#{1,6}\s+([^\n]+)", region)
                if heading:
                    section = heading.group(1).strip()
                offset = start + left
                while offset < start + right:
                    stop = min(offset + MAX_PASSAGE_CHARS, start + right)
                    if stop < start + right:
                        boundary = page.text.rfind(" ", offset + MAX_PASSAGE_CHARS // 2, stop)
                        if boundary > offset:
                            stop = boundary
                    piece = page.text[offset:stop]
                    if piece.strip():
                        passages.append(
                            SourcePassage(
                                id=f"{document_id}:p{page.number}:{offset}:{stop}",
                                page=page.number,
                                section=section,
                                start=offset,
                                end=stop,
                                text=piece,
                            )
                        )
                    offset = stop
                    if len(passages) > MAX_PASSAGES:
                        raise SourceError("Use an excerpt with at most 200 passages.")
    return SourceDocument(
        id=document_id,
        title=Path(filename).name,
        kind=kind,
        content_hash=digest,
        pages=pages,
        passages=passages,
        textless_pages=[page.number for page in pages if not page.text.strip()],
    )
