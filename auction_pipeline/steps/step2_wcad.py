"""Step 2 — WCAD (Williamson Central Appraisal District) appraisal data.

Resolution strategy (in priority order):
  1. Query WCAD property search by address → parse R Number + assessed value from HTML
  2. Try direct PDF at documents.wcad.org/{year}/{r_number}.pdf
  3. If login redirect on PDF → log a comment with the manual URL and store
     whatever assessed-value data was found in step 1.

Cache: workspace/{month}/properties/{entry_no}/wcad_appraisal.pdf
Idempotent: skips if step_results already has a step2_wcad row (unless --force).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from auction_pipeline import get_county_config, workspace_path
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session

log = logging.getLogger(__name__)

STEP_NAME = "step2_wcad"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_WCAD_SEARCH_URL = "https://www.wcad.org/property-search/"


def _search_wcad_by_address(address: str) -> dict | None:
    """
    Query WCAD property search and return {r_number, assessed_value, ...} or None.
    Uses the WCAD quick search form.
    """
    if not address:
        return None

    # Extract the street number and name from the address string
    # e.g. "297 KOONTZ LOOP, JARRELL, TX 76537" → "297 KOONTZ LOOP"
    m = re.match(r"(\d+\s+[\w\s.]+?)(?:,|TX|$)", address, re.IGNORECASE)
    if not m:
        log.debug("Cannot parse street from address: %r", address)
        return None

    street = m.group(1).strip().upper()
    log.info("Searching WCAD for address: %r", street)

    try:
        # WCAD uses a WordPress-based search with a GET parameter
        resp = requests.get(
            _WCAD_SEARCH_URL,
            params={"s": street},
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return _parse_wcad_search_results(resp.text)
    except requests.RequestException as exc:
        log.warning("WCAD search request failed: %s", exc)
        return None


def _parse_wcad_search_results(html: str) -> dict | None:
    """Parse WCAD search results page for R Number and assessed values."""
    soup = BeautifulSoup(html, "lxml")

    # Look for a link or table entry with pattern R followed by digits
    r_matches = re.findall(r"R(\d{5,7})", html)
    assessed_values = re.findall(r"\$([\d,]+)", html)

    if not r_matches:
        log.debug("No R Number found in WCAD search results")
        return None

    r_number = "R" + r_matches[0]
    assessed = None
    if assessed_values:
        # Largest value is likely total assessed
        amounts = [int(v.replace(",", "")) for v in assessed_values]
        amounts = [a for a in amounts if a > 1000]
        assessed = max(amounts) if amounts else None

    log.info("WCAD found R Number: %s, assessed: %s", r_number, assessed)
    return {
        "r_number": r_number,
        "assessed_value": assessed,
        "source": "wcad_search",
    }


def _try_fetch_appraisal_pdf(r_number: str, year: int, dest: Path, force: bool) -> bool:
    """
    Try to download the appraisal notice PDF from documents.wcad.org.
    Returns True if downloaded, False if skipped (cached or login redirect).
    """
    if dest.exists() and not force:
        log.info("[cached] WCAD PDF for %s", r_number)
        return True  # cached = success for our purposes

    url = f"https://documents.wcad.org/{year}/{r_number}.pdf"
    log.info("Trying WCAD PDF: %s", url)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "")

        if resp.status_code in (401, 403) or "login" in resp.url.lower():
            # NOTE: WCAD requires authentication to access appraisal notice PDFs.
            # Automated download not possible without credentials.
            # Manual URL: https://www.wcad.org/property-search/ → search by R Number
            log.info(
                "[WCAD PDF not accessible] R=%s — login required. "
                "Manual lookup: https://www.wcad.org/property-search/?s=%s",
                r_number, r_number,
            )
            return False

        if "pdf" in content_type.lower() and resp.status_code == 200:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(resp.content)
            log.info("Saved WCAD PDF: %s", dest)
            return True

        log.debug("WCAD PDF response: status=%s type=%s", resp.status_code, content_type)
        return False
    except requests.RequestException as exc:
        log.warning("WCAD PDF fetch failed for %s: %s", r_number, exc)
        return False


def _fetch_wcad_details(r_number: str) -> dict:
    """Fetch property details directly from the WCAD property page."""
    url = f"https://search.wcad.org/Property-Detail/PropertyQuickRefID/{r_number}"
    log.info("Fetching WCAD property details for %s", r_number)
    details = {}
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
        
        # Regex is often more robust than beautifulsoup for these highly-nested Kendo grids
        # Year Built
        m_year = re.search(r"Year\s*Built[\s\S]*?(\d{4})", html, re.IGNORECASE)
        if m_year:
            details["year_built"] = int(m_year.group(1))
            
        # Square Footage
        # Looking for things like "1,546 Sq. Ft" or "1546 Sq. Ft"
        m_sqft = re.search(r"([\d,]+)\s*Sq\.?\s*Ft", html, re.IGNORECASE)
        if m_sqft:
            try:
                details["sqft"] = int(m_sqft.group(1).replace(",", ""))
            except ValueError:
                pass
                
        # Market Value
        # Often the highest dollar value on the page
        dollar_amounts = re.findall(r"\$([\d,]+)", html)
        if dollar_amounts:
            amounts = [int(v.replace(",", "")) for v in dollar_amounts]
            amounts = [a for a in amounts if a > 1000]
            if amounts:
                details["market_value"] = max(amounts)
                
    except requests.RequestException as exc:
        log.warning("WCAD property detail fetch failed for %s: %s", r_number, exc)
        
    return details
def _run_one(session, prop: Property, force: bool) -> None:
    if not force:
        existing = (
            session.query(StepResult)
            .filter_by(entry_no=prop.entry_no, step_name=STEP_NAME)
            .first()
        )
        if existing:
            log.info("[cached] step2 already done for %s", prop.entry_no)
            return

    address = prop.address
    extracted: dict = {}

    # 1. Try WCAD property search by address
    wcad_data = _search_wcad_by_address(address)
    if wcad_data:
        extracted.update(wcad_data)
        r_number = wcad_data.get("r_number")
        if r_number and not prop.r_number:
            prop.r_number = r_number
            session.add(prop)

    # 2. Try appraisal PDF download and detail fetch
    r_number = prop.r_number or extracted.get("r_number")
    if r_number:
        pdf_dest = workspace_path(
            prop.month, "properties", prop.entry_no, "wcad_appraisal.pdf"
        )
        current_year = datetime.now().year
        # Try current year then prior year
        for yr in [current_year, current_year - 1]:
            ok = _try_fetch_appraisal_pdf(r_number, yr, pdf_dest, force)
            if ok:
                extracted["appraisal_pdf_year"] = yr
                break
                
        # Fetch detailed properties
        details = _fetch_wcad_details(r_number)
        if details:
            extracted.update(details)

    # 3. Persist step_results
    sr = StepResult(
        entry_no=prop.entry_no,
        step_name=STEP_NAME,
        extracted_json=json.dumps(extracted),
    )
    session.add(sr)
    prop.status = "step2_done"
    session.add(prop)
    time.sleep(0.5)  # be polite to WCAD servers


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
        log.info("Running step2 (WCAD) on %d properties", len(props))
        for prop in props:
            _run_one(session, prop, force)
        session.commit()
        log.info("Step 2 (WCAD) complete")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
