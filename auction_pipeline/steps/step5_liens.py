"""Step 5 — County records lien search.

Searches williamson.tx.publicsearch.us for instruments recorded after
loan_origination_date by owner name and legal description.

If automated access proves infeasible (JS SPA, anti-bot), falls back to
the same manual-assist pattern as Step 3:
  - run_step() prints the direct search URL for each property
  - run_manual_entry() records manually-entered lien data

Results stored as JSON list of {instrument_type, recorded_date, parties}
in step_results (step_name=step5_liens).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime

import click
import requests
from bs4 import BeautifulSoup

from auction_pipeline import get_county_config, workspace_path
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session

log = logging.getLogger(__name__)

STEP_NAME = "step5_liens"

_PORTAL_BASE = "https://williamson.tx.publicsearch.us"
_SEARCH_URL = f"{_PORTAL_BASE}/results"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _search_liens_automated(
    owner_name: str,
    legal_description: str,
    after_date: str,
) -> list[dict] | None:
    """
    Attempt automated lien search via Tyler Technologies portal.
    Returns list of {instrument_type, recorded_date, parties} or None if failed.
    """
    if not owner_name:
        return None

    # Extract last name from owner_name
    parts = owner_name.strip().split()
    last_name = parts[-1] if parts else owner_name

    try:
        session = requests.Session()
        session.headers.update(_HEADERS)
        # Initialize session
        session.get(_PORTAL_BASE, timeout=15)

        resp = session.get(
            _SEARCH_URL,
            params={
                "department": "RP",
                "party1LastName": last_name,
                "recordedDateRange": f"{after_date}:{datetime.now().strftime('%m/%d/%Y')}",
                "page": "1",
                "pageSize": "50",
                "searchType": "fullSearch",
            },
            timeout=20,
        )

        content_type = resp.headers.get("Content-Type", "")
        liens = []

        if "application/json" in content_type:
            data = resp.json()
            results = data.get("results", data.get("items", []))
            for item in results:
                liens.append({
                    "instrument_type": item.get("docType") or item.get("instrumentType", ""),
                    "recorded_date": item.get("recordedDate") or item.get("instrumentDate", ""),
                    "parties": (item.get("grantors", []) or []) + (item.get("grantees", []) or []),
                    "instrument_number": item.get("docNumber") or item.get("instrumentNumber", ""),
                })
            log.info("Portal returned %d lien results for %s", len(liens), last_name)
            return liens if liens else None

        # HTML response — parse links
        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.find_all("tr", class_=re.compile(r"result|doc", re.I))
        if rows:
            for row in rows:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 3:
                    liens.append({
                        "instrument_type": cells[0] if cells else "",
                        "recorded_date": cells[1] if len(cells) > 1 else "",
                        "parties": cells[2:],
                        "instrument_number": "",
                    })
            return liens

    except Exception as exc:
        log.debug("Automated lien search failed: %s", exc)

    return None


def _manual_url(entry_no: str, owner_name: str) -> str:
    last = owner_name.strip().split()[-1] if owner_name else ""
    return (
        f"{_PORTAL_BASE}/results?department=RP"
        f"&party1LastName={last}&searchType=fullSearch"
    )


def _run_one(session, prop: Property, force: bool) -> None:
    if not force:
        existing = (
            session.query(StepResult)
            .filter_by(entry_no=prop.entry_no, step_name=STEP_NAME)
            .first()
        )
        if existing:
            log.info("[cached] step5 already done for %s", prop.entry_no)
            return

    after_date = ""
    if prop.loan_origination_date:
        after_date = prop.loan_origination_date.strftime("%m/%d/%Y")

    liens = _search_liens_automated(
        owner_name=prop.owner_full_name or "",
        legal_description=prop.legal_description or "",
        after_date=after_date,
    )

    extracted: dict
    if liens is not None:
        extracted = {
            "liens": liens,
            "lien_count": len(liens),
            "source": "automated",
        }
        log.info("Found %d liens for %s", len(liens), prop.entry_no)
    else:
        # Automated search failed — fall back to manual-assist
        manual_url = _manual_url(prop.entry_no, prop.owner_full_name or "")
        extracted = {
            "liens": [],
            "lien_count": None,
            "source": "manual_assist_needed",
            "manual_lookup_url": manual_url,
            # NOTE: Automated lien search via williamson.tx.publicsearch.us failed.
            # The portal likely requires JS rendering. To complete this step manually:
            # 1. Visit the URL below
            # 2. Search by party last name and filter by date range after loan origination
            # 3. Use: python -m auction_pipeline.cli manual-entry --step 5 --entry-no {entry_no}
        }
        log.info(
            "[manual assist needed] step5 lien search for %s — URL: %s",
            prop.entry_no, manual_url,
        )

    sr = StepResult(
        entry_no=prop.entry_no,
        step_name=STEP_NAME,
        extracted_json=json.dumps(extracted),
    )
    session.add(sr)
    time.sleep(0.3)


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
        log.info("Running step5 (liens) on %d properties", len(props))
        for prop in props:
            _run_one(session, prop, force=force)

        # Print manual-assist summary
        pending_manual = (
            session.query(StepResult)
            .filter_by(step_name=STEP_NAME)
            .filter(StepResult.extracted_json.like('%manual_assist_needed%'))
            .all()
        )
        if pending_manual:
            click.echo(
                f"\n=== Step 5: {len(pending_manual)} properties need manual lien search ==="
            )
            for sr in pending_manual:
                data = json.loads(sr.extracted_json or "{}")
                click.echo(f"  {sr.entry_no}: {data.get('manual_lookup_url', '')}")

        session.commit()
        log.info("Step 5 (liens) complete")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def run_manual_entry(entry_no: str) -> None:
    """Interactive manual lien entry for a specific property."""
    session = get_session()
    try:
        prop = session.get(Property, entry_no)
        if prop is None:
            click.echo(f"Error: No property found with entry_no={entry_no!r}", err=True)
            return

        click.echo(f"\nManual lien entry for {entry_no}")
        click.echo(f"Owner: {prop.owner_full_name}")
        if prop.loan_origination_date:
            click.echo(f"Search for instruments AFTER: {prop.loan_origination_date}")
        click.echo(f"\nSearch URL: {_manual_url(entry_no, prop.owner_full_name or '')}")
        click.echo("\nEnter liens (one per line, format: TYPE|DATE|PARTIES, blank to finish):")

        liens = []
        while True:
            line = input("> ").strip()
            if not line:
                break
            parts = line.split("|")
            liens.append({
                "instrument_type": parts[0].strip() if len(parts) > 0 else "",
                "recorded_date": parts[1].strip() if len(parts) > 1 else "",
                "parties": parts[2].strip() if len(parts) > 2 else "",
            })

        # Upsert step_results
        sr = (
            session.query(StepResult)
            .filter_by(entry_no=entry_no, step_name=STEP_NAME)
            .first()
        )
        if sr is None:
            sr = StepResult(entry_no=entry_no, step_name=STEP_NAME)

        sr.extracted_json = json.dumps({
            "liens": liens,
            "lien_count": len(liens),
            "source": "manual",
            "entered_at": datetime.utcnow().isoformat(),
        })
        sr.fetched_at = datetime.utcnow()
        session.add(sr)
        session.commit()
        click.echo(f"✓ Recorded {len(liens)} liens for {entry_no}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
