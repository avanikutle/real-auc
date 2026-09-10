"""Step 4 — Deed of Trust document fetching and parsing.

Source: williamson.tx.publicsearch.us (Tyler Technologies OORP)
Access method: Session-based requests (accepts disclaimer cookie, then fetches PDF).

The portal requires:
  1. GET the main page to get initial cookies
  2. Accept the disclaimer (POST or cookie-set)
  3. Search by document number → get document ID
  4. Download PDF via document endpoint

If automated access fails at any step, falls back to manual-assist mode:
  - Prints the direct search URL for the operator
  - Skips download with a comment in step_results

Parsed from DoT PDF:
  - loan_type (FHA / Conventional / VA / USDA)
  - origination_date / maturity_date
  - is_purchase_money: Section 27 checkbox (bool)
  - has_hoa_rider: PUD/HOA rider attachment (bool)

Cache: workspace/{month}/properties/{entry_no}/deed_of_trust.pdf
Idempotent: skips if step_results row exists (unless --force).
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from auction_pipeline import get_county_config, workspace_path
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session
from auction_pipeline.ocr.extract import extract_text

log = logging.getLogger(__name__)

STEP_NAME = "step4_dot"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_PORTAL_BASE = "https://williamson.tx.publicsearch.us"
_SEARCH_URL = f"{_PORTAL_BASE}/results"


def _build_session() -> requests.Session:
    """Create a requests session with initial portal cookies."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        # Load the portal root to pick up session cookies
        r = s.get(_PORTAL_BASE, timeout=15)
        r.raise_for_status()
        # Look for disclaimer form — if present, submit it
        soup = BeautifulSoup(r.text, "lxml")
        form = soup.find("form", {"id": re.compile(r"disclaimer|accept", re.I)})
        if form:
            action = form.get("action", _PORTAL_BASE)
            if not action.startswith("http"):
                action = _PORTAL_BASE + action
            data = {inp.get("name"): inp.get("value", "")
                    for inp in form.find_all("input")
                    if inp.get("name")}
            # Add agree/accept field if missing
            for btn in form.find_all(["input", "button"],
                                      {"type": ["submit", "button"]}):
                name = btn.get("name")
                if name and re.search(r"agree|accept|ok", name, re.I):
                    data[name] = btn.get("value", "1")
            s.post(action, data=data, timeout=15)
            log.info("Submitted disclaimer form")
    except Exception as exc:
        log.debug("Session init issue (non-fatal): %s", exc)
    return s


def _search_by_instrument(session: requests.Session, instrument_no: str) -> str | None:
    """
    Search the portal for instrument_no and return the document view URL or None.
    """
    try:
        resp = session.get(
            _SEARCH_URL,
            params={
                "department": "RP",
                "docNum": instrument_no,
                "recordedDateRange": "",
                "party1LastName": "",
                "party2LastName": "",
                "page": "1",
                "pageSize": "25",
                "searchType": "quickSearch",
                "quickSearchText": instrument_no,
            },
            timeout=20,
        )
        # Tyler Technologies returns JSON for API searches
        if "application/json" in resp.headers.get("Content-Type", ""):
            data = resp.json()
            results = data.get("results", []) or data.get("items", [])
            if results:
                doc_id = results[0].get("docID") or results[0].get("id")
                if doc_id:
                    return f"{_PORTAL_BASE}/doc/{doc_id}"
        # Fallback: parse HTML for result links
        soup = BeautifulSoup(resp.text, "lxml")
        links = soup.find_all("a", href=re.compile(r"/doc/\d+"))
        if links:
            return _PORTAL_BASE + links[0]["href"]
    except Exception as exc:
        log.debug("Portal search failed: %s", exc)
    return None


def _download_doc_pdf(
    session: requests.Session,
    doc_url: str,
    dest: Path,
    force: bool,
) -> bool:
    """Download a document PDF from the portal. Returns True on success."""
    if dest.exists() and not force:
        log.info("[cached] DoT PDF for %s", dest)
        return True

    pdf_url = doc_url.rstrip("/") + "/pdf" if "/pdf" not in doc_url else doc_url
    try:
        resp = session.get(pdf_url, timeout=60, stream=True)
        if resp.status_code == 200 and "pdf" in resp.headers.get("Content-Type", "").lower():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(65536):
                    fh.write(chunk)
            log.info("Saved DoT PDF: %s (%.1f KB)", dest, dest.stat().st_size / 1024)
            return True
        log.warning("PDF download failed: status=%s type=%s",
                    resp.status_code, resp.headers.get("Content-Type"))
    except Exception as exc:
        log.warning("DoT PDF download error: %s", exc)
    return False


# ---------------------------------------------------------------------------
# DoT text parsing
# ---------------------------------------------------------------------------

