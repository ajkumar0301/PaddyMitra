"""
Open-source, rule-based chunker using LangChain's RecursiveCharacterTextSplitter.

Why this choice:
- Deterministic, no ML model download needed.
- Installs via pip alone on Windows.
- Handles mixed agricultural text (narrative + bullet lists + headings) well.
- Swap to SemanticChunker later by replacing this module's `chunk_text`.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from django.conf import settings
from langchain_text_splitters import RecursiveCharacterTextSplitter


def _splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
        length_function=len,
    )


def chunk_text(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    return [c.strip() for c in _splitter().split_text(text) if c.strip()]


def extract_pdf_text(path: Path | str) -> str:
    """Extract text from a PDF file with pypdf. Returns empty string on failure."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            try:
                pages.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n\n".join(pages).strip()
    except Exception:
        return ""


def document_text(document) -> str:
    """
    Return the best available text body for a Document:
      1. Uploaded file (if PDF)
      2. Fallback body built from metadata + keywords
    """
    if document.file and document.file.path:
        path = Path(document.file.path)
        if path.exists() and path.suffix.lower() == ".pdf":
            txt = extract_pdf_text(path)
            if txt:
                return txt
    # fallback body so every tagged CSV row still produces vectors
    return document.text_for_embedding()
