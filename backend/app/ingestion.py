"""
Document ingestion for the AUTOSAR HLD Document Analysis Assistant.

Pipeline
--------
1. extract_pdf_content : per page -> text lines (with y-position and font size) and tables
                         (with y-position). Falls back to OCR for scanned pages.
2. build_chunks        : walks each page top-to-bottom, so every paragraph and every table
                         is attached to the *closest heading above it*. Produces
                         retrieval chunks plus the raw structured tables that the entity
                         extractor consumes.

Why position-aware? A page can hold several headings and several tables
(e.g. "3.1 CentralLockingMgr Ports", "3.2 WindowLiftMgr Ports"). Assigning
"the last heading on the page" to every table would mislabel them and break
port-to-component ownership. Sorting by vertical position avoids that.
"""
import hashlib
import logging
import re
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber
from . import config

logger = logging.getLogger(__name__)

# Optional OCR dependencies - ingestion still works without them.
try:  # pragma: no cover - depends on the local machine
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:  # pragma: no cover
    pytesseract = None  # type: ignore[assignment]
    _OCR_AVAILABLE = False

HEADING_NUMBERED = re.compile(r"^\d+(?:\.\d+)*\.?\s+\S.{1,78}$")
DOC_ID_PATTERN = re.compile(r"Document\s*ID\s*:\s*([A-Za-z0-9._\-]+)", re.IGNORECASE)

INITIAL_SECTION = "Document Start"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_file_hash(file_path: str) -> str:
    """SHA-256 of the file, used to detect duplicate uploads."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _clean_rows(rows: List[List[Any]]) -> List[List[str]]:
    """Normalise a pdfplumber table: None -> '', collapse whitespace, drop empty rows."""
    cleaned = []
    for row in rows or []:
        new_row = [re.sub(r"\s+", " ", str(c)).strip() if c is not None else "" for c in row]
        if any(new_row):
            cleaned.append(new_row)
    return cleaned


def _ocr_page(page) -> List[Dict[str, Any]]:  # pragma: no cover - needs tesseract binary
    """OCR fallback for scanned pages. Returns pseudo text-lines (no font size)."""
    if not (config.OCR_ENABLED and _OCR_AVAILABLE):
        return []
    try:
        image = page.to_image(resolution=config.OCR_RESOLUTION_DPI).original
        text = pytesseract.image_to_string(image)
    except Exception as exc:
        logger.warning("OCR failed on page %s: %s", getattr(page, "page_number", "?"), exc)
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [{"text": ln, "top": float(i) * 10.0, "size": None} for i, ln in enumerate(lines)]


# ---------------------------------------------------------------------------
# Step 1: extraction
# ---------------------------------------------------------------------------
def extract_pdf_content(file_path: str) -> List[Dict[str, Any]]:
    """
    Returns one dict per page:
        {"page": int, "lines": [{"text","top","size"}], "tables": [{"top","rows"}], "ocr_used": bool}
    Table regions are cropped out of the text stream so table cells are not
    duplicated as loose paragraph text.
    """
    pages: List[Dict[str, Any]] = []
    with pdfplumber.open(file_path) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                found_tables = page.find_tables()
            except Exception as exc:
                logger.warning("Table detection failed on page %d: %s", idx, exc)
                found_tables = []

            tables = []
            for t in found_tables:
                rows = _clean_rows(t.extract())
                if rows:
                    tables.append({"top": float(t.bbox[1]), "rows": rows})

            region = page
            for t in found_tables:
                try:
                    region = region.outside_bbox(t.bbox)
                except Exception:
                    pass  # if cropping fails we simply keep some duplicate text

            lines = []
            try:
                raw_lines = region.extract_text_lines(return_chars=True) or []
            except Exception as exc:
                logger.warning("Text extraction failed on page %d: %s", idx, exc)
                raw_lines = []
            for ln in raw_lines:
                text = (ln.get("text") or "").strip()
                if not text:
                    continue
                chars = ln.get("chars") or []
                size = float(chars[0]["size"]) if chars and "size" in chars[0] else None
                lines.append({"text": text, "top": float(ln["top"]), "size": size})

            ocr_used = False
            if not lines and not tables:
                lines = _ocr_page(page)
                ocr_used = bool(lines)

            pages.append({"page": idx, "lines": lines, "tables": tables, "ocr_used": ocr_used})
    return pages


def extract_document_metadata(pages: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """Best-effort title and document ID from the first page."""
    if not pages or not pages[0]["lines"]:
        return {"document_id": None, "title": None}
    first_page_text = "\n".join(l["text"] for l in pages[0]["lines"])
    match = DOC_ID_PATTERN.search(first_page_text)
    title_lines = [l["text"] for l in pages[0]["lines"][:2]]
    return {
        "document_id": match.group(1) if match else None,
        "title": " - ".join(title_lines) if title_lines else None,
    }


# ---------------------------------------------------------------------------
# Step 2: chunking
# ---------------------------------------------------------------------------
def _is_heading(text: str, size: Optional[float], body_size: Optional[float]) -> bool:
    """A heading is short, doesn't end like a sentence, and is numbered or visibly larger."""
    if len(text) > 80 or text.endswith((".", ",", ";", ":")):
        return False
    if HEADING_NUMBERED.match(text):
        return True
    if size and body_size and size >= body_size * 1.25 and len(text.split()) <= 12:
        return True
    return False


