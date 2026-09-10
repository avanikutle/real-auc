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
# Regex patterns — written to handle multi-line Texas notice formatting
# ---------------------------------------------------------------------------

# Grantor / debtor name lines — two formats:
# 1. "Grantor: Name" style
# 2. "executed by NAME AND NAME" (Williamson County format)
_RE_GRANTOR = re.compile(
    r"(?:Grantor[s]?|Obligor[s]?|Mortgagor[s]?|Debtor[s]?)\ *[:\-\u2013]\ *(.+?)(?:\n|$)",
    re.IGNORECASE,
)
_RE_GRANTOR_EXEC = re.compile(
    r"executed\s+by\s+([A-Z][A-Z\s]+(?:AND|&)\s+[A-Z][A-Z\s]+?)\s+secures",
    re.IGNORECASE,
)

# Property address — two formats:
# 1. Labeled "Property Address: ..."
# 2. All-caps address in header (WilCo format): "297 KOONTZ LOOP, JARRELL, TX 76537"
_RE_ADDRESS = re.compile(
    r"(?:property address|property located at|premises located at|located at)\ *[:\-\u2013]?\ *"
    r"([\d]+\ +[\w\ .,#-]+(?:TX|Texas)\ +\d{5})",
    re.IGNORECASE | re.DOTALL,
)
_RE_ADDRESS_HEADER = re.compile(
    r"(\d{1,5}\s+[A-Z][A-Z0-9\s.,#-]+,\s*[A-Z][A-Z\s]+,\s*TX\s+\d{5})",
)

# Legal description
_RE_LEGAL = re.compile(
    r"(?:legal description|described as follows?|to\s*wit|property description)\s*[:\-–]?\s*"
    r"(.{20,400}?)(?:\n\n|\Z|WHEREAS|Deed of Trust)",
    re.IGNORECASE | re.DOTALL,
)

# Sale date
_RE_SALE_DATE = re.compile(
    r"(?:sale\s+date|sold\s+on|first\s+tuesday)\s*[:\-–]?\s*"
    r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)

