"""OCR/text extraction helpers.

Priority order for extracting text from a PDF page:
  1. pdfplumber (fast, accurate for text-layer PDFs)
  2. PyMuPDF (fitz) — alternative text layer extraction
  3. pdf2image + pytesseract — fallback for scanned/image-only PDFs

The extract_text() function abstracts this chain.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)


def extract_text(pdf_path: Path) -> tuple[str, float | None]:
    """
    Extract all text from a PDF file.

    Returns:
        (text, ocr_confidence)
        ocr_confidence is None when text-layer extraction succeeded,
        or a 0-100 float when pytesseract was used.
    """
    text = _try_pdfplumber(pdf_path)
    if text and len(text.strip()) > 50:
        log.debug("pdfplumber extracted %d chars from %s", len(text), pdf_path.name)
        return text, None

    text = _try_pymupdf(pdf_path)
    if text and len(text.strip()) > 50:
        log.debug("PyMuPDF extracted %d chars from %s", len(text), pdf_path.name)
        return text, None

    log.info("Text layer empty for %s — falling back to OCR", pdf_path.name)
    text, confidence = _try_tesseract(pdf_path)
    return text, confidence


def _try_pdfplumber(pdf_path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            parts = []
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    parts.append(t)
            return "\n".join(parts)
    except Exception as exc:
        log.debug("pdfplumber failed on %s: %s", pdf_path.name, exc)
        return ""


def _try_pymupdf(pdf_path: Path) -> str:
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        parts = []
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        return "\n".join(parts)
    except Exception as exc:
        log.debug("PyMuPDF failed on %s: %s", pdf_path.name, exc)
        return ""


def _try_tesseract(pdf_path: Path) -> tuple[str, float]:
    """Convert PDF pages to images and OCR each one."""
    try:
        import pytesseract
        from pdf2image import convert_from_path

        images = convert_from_path(str(pdf_path), dpi=300)
        parts = []
        confidences = []
        for img in images:
            data = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
                config="--oem 3 --psm 3",
            )
            words = [
                w for w, c in zip(data["text"], data["conf"])
                if isinstance(c, (int, float)) and c > 0 and w.strip()
            ]
            confs = [
                float(c) for c in data["conf"]
                if isinstance(c, (int, float)) and c > 0
            ]
            parts.append(" ".join(words))
            if confs:
                confidences.extend(confs)

        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(parts), avg_conf
    except Exception as exc:
        log.error("Tesseract OCR failed on %s: %s", pdf_path.name, exc)
        return "", 0.0
