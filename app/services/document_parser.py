"""Turns uploaded files into page-numbered text. No AI here - deterministic only."""
import hashlib
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import pandas as pd
import pymupdf as fitz
from docx import Document

from app.log import get_logger

log = get_logger("parser")

SUPPORTED = {".pdf", ".xlsx", ".docx", ".csv"}
MIN_CHARS_PER_PAGE = 30  # below this, a PDF page is treated as scanned


class DocumentError(Exception):
    """Error whose message is safe to show to a non-technical user."""


@dataclass
class ParsedDocument:
    filename: str
    file_type: str
    sha256: str
    pages: list  # list of (page_number, text)
    needs_vision: bool = False
    raw_bytes: bytes = field(default=b"", repr=False)
    warnings: list = field(default_factory=list)

    def as_prompt_text(self) -> str:
        return "\n\n".join(f"=== PAGE {n} ===\n{t}" for n, t in self.pages)


def parse_document(filename: str, data: bytes, max_mb: int = 15) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise DocumentError(f"'{filename}': unsupported file type '{ext}'. Please upload PDF, XLSX, DOCX or CSV.")
    if not data:
        raise DocumentError(f"'{filename}' is empty (0 bytes).")
    if len(data) > max_mb * 1024 * 1024:
        raise DocumentError(f"'{filename}' is larger than {max_mb} MB.")

    try:
        _check_signature(ext, data)
        pages, needs_vision, warnings = _PARSERS[ext](data)
    except DocumentError as e:
        raise DocumentError(f"'{filename}' {e}") from e
    except Exception as e:  # library-level failure = unreadable file
        log.warning(f"parse_failed file_type={ext} error={type(e).__name__}")
        raise DocumentError(
            f"'{filename}' could not be opened - the file seems damaged or incomplete. "
            "Try downloading or saving it again."
        ) from e

    return ParsedDocument(
        filename=filename, file_type=ext.lstrip("."), sha256=hashlib.sha256(data).hexdigest(),
        pages=pages, needs_vision=needs_vision, raw_bytes=data, warnings=warnings,
    )


def _check_signature(ext: str, data: bytes) -> None:
    if ext == ".pdf" and b"%PDF" not in data[:1024]:
        raise DocumentError("is not a real PDF (its content does not match the .pdf extension).")
    if ext in (".xlsx", ".docx") and not data.startswith(b"PK"):
        raise DocumentError(f"is not a real {ext} file (its content does not match the extension).")
    if ext == ".csv" and b"\x00" in data[:2048]:
        raise DocumentError("looks like a binary file, not a CSV.")


def _pdf(data: bytes):
    doc = fitz.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        raise DocumentError("is password-protected. Please upload an unlocked copy.")
    if doc.page_count == 0:
        raise DocumentError("has no pages - the file may be corrupted.")
    pages = [(i + 1, p.get_text("text").strip()) for i, p in enumerate(doc)]
    low_text = sum(len(t) < MIN_CHARS_PER_PAGE for _, t in pages)
    needs_vision = low_text > len(pages) / 2
    warnings = (["Little or no selectable text - looks scanned. Gemini will read the page images; "
                 "please double-check extracted values."] if needs_vision else [])
    return pages, needs_vision, warnings


def _xlsx(data: bytes):
    sheets = pd.read_excel(BytesIO(data), sheet_name=None, header=None)
    pages = []
    for i, (name, df) in enumerate(sheets.items(), start=1):
        df = df.dropna(how="all").dropna(axis=1, how="all")
        text = df.to_csv(index=False, header=False).strip()
        pages.append((i, f"[Sheet: {name}]\n{text}"))
    if not any(t.split("\n", 1)[-1].strip() for _, t in pages):
        raise DocumentError("contains no data.")
    return pages, False, []


def _docx(data: bytes):
    doc = Document(BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    text = "\n".join(parts).strip()
    if not text:
        raise DocumentError("contains no text.")
    return [(1, text)], False, []


def _csv(data: bytes):
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    if not text.strip():
        raise DocumentError("contains no data.")
    return [(1, text.strip())], False, []


_PARSERS = {".pdf": _pdf, ".xlsx": _xlsx, ".docx": _docx, ".csv": _csv}