# Deed of Trust date
_RE_DOT_DATE = re.compile(
    r"Deed\s+of\s+Trust\s+dated?\s+(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)

# Instrument number — multiple formats:
# 1. "at Instrument Number 2022120311" (WilCo format)
# 2. "Instrument No. XXXXXXXXXX"
# 3. "recorded under Instrument No."
# NOTE: We explicitly avoid matching "DOCUMENT NO." in legal descriptions
#       by prioritizing the Security Instrument section.
_RE_INSTRUMENT = re.compile(
    r"(?:at\s+Instrument\s+Number|Instrument\s+No\.?|Clerk['']?s\s+File\s+No\.?|"
    r"recorded\s+(?:on\s+[\w\s,]+?\s+)?(?:under\s+)?(?:Instrument|Document)\s+(?:Number|No\.?)|Doc\.?\s*No\.?)\s*[:\-\u2013]?\s*"
    r"(\d{9,12})",
    re.IGNORECASE,
)
# Secondary: pattern specifically for Security Instrument section
_RE_INSTRUMENT_SECURITY = re.compile(
    r"Security\s+Instrument[:\s\S]{0,200}?Instrument\s+Number\s+(\d{9,12})",
    re.IGNORECASE | re.DOTALL,
)

# Loan / note amount — multiple formats:
# 1. "in the amount of $274,928.00" (WilCo format)
# 2. "original principal amount of $NNN"
# 3. "note amount: $NNN"
_RE_LOAN_AMOUNT = re.compile(
    r"(?:in\s+the\s+amount\s+of|original\s+(?:principal\s+)?(?:note\s+)?amount|"
    r"note\s+amount|principal\s+amount|principal\s+sum|note\s+of|loan\s+amount)\s*[:\-\u2013]?\s*"
    r"\$\s*([\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Also try bare dollar amounts that look like loan amounts ($NNN,NNN.00)
_RE_DOLLAR = re.compile(r"\$([\d,]{4,}\.?\d*)")

# Lender / mortgagee — multiple formats:
# 1. "Lender: Name" style
# 2. "NAME, is the current mortgagee" (WilCo format)
# 3. "payable to NAME"
_RE_LENDER = re.compile(
    r"(?:Lender|Beneficiary|Payee)\s*[:\-\u2013]\s*(.+?)(?:\n|,\s*a\s+)",
    re.IGNORECASE,
)
_RE_MORTGAGEE = re.compile(
    r"([A-Z][\w\s,\.]+?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing))"
    r"(?:[,\.\s]+whose\s+address|[,\.\s]+is\s+the\s+current\s+mortgagee)",
    re.IGNORECASE,
)
_RE_PAYABLE = re.compile(
    r"(?:note\s+is\s+payable\s+to|payable\s+to)\s+(.+?)(?:\.|\n|$)",
    re.IGNORECASE,
)

# Servicer — WilCo: "LoanCare, LLC is the current mortgage servicer"
_RE_SERVICER = re.compile(
    r"([\w][\w\s,\.]+?(?:LLC|LP|Inc\.?|Corp\.?|Bank|Mortgage|Services?|Servicing))"
    r"\s+is\s+the\s+current\s+mortgage\s+servicer",
    re.IGNORECASE,
)
_RE_SERVICER_ALT = re.compile(
    r"(?:servicer|mortgage\s+servicer|loan\s+servicer)\s*[:\-\u2013]\s*([\w][\w\s,\.]+)",
    re.IGNORECASE,
)

# Trustee — require the colon to distinguish from title "APPOINTMENT OF SUBSTITUTE TRUSTEE"
_RE_TRUSTEE = re.compile(
    r"Substitute\s+Trustee[s]?\s*:\s*(.+?)(?:\n|$)",
    re.IGNORECASE,
)


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


def parse_notice_text(text: str) -> dict[str, Any]:
    """
    Extract all fields from trustee notice text.
    Returns a dict of parsed fields (may have None values for unparsed fields).
    """
    result: dict[str, Any] = {}

    # Owner / grantor — try "executed by" first (WilCo format), then labeled
    owner = _first_match(_RE_GRANTOR_EXEC, text)
    if not owner:
        owner = _first_match(_RE_GRANTOR, text)
    result["owner_full_name"] = owner

    # Address — try labeled format first, then all-caps header style
    addr = _first_match(_RE_ADDRESS, text)
    if not addr:
        addr = _first_match(_RE_ADDRESS_HEADER, text)
    if not addr:
        # Fallback: find street + city + TX + zip pattern
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

    # Sale date
    result["sale_date"] = _parse_date(_first_match(_RE_SALE_DATE, text))

    # Deed of Trust date (used as origination date proxy)
    result["loan_origination_date"] = _parse_date(_first_match(_RE_DOT_DATE, text))

    # Instrument number — prioritize Security Instrument section to avoid
    # matching plat DOCUMENT NO. in legal descriptions
    instrument = _first_match(_RE_INSTRUMENT_SECURITY, text)
    if not instrument:
        instrument = _first_match(_RE_INSTRUMENT, text)
    if not instrument:
        # Last resort: 10-digit number near recording language
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
        # Fallback: largest dollar figure in doc
        matches = _RE_DOLLAR.findall(text)
        amounts = [_parse_amount(m) for m in matches]
        amounts = [a for a in amounts if a and a > 10000]
        result["original_loan_amount"] = max(amounts) if amounts else None

    # Lender / mortgagee
    lender = _first_match(_RE_LENDER, text)
    if not lender:
        lender = _first_match(_RE_MORTGAGEE, text)
    if not lender:
        lender = _first_match(_RE_PAYABLE, text)
    result["lender"] = lender

    # Servicer
    servicer = _first_match(_RE_SERVICER, text)
    if not servicer:
        servicer = _first_match(_RE_SERVICER_ALT, text)
    result["servicer"] = servicer

    # Trustee(s) — must use "Substitute Trustee(s):" label to avoid false matches
    result["trustee"] = _first_match(_RE_TRUSTEE, text)

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