def parse_dot_text(text: str) -> dict:
    """
    Parse Deed of Trust text to extract key fields.
    Returns a dict with all parseable fields.
    """
    result: dict = {}

    # Loan type detection
    loan_type = None
    if re.search(r"\bFHA\b|\bFederal\s+Housing\s+Administration\b", text, re.I):
        loan_type = "FHA"
    elif re.search(r"\bVA\b|\bVeterans\s+Affairs\b|\bDept\.?\s+of\s+Veterans\b", text, re.I):
        loan_type = "VA"
    elif re.search(r"\bUSDA\b|\bRural\s+(?:Housing|Development)\b", text, re.I):
        loan_type = "USDA"
    else:
        loan_type = "Conventional"
    result["loan_type"] = loan_type

    # Origination date
    m = re.search(
        r"(?:dated|executed\s+on|effective\s+date[:\s]+)\s*(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        text, re.IGNORECASE
    )
    result["origination_date"] = m.group(1).strip() if m else None

    # Maturity date
    m = re.search(
        r"(?:maturity\s+date|due\s+date|payable\s+in\s+full|due\s+on)\s*[:\-]?\s*"
        r"(\w+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
        text, re.IGNORECASE
    )
    result["maturity_date"] = m.group(1).strip() if m else None

    # Section 27 Purchase Money checkbox
    # The checkbox is "checked" if the text near "Section 27" has an X or check mark
    s27_match = re.search(
        r"(?:Section\s+27|Purchase\s+Money)[^.]{0,200}?\[([Xx\u2713\u2714\u2611]?)\]",
        text, re.IGNORECASE | re.DOTALL
    )
    if s27_match:
        result["is_purchase_money"] = bool(s27_match.group(1).strip())
    else:
        # If "purchase money" language appears without checkbox syntax
        result["is_purchase_money"] = bool(
            re.search(r"purchase\s+money\s+mortgage|purchase\s+money\s+deed", text, re.I)
        )

    # HOA / PUD rider
    result["has_hoa_rider"] = bool(
        re.search(
            r"(?:Planned\s+Unit\s+Development\s+Rider|PUD\s+Rider|"
            r"Condominium\s+Rider|HOA|Homeowners?\s+Association\s+Rider)",
            text, re.IGNORECASE
        )
    )

    return result


# ---------------------------------------------------------------------------
# Main step runner
# ---------------------------------------------------------------------------

def _run_one(session, prop: Property, force: bool, portal_session: requests.Session) -> None:
    if not force:
        existing = (
            session.query(StepResult)
            .filter_by(entry_no=prop.entry_no, step_name=STEP_NAME)
            .first()
        )
        if existing:
            log.info("[cached] step4 already done for %s", prop.entry_no)
            return

    if not prop.instrument_number:
        log.warning("No instrument number for %s — skipping DoT fetch", prop.entry_no)
        return

    pdf_dest = workspace_path(
        prop.month, "properties", prop.entry_no, "deed_of_trust.pdf"
    )
    extracted: dict = {"instrument_number": prop.instrument_number}
    doc_url = None
    pdf_ok = pdf_dest.exists() and not force

    if not pdf_ok:
        # Search the portal
        doc_url = _search_by_instrument(portal_session, prop.instrument_number)
        if doc_url:
            pdf_ok = _download_doc_pdf(portal_session, doc_url, pdf_dest, force)
            time.sleep(0.5)
        else:
            # NOTE: Could not retrieve DoT from williamson.tx.publicsearch.us.
            # The portal may require JS rendering or session authentication.
            # Manual lookup: https://williamson.tx.publicsearch.us
            # Search by Document Number: {instrument_number}
            log.info(
                "[DoT not auto-fetched] %s instrument=%s — manual lookup: %s",
                prop.entry_no, prop.instrument_number,
                f"https://williamson.tx.publicsearch.us/results?quickSearchText={prop.instrument_number}",
            )
            extracted["manual_lookup_url"] = (
                f"https://williamson.tx.publicsearch.us/results"
                f"?quickSearchText={prop.instrument_number}"
            )

    # Parse if PDF was obtained
    if pdf_ok and pdf_dest.exists():
        text, conf = extract_text(pdf_dest)
        if text.strip():
            dot_fields = parse_dot_text(text)
            extracted.update(dot_fields)

            # Update properties row
            if dot_fields.get("loan_type") and not prop.loan_type:
                prop.loan_type = dot_fields["loan_type"]
            if dot_fields.get("is_purchase_money") is not None:
                prop.is_purchase_money = dot_fields["is_purchase_money"]
            if dot_fields.get("has_hoa_rider") is not None:
                prop.has_hoa_rider = dot_fields["has_hoa_rider"]
            session.add(prop)

    # Persist step_results
    sr = StepResult(
        entry_no=prop.entry_no,
        step_name=STEP_NAME,
        source_url=doc_url,
        source_file_path=str(pdf_dest) if pdf_ok else None,
        extracted_json=json.dumps(extracted, default=str),
    )
    session.add(sr)


def run_step(
    month: str,
    county: str = "williamson",
    entry_no: str | None = None,
    force: bool = False,
) -> None:
    portal_session = _build_session()
    db_session = get_session()
    try:
        query = db_session.query(Property).filter_by(month=month, county=county)
        if entry_no:
            query = query.filter_by(entry_no=entry_no)
        props = query.all()
        log.info("Running step4 (DoT) on %d properties", len(props))
        for prop in props:
            _run_one(db_session, prop, force=force, portal_session=portal_session)
        db_session.commit()
        log.info("Step 4 (DoT) complete")
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()