def _split_text(text: str, max_chars: int) -> List[str]:
    """Split long text on line boundaries so no chunk exceeds max_chars."""
    if len(text) <= max_chars:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > max_chars:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


def _emit_text_chunks(chunks, buffer, page, section, max_chars):
    body = "\n".join(buffer).strip()
    if len(body) < config.MIN_CHUNK_CHARS:
        return
    for part in _split_text(body, max_chars):
        chunks.append(
            {
                "text": f"[Section: {section}]\n{part}",
                "page": page,
                "section": section,
                "chunk_type": "text",
            }
        )


def _emit_table_chunks(chunks, rows, page, section, max_chars):
    """Render a table as text; split large tables by rows, repeating the header row."""
    header = " | ".join(rows[0])
    prefix = f"[Table in section: {section}]\n"
    current_rows: List[str] = []
    current_len = len(prefix) + len(header)

    def flush():
        if current_rows:
            chunks.append(
                {
                    "text": prefix + header + "\n" + "\n".join(current_rows),
                    "page": page,
                    "section": section,
                    "chunk_type": "table",
                }
            )

    for row in rows[1:]:
        row_text = " | ".join(row)
        if current_rows and current_len + len(row_text) + 1 > max_chars:
            flush()
            current_rows, current_len = [], len(prefix) + len(header)
        current_rows.append(row_text)
        current_len += len(row_text) + 1
    if current_rows:
        flush()
    elif len(rows) == 1:  # header-only table
        chunks.append(
            {"text": prefix + header, "page": page, "section": section, "chunk_type": "table"}
        )


def build_chunks(
    pages: List[Dict[str, Any]], max_chars: int = config.MAX_CHUNK_CHARS
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (chunks, structured_tables)

    chunks            : [{"text","page","section","chunk_type"}] ready for embedding
    structured_tables : [{"page","section","rows"}] consumed by entity_extraction
    """
    chunks: List[Dict[str, Any]] = []
    structured_tables: List[Dict[str, Any]] = []
    section = INITIAL_SECTION

    for page in pages:
        sizes = [l["size"] for l in page["lines"] if l["size"]]
        body_size = statistics.median(sizes) if sizes else None

        items = [("line", l["top"], l) for l in page["lines"]] + [
            ("table", t["top"], t) for t in page["tables"]
        ]
        items.sort(key=lambda it: it[1])  # top-to-bottom reading order

        buffer: List[str] = []
        for kind, _top, payload in items:
            if kind == "line":
                text = payload["text"]
                if _is_heading(text, payload["size"], body_size):
                    _emit_text_chunks(chunks, buffer, page["page"], section, max_chars)
                    buffer = [text]
                    section = text
                else:
                    buffer.append(text)
            else:  # table
                _emit_text_chunks(chunks, buffer, page["page"], section, max_chars)
                buffer = []
                rows = payload["rows"]
                _emit_table_chunks(chunks, rows, page["page"], section, max_chars)
                structured_tables.append({"page": page["page"], "section": section, "rows": rows})

        _emit_text_chunks(chunks, buffer, page["page"], section, max_chars)

    return chunks, structured_tables