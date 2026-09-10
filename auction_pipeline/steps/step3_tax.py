"""Step 3 — Tax delinquency status (manual-assist mode).

tax.wilcotx.gov disallows automated fetching (robots.txt).
This module provides:
  1. run_step() — prints the lookup URL for each property so an operator can check manually
  2. run_manual_entry() — records the operator's manually-entered result

CLI usage:
  python -m auction_pipeline.cli manual-entry --step 3 --entry-no <id> \\
      --status current|delinquent --amount <n>

  python -m auction_pipeline.cli run-step --step 3 --month 2026-09
      (prints all pending URLs for the operator)

Stored result is flagged stale if fetched_at is older than 30 days.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import click

from auction_pipeline import get_county_config
from auction_pipeline.db.models import Property, StepResult
from auction_pipeline.db.session import get_session

log = logging.getLogger(__name__)

STEP_NAME = "step3_tax"
STALE_DAYS = 30


def _tax_url(county_cfg: dict, r_number: str) -> str:
    return county_cfg["tax_detail_url"].format(r_number=r_number)


def _is_stale(fetched_at: datetime | None) -> bool:
    if fetched_at is None:
        return True
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=STALE_DAYS)
    # Handle naive datetimes (SQLite stores without tz)
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return fetched_at < cutoff


def run_step(
    month: str,
    county: str = "williamson",
    entry_no: str | None = None,
    force: bool = False,
) -> None:
    """Print tax lookup URLs for all properties missing step3 results."""
    county_cfg = get_county_config(county)
    session = get_session()
    try:
        query = session.query(Property).filter_by(month=month, county=county)
        if entry_no:
            query = query.filter_by(entry_no=entry_no)
        props = query.all()

        pending = []
        for prop in props:
            existing = (
                session.query(StepResult)
                .filter_by(entry_no=prop.entry_no, step_name=STEP_NAME)
                .first()
            )
            if existing and not force:
                if not _is_stale(existing.fetched_at):
                    log.info("[cached] step3 tax already done for %s", prop.entry_no)
                    continue
                else:
                    log.info("[stale] step3 tax result >%d days old for %s", STALE_DAYS, prop.entry_no)

            if not prop.r_number:
                log.warning("No R Number for %s — cannot generate tax URL", prop.entry_no)
                continue

            url = _tax_url(county_cfg, prop.r_number)
            pending.append((prop.entry_no, prop.r_number, url))

        if pending:
            click.echo("\n=== Step 3: Tax Delinquency — Manual Lookup Required ===")
            click.echo("For each property below, visit the URL and record the status:\n")
            for eno, r_num, url in pending:
                click.echo(f"  Entry: {eno}  (R Number: {r_num})")
                click.echo(f"  URL:   {url}")
                click.echo(f"  Command: python -m auction_pipeline.cli manual-entry "
                           f"--step 3 --entry-no {eno} --status current|delinquent --amount <n>\n")
        else:
            click.echo("Step 3: All tax status results are current (no action needed).")
    finally:
        session.close()


def run_manual_entry(
    entry_no: str,
    status: str | None = None,
    amount: float | None = None,
) -> None:
    """Record a manually-entered tax delinquency result."""
    if status not in ("current", "delinquent"):
        click.echo(
            f"Error: --status must be 'current' or 'delinquent', got {status!r}",
            err=True,
        )
        return

    session = get_session()
    try:
        prop = session.get(Property, entry_no)
        if prop is None:
            click.echo(f"Error: No property found with entry_no={entry_no!r}", err=True)
            return

        # Upsert the step_results row
        sr = (
            session.query(StepResult)
            .filter_by(entry_no=entry_no, step_name=STEP_NAME)
            .first()
        )
        if sr is None:
            sr = StepResult(entry_no=entry_no, step_name=STEP_NAME)

        payload = {
            "tax_status": status,
            "delinquent_amount": amount,
            "manually_entered": True,
            "entered_at": datetime.now(tz=timezone.utc).isoformat(),
        }
        sr.extracted_json = json.dumps(payload)
        sr.fetched_at = datetime.now(tz=timezone.utc)
        session.add(sr)
        session.commit()

        click.echo(
            f"✓ Recorded tax status for {entry_no}: "
            f"status={status}, amount={amount}"
        )
        log.info(
            "Tax status recorded for %s: status=%s, amount=%s",
            entry_no, status, amount,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
