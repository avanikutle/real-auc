"""Step 0 — Monthly trustee-sale notice downloader.

Fetches the Williamson County trustee-sales file listing for a given month,
enumerates every PDF link, and downloads each file into:

    workspace/{YYYY-MM}/properties/{entry_no}/trustee_notice.pdf

Entry numbers are derived from the filename so they are stable across runs:
    {YYYY-MM}_{MM-DD-YYYY}_File_{NNN}
    e.g.  2026-09_07-07-2026_File_006

The File_IDX (alphabetical index) is stored separately as:
    workspace/{YYYY-MM}/File_IDX.pdf

Re-running is fully idempotent:
- If the destination file already exists → log [cached] and skip.
- Pass --force to re-download everything.
"""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from auction_pipeline import get_county_config, workspace_path
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session

log = logging.getLogger(__name__)

# Month number → name mapping
_MONTH_NAMES = {
    "01": "January",  "02": "February", "03": "March",
    "04": "April",    "05": "May",       "06": "June",
    "07": "July",     "08": "August",    "09": "September",
    "10": "October",  "11": "November",  "12": "December",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _month_name(month: str) -> str:
    """Convert '2026-09' → 'September'."""
    parts = month.split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid month format: {month!r}. Expected YYYY-MM.")
    return _MONTH_NAMES[parts[1]]


def _build_listing_url(county_cfg: dict, month: str) -> str:
    month_name = _month_name(month)
    base = county_cfg["trustee_sales_base_url"]
    return base.format(month_name=month_name)


def _fetch_file_listing(listing_url: str) -> list[dict]:
    """
    Fetch the files.aspx page and return a list of:
        {"href": "07-07-2026_File_006.pdf", "label": "File_006", "size": "126 Kb"}
    """
    log.info("Fetching listing from %s", listing_url)
    resp = requests.get(listing_url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    files = []
    for a_tag in soup.find_all("a", href=re.compile(r"\.pdf$", re.I)):
        href = a_tag["href"]
        label = a_tag.get_text(strip=True)
        # Try to get size from next sibling td
        size = ""
        tr = a_tag.find_parent("tr")
        if tr:
            tds = tr.find_all("td")
            if len(tds) >= 2:
                size = tds[1].get_text(strip=True)
        files.append({"href": href, "label": label, "size": size})
    log.info("Found %d PDF links", len(files))
    return files


def _make_entry_no(month: str, filename: str) -> str:
    """
    Derive a stable entry number from the filename.
    e.g. month='2026-09', filename='07-07-2026_File_006.pdf'
         → '2026-09_07-07-2026_File_006'
    """
    stem = Path(filename).stem  # strip .pdf
    return f"{month}_{stem}"


def _download_pdf(url: str, dest: Path, force: bool) -> bool:
    """
    Download a PDF to dest.
    Returns True if downloaded, False if skipped (cached).
    """
    if dest.exists() and not force:
        log.info("[cached] %s", dest)
        return False

    log.info("Downloading %s → %s", url, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, headers=_HEADERS, timeout=60, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=65536):
            fh.write(chunk)
    log.info("Saved %s (%.1f KB)", dest.name, dest.stat().st_size / 1024)
    return True


def _upsert_property(session, entry_no: str, month: str, county: str,
                     source_file_name: str, source_url: str) -> None:
    """Insert a properties row if one doesn't already exist."""
    existing = session.get(Property, entry_no)
    if existing is None:
        prop = Property(
            entry_no=entry_no,
            month=month,
            county=county,
            source_file_name=source_file_name,
            status="pending",
        )
        session.add(prop)
        log.info("Inserted property row: %s", entry_no)
    else:
        log.debug("Property row already exists: %s", entry_no)


def run_download(month: str, county: str = "williamson", force: bool = False) -> None:
    county_cfg = get_county_config(county)
    listing_url = _build_listing_url(county_cfg, month)
    base_url = listing_url.rsplit("/", 1)[0] + "/"  # e.g. .../September/

    files = _fetch_file_listing(listing_url)
    if not files:
        log.warning("No PDF files found at %s", listing_url)
        return

    session = get_session()
    try:
        downloaded = 0
        cached = 0

        for f in files:
            filename = Path(f["href"]).name
            pdf_url = base_url + filename

            # File_IDX goes to the month root, not a per-property subfolder
            if "IDX" in filename.upper() or "IDX" in f["label"].upper():
                dest = workspace_path(month, "File_IDX.pdf")
                result = _download_pdf(pdf_url, dest, force)
                if result:
                    downloaded += 1
                else:
                    cached += 1
                continue

            # Regular notice file → per-property folder
            entry_no = _make_entry_no(month, filename)
            dest = workspace_path(
                month, "properties", entry_no, "trustee_notice.pdf"
            )
            result = _download_pdf(pdf_url, dest, force)
            if result:
                downloaded += 1
            else:
                cached += 1

            # Always upsert the property row (idempotent)
            _upsert_property(
                session,
                entry_no=entry_no,
                month=month,
                county=county,
                source_file_name=filename,
                source_url=pdf_url,
            )
            # Be polite — brief pause only when actually downloading
            if result:
                time.sleep(0.3)

        session.commit()
        log.info(
            "Download complete: %d downloaded, %d cached (total %d files)",
            downloaded, cached, downloaded + cached,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
