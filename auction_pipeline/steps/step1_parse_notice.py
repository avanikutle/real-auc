"""Step 1 — Trustee notice parser.

For each property in workspace/{month}/properties/{entry_no}/trustee_notice.pdf:
  1. Extract text via pdfplumber / PyMuPDF / pytesseract fallback
  2. Parse fields via regex
  3. Persist to step_results (step_name=step1_trustee_notice) as JSON
  4. Update properties row with all extracted fields

Idempotent: skips entries that already have a step_results row unless --force.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from auction_pipeline import workspace_path
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session
from auction_pipeline.ocr.extract import extract_text

log = logging.getLogger(__name__)

STEP_NAME = "step1_trustee_notice"


# ---------------------------------------------------------------------------
# Regex patterns — 3 real-world Williamson County notice formats:
#   Format A:  "NAMES, as Grantor/Borrower, executed..."   (file_007 style)
#   Format B:  "Deed of Trust executed by NAMES secures"   (file_008 style)
#   Format C:  "executed by NAMES" anywhere with AND/&     (WilCo standard)
#   Format D:  "Grantor: Name" explicit label
# ---------------------------------------------------------------------------

# Format A: "NAMES, as Grantor/Borrower" — captures everything before the comma
_RE_GRANTOR_BORROWER = re.compile(
    r"([A-Z][A-Z\s,\.]+?(?:\s+AND\s+[A-Z][A-Z\s,\.]+?)?)"
    r",\s*(?:as\s+)?Grantor[/\\]?Borrower",
    re.IGNORECASE,
)

# Format A2: "NAMES, grantor(s)" — name before grantor label (file_020 style)
_RE_GRANTOR_SUFFIX = re.compile(
    r"(?:by|with)\s+([A-Z][A-Z\s]+(?:AND|&)\s+[A-Z][A-Z\s]+?|[A-Z][A-Z\s]+?),?\s+(?:HUSBAND\s+AND\s+WIFE,?\s+)?grantor[s]?\(",
    re.IGNORECASE,
)

# Format T: "Trustor(s): NAME" — file_011 style
_RE_TRUSTOR = re.compile(
    r"Trustor[s]?\s*\(?s?\)?\s*[:\-\u2013]\s*([A-Z][A-Z\s,\.]+?)(?:\s*(?:,\s*A\s+SINGLE|Original|\n|$))",
    re.IGNORECASE,
)

# Format B: "executed by NAMES secures" — single or multiple names
_RE_GRANTOR_EXEC_SINGLE = re.compile(
    r"executed\s+by\s+([A-Z][A-Z\s,\.]+?)\s+secures",
    re.IGNORECASE,
)

# Format C: "executed by NAMES AND NAMES" anywhere
_RE_GRANTOR_EXEC = re.compile(
    r"executed\s+by\s+([A-Z][A-Z\s]+(?:AND|&)\s+[A-Z][A-Z\s]+?)(?:\s+secures|\s*,)",
    re.IGNORECASE,
)

# Format D: explicit Grantor/Mortgagor/Trustor label — handles variants like Grantor(s)/Mortgagor(s):
_RE_GRANTOR = re.compile(
    r"(?:Grantor[s]?(?:\(s\))?(?:[/\\]Mortgagor[s]?(?:\(s\))?)?|Obligor[s]?|Mortgagor[s]?(?:\(s\))?|Debtor[s]?)\s*[:\-\u2013]\s*(.+?)(?:\n|,\s*(?:as\s+)?(?:grantor|borrower)|Current\s+Beneficiary|$)",
    re.IGNORECASE,
)

# Property address
_RE_ADDRESS = re.compile(
    r"(?:property address|property located at|premises located at|located at|commonly known as)\s*[:\-\u2013]?\s*"
    r"([\d]+\s+[\w\s.,#-]+(?:TX|Texas)\s+\d{5})",
    re.IGNORECASE | re.DOTALL,
)
_RE_ADDRESS_HEADER = re.compile(
    r"(\d{1,5}\s+[A-Z][A-Z0-9\s.,#-]+,\s*[A-Z][A-Z\s]+,\s*TX\s+\d{5})",
)

# Legal description
_RE_LEGAL = re.compile(
    r"(?:legal description|described as follows?|to\s*wit|property description|property to be sold[:\s-]*)\s*[:\-–]?\s*"
    r"(.{20,400}?)(?:\n\n|\Z|WHEREAS|Deed of Trust|Security Instrument|Sale Information)",
    re.IGNORECASE | re.DOTALL,
)

# Sale date — handle "9/1/2026" and "September 1, 2026" and "Date: 9/1/2026"
_RE_SALE_DATE = re.compile(
    r"(?:Date\s*[:\-]?\s*|sale\s+date\s*[:\-]?\s*|sold\s+on\s+|first\s+tuesday\s+)"
    r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)

# Deed of Trust date
_RE_DOT_DATE = re.compile(
    r"Deed\s+of\s+Trust\s+dated?\s+(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)

# Instrument number
_RE_INSTRUMENT = re.compile(
    r"(?:at\s+Instrument\s+Number|Instrument\s+No\.?|Clerk['']?s\s+File\s+No\.?|"
    r"recorded\s+(?:on\s+[\w\s,]+?\s+)?(?:under\s+)?(?:Instrument|Document)\s+(?:Number|No\.?)|Doc\.?\s*No\.?)(?:\s+Number)?\s*[:\-\u2013]?\s*"
    r"(\d{9,12})",
    re.IGNORECASE,
)
_RE_INSTRUMENT_SECURITY = re.compile(
    r"Security\s+Instrument[\:\s\S]{0,200}?Instrument\s+Number\s+(\d{9,12})",
    re.IGNORECASE | re.DOTALL,
)

# Loan amount
_RE_LOAN_AMOUNT = re.compile(
    r"(?:in\s+the\s+amount\s+of|original\s+(?:principal\s+)?(?:note\s+)?amount|"
    r"note\s+amount|principal\s+amount|principal\s+sum|note\s+of|loan\s+amount)\s*[:\-\u2013]?\s*"
    r"\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)
_RE_DOLLAR = re.compile(r"\$([\d,]{4,}\.?\d*)")

# Lender — stop at common separators, not at arbitrary commas
# "payable to the order of LENDER NAME, its successors"
_RE_LENDER_PAYABLE = re.compile(
    r"payable\s+to(?:\s+the\s+order\s+of)?\s+([A-Z][\w\s,\.]+?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing|Associates?))"
    r"(?:,\s*its|\.|$)",
    re.IGNORECASE,
)
# "LENDER NAME, is the current mortgagee / whose address"
_RE_MORTGAGEE = re.compile(
    r"([A-Z][\w\s,\.]{3,80}?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing|Associates?))"
    r"(?:[,\.\s]+whose\s+address|[,\.\s]+is\s+the\s+current\s+mortgagee)",
    re.IGNORECASE,
)
_RE_LENDER_LABEL = re.compile(
    r"(?:Current\s+)?(?:Beneficiary|Mortgagee)[/\\]?(?:Mortgagee|Beneficiary)?\s*[:\-\u2013]\s*([A-Z][\w\s,\.]{3,80}?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing|Associates?))",
    re.IGNORECASE,
)
_RE_LENDER = re.compile(
    r"(?:Lender|Beneficiary|Payee)\s*[:\-\u2013]\s*(.+?)(?:\n|,\s*a\s+)",
    re.IGNORECASE,
)

# Servicer — only capture the company name, not the address
# "Rocket Mortgage, LLC is the current mortgage servicer"
# or "...and Rocket Mortgage, LLC is the current mortgage servicer"
_RE_SERVICER = re.compile(
    r"(?:^|and\s+|,\s*)([A-Z][\w\s\.]{2,60}?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing|Associates?))"
    r"(?:,\s*[\w\s\.]*?)?\s+is\s+the\s+current\s+mortgage\s+servicer",
    re.IGNORECASE | re.MULTILINE,
)
_RE_SERVICER_LABEL = re.compile(
    r"(?:Mortgage\s+Servicer|Loan\s+Servicer|Servicer)\s*[:\-\u2013]\s*([\w][\w\s,\.]{3,80}?)(?:\n|$|Mortgage\s+Servicer\s+Address)",
    re.IGNORECASE,
)
_RE_SERVICER_REPRESENTING = re.compile(
    r"([A-Z][\w\s\.]{2,60}?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing|Associates?|N\.A\.))"
    r"\s+is\s+representing\s+the\s+Current",
    re.IGNORECASE | re.MULTILINE,
)

# Trustee — require the colon
_RE_TRUSTEE = re.compile(
    r"Substitute\s+Trustee[s]?\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)

# Backward-compatibility aliases
_RE_GRANTOR_ALT = _RE_GRANTOR
_RE_PAYABLE = _RE_LENDER_PAYABLE
_RE_SERVICER_ALT = _RE_SERVICER_LABEL


# ---------------------------------------------------------------------------
# Field parsers
# ---------------------------------------------------------------------------

def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip().rstrip(",").strip()
    formats = [
        "%B %d %Y", "%b %d %Y", "%B %d, %Y", "%b %d, %Y",
        "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount(s: str | None) -> float | None:
    if not s:
        return None
    clean = re.sub(r"[^\d.]", "", s)
    try:
        return float(clean)
    except ValueError:
        return None


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _clean_name(s: str | None) -> str | None:
    """Clean up extracted name strings — strip trailing/leading junk."""
    if not s:
        return None
    # Remove common OCR noise and trailing punctuation
    s = re.sub(r"\s+", " ", s).strip().strip(".,;:")
    # Remove anything after "as Grantor", "hereinafter", "Borrower", "Trustee", "Beneficiary"
    s = re.split(r"\s+(?:as\s+Grantor|hereinafter|Borrower|AND\s+WIFE\b|Trustee:|Beneficiary:|Recorded:)", s)[0].strip()
    # Must be at least 4 chars and contain a letter
    if len(s) < 4 or not re.search(r"[A-Za-z]{2,}", s):
        return None
    return s[:200]


def _clean_company(s: str | None, max_len: int = 80) -> str | None:
    """Trim a company name to just the entity name — stops at address indicators."""
    if not s:
        return None
    s = re.sub(r"\s+", " ", s).strip()
    # Stop at address-like content
    for stop in [", whose address", ", c/o ", ", 8950", "Mortgage Servicer Address", "\nMortgage"]:
        if stop.lower() in s.lower():
            s = s[:s.lower().index(stop.lower())]
    return s.strip(".,:;")[:max_len] or None


def parse_notice_text(text: str) -> dict[str, Any]:
    """
    Extract all fields from trustee notice text.
    Returns a dict of parsed fields (may have None values for unparsed fields).
    """
    result: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Owner / Grantor — try 4 formats in priority order
    # ------------------------------------------------------------------
    # Format A: "NAMES, as Grantor/Borrower"
    owner = _clean_name(_first_match(_RE_GRANTOR_BORROWER, text))
    # Format A2: "NAMES, grantor(s)" suffix (file_020 style)
    if not owner:
        owner = _clean_name(_first_match(_RE_GRANTOR_SUFFIX, text))
    # Format T: "Trustor(s): NAMES" (file_011 style)
    if not owner:
        owner = _clean_name(_first_match(_RE_TRUSTOR, text))
    # Format C: "executed by NAMES AND NAMES" (multi-name with AND/&)
    if not owner:
        owner = _clean_name(_first_match(_RE_GRANTOR_EXEC, text))
    # Format B: "executed by NAME secures" (single name)
    if not owner:
        owner = _clean_name(_first_match(_RE_GRANTOR_EXEC_SINGLE, text))
    # Format D: explicit "Grantor(s)/Mortgagor(s):" label
    if not owner:
        owner = _clean_name(_first_match(_RE_GRANTOR, text))
    result["owner_full_name"] = owner

    # ------------------------------------------------------------------
    # Address
    # ------------------------------------------------------------------
    addr = _first_match(_RE_ADDRESS, text)
    if not addr:
        addr = _first_match(_RE_ADDRESS_HEADER, text)
    if not addr:
        m = re.search(
            r"(\d+\s+[\w\s.#-]+?,\s*[\w\s]+,\s*(?:TX|Texas)\s*\d{5})",
            text, re.IGNORECASE
        )
        addr = m.group(1).strip() if m else None
    result["address"] = addr

    # Legal description
    legal = _first_match(_RE_LEGAL, text)
    if legal:
        legal = re.sub(r"\s+", " ", legal).strip()
    result["legal_description"] = legal

    # Sale date — filter out dates that are clearly filing/recording dates
    result["sale_date"] = _parse_date(_first_match(_RE_SALE_DATE, text))

    # Deed of Trust origination date
    result["loan_origination_date"] = _parse_date(_first_match(_RE_DOT_DATE, text))

    # Instrument number
    instrument = _first_match(_RE_INSTRUMENT_SECURITY, text)
    if not instrument:
        instrument = _first_match(_RE_INSTRUMENT, text)
    if not instrument:
        m = re.search(
            r"(?:recorded|filed|clerk['']?s\s+file)\s*[:\-\u2013]?\s*(\d{9,12})",
            text, re.IGNORECASE
        )
        if m:
            instrument = m.group(1)
    result["instrument_number"] = instrument

    # Loan amount
    loan_str = _first_match(_RE_LOAN_AMOUNT, text)
    result["original_loan_amount"] = _parse_amount(loan_str)
    if not result["original_loan_amount"]:
        matches = _RE_DOLLAR.findall(text)
        amounts = [_parse_amount(m) for m in matches]
        amounts = [a for a in amounts if a and a > 10000]
        result["original_loan_amount"] = max(amounts) if amounts else None

    # ------------------------------------------------------------------
    # Lender — clean to just company name
    # ------------------------------------------------------------------
    lender = _clean_company(_first_match(_RE_LENDER_PAYABLE, text))
    if not lender:
        lender = _clean_company(_first_match(_RE_MORTGAGEE, text))
    if not lender:
        lender = _clean_company(_first_match(_RE_LENDER_LABEL, text))
    if not lender:
        lender = _clean_company(_first_match(_RE_LENDER, text))
    result["lender"] = lender

    # ------------------------------------------------------------------
    # Servicer — clean to just company name
    # ------------------------------------------------------------------
    servicer = _clean_company(_first_match(_RE_SERVICER, text))
    if not servicer:
        servicer = _clean_company(_first_match(_RE_SERVICER_LABEL, text))
    if not servicer:
        servicer = _clean_company(_first_match(_RE_SERVICER_REPRESENTING, text))
    result["servicer"] = servicer

    # Trustee — first name only (before comma or newline)
    trustee_raw = _first_match(_RE_TRUSTEE, text)
    if trustee_raw:
        # Often "John Smith, Attorney at Law" — take only first name segment
        trustee_raw = trustee_raw.split(",")[0].strip()
    result["trustee"] = trustee_raw

    return result


# ---------------------------------------------------------------------------
# Main step runner
# ---------------------------------------------------------------------------

def _already_run(session, entry_no: str) -> bool:
    return (
        session.query(StepResult)
        .filter_by(entry_no=entry_no, step_name=STEP_NAME)
        .first()
    ) is not None


def _run_one(session, prop: Property, force: bool) -> None:
    if not force and _already_run(session, prop.entry_no):
        log.info("[cached] step1 already done for %s", prop.entry_no)
        return

    pdf_path = workspace_path(
        prop.month, "properties", prop.entry_no, "trustee_notice.pdf"
    )
    if not pdf_path.exists():
        log.warning("PDF not found for %s: %s", prop.entry_no, pdf_path)
        return

    log.info("Parsing %s", prop.entry_no)
    text, ocr_conf = extract_text(pdf_path)

    if not text.strip():
        log.warning("Empty text for %s", prop.entry_no)
        return

    fields = parse_notice_text(text)
    log.debug("Parsed fields: %s", fields)

    # Persist to step_results
    sr = (
        session.query(StepResult)
        .filter_by(entry_no=prop.entry_no, step_name=STEP_NAME)
        .first()
    )
    if sr is None:
        sr = StepResult(entry_no=prop.entry_no, step_name=STEP_NAME)
    sr.source_file_path = str(pdf_path)
    sr.extracted_json = json.dumps(fields, default=str)
    sr.ocr_confidence = ocr_conf
    session.add(sr)

    # Update properties row
    for field, value in fields.items():
        if value is not None and hasattr(prop, field):
            setattr(prop, field, value)
    prop.status = "step1_done"
    session.add(prop)


def run_step(
    month: str,
    county: str = "williamson",
    entry_no: str | None = None,
    force: bool = False,
) -> None:
    session = get_session()
    try:
        query = session.query(Property).filter_by(month=month, county=county)
        if entry_no:
            query = query.filter_by(entry_no=entry_no)
        props = query.all()
        log.info("Running step1 on %d properties", len(props))
        for prop in props:
            _run_one(session, prop, force)
        session.commit()
        log.info("Step 1 complete")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
