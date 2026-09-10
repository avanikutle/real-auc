"""Step 6 — Loan amortization estimate (pure calculation, no external dependencies).

Standard fixed-rate amortization formula:
    r = annual_rate / 12
    n = 360  (30-year loan)
    M = P * r * (1+r)^n / ((1+r)^n - 1)  (monthly payment)
    balance(k) = P*(1+r)^k - M*((1+r)^k - 1)/r
    principal_paid = P - balance(k)
    pct_paid_down = principal_paid / P

Inputs:
    - original_loan_amount (P)
    - loan_origination_date → months_elapsed (k)
    - assumed annual rate from config.yaml rate table by origination month

Output:
    - Writes to loan_estimates table
    - Sets filter_flag = 'LOW_PAYDOWN' if pct_paid_down < threshold (default 0.10)
                       = 'GOOD_CANDIDATE' otherwise

Idempotent: skips if loan_estimates row exists (unless --force).
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from auction_pipeline import get_amortization_config, get_interest_rate
from auction_pipeline.db.models import LoanEstimate, Property
from auction_pipeline.db.session import get_session

log = logging.getLogger(__name__)


def compute_amortization(
    principal: float,
    origination_date: date,
    annual_rate: float,
    as_of_date: date | None = None,
    loan_term_years: int = 30,
) -> dict:
    """
    Compute amortization schedule output.

    Args:
        principal: Original loan amount (P)
        origination_date: When the loan was originated
        annual_rate: Annual interest rate as decimal (e.g. 0.065 for 6.5%)
        as_of_date: Date to compute balance as of (defaults to today)
        loan_term_years: Loan term in years (default 30)

    Returns:
        dict with amortization fields
    """
    if as_of_date is None:
        as_of_date = date.today()

    r = annual_rate / 12
    n = loan_term_years * 12

    # Months elapsed (k) — computed before branching so both paths have it
    months_elapsed = (
        (as_of_date.year - origination_date.year) * 12
        + (as_of_date.month - origination_date.month)
    )
    months_elapsed = max(0, months_elapsed)

    # Monthly payment and remaining balance
    if r == 0:
        monthly_payment = principal / n
        balance = max(0.0, principal - monthly_payment * months_elapsed)
    else:
        monthly_payment = principal * r * (1 + r) ** n / ((1 + r) ** n - 1)

        # Remaining balance after k payments (standard formula)
        balance = (
            principal * (1 + r) ** months_elapsed
            - monthly_payment * ((1 + r) ** months_elapsed - 1) / r
        )
        balance = max(0.0, balance)

    principal_paid = principal - balance
    interest_paid = monthly_payment * months_elapsed - principal_paid
    pct_paid_down = principal_paid / principal if principal > 0 else 0.0

    return {
        "months_elapsed": months_elapsed,
        "assumed_rate": annual_rate,
        "est_monthly_payment": round(monthly_payment, 2),
        "est_principal_paid": round(principal_paid, 2),
        "est_interest_paid": round(max(0.0, interest_paid), 2),
        "est_remaining_balance": round(balance, 2),
        "est_pct_paid_down": round(pct_paid_down, 6),
    }


def apply_filter_flag(pct_paid_down: float, threshold: float) -> str:
    return "GOOD_CANDIDATE" if pct_paid_down >= threshold else "LOW_PAYDOWN"


def _run_one(session, prop: Property, force: bool, threshold: float) -> None:
    # Idempotency check
    if not force:
        existing = session.get(LoanEstimate, prop.entry_no)
        if existing:
            log.info("[cached] step6 amortization already done for %s", prop.entry_no)
            return

    if not prop.original_loan_amount or not prop.loan_origination_date:
        log.warning(
            "Missing loan data for %s (amount=%s, date=%s) — skipping",
            prop.entry_no, prop.original_loan_amount, prop.loan_origination_date,
        )
        return

    # Get rate from config.yaml by origination month
    orig_month = prop.loan_origination_date.strftime("%Y-%m")
    annual_rate = get_interest_rate(orig_month)

    result = compute_amortization(
        principal=prop.original_loan_amount,
        origination_date=prop.loan_origination_date,
        annual_rate=annual_rate,
    )

    flag = apply_filter_flag(result["est_pct_paid_down"], threshold)

    est = session.get(LoanEstimate, prop.entry_no)
    if est is None:
        est = LoanEstimate(entry_no=prop.entry_no)

    est.months_elapsed = result["months_elapsed"]
    est.assumed_rate = result["assumed_rate"]
    est.est_monthly_payment = result["est_monthly_payment"]
    est.est_principal_paid = result["est_principal_paid"]
    est.est_interest_paid = result["est_interest_paid"]
    est.est_remaining_balance = result["est_remaining_balance"]
    est.est_pct_paid_down = result["est_pct_paid_down"]
    est.filter_flag = flag
    session.add(est)

    log.info(
        "Amortization for %s: rate=%.1f%%, elapsed=%d mo, paid_down=%.1f%%, flag=%s",
        prop.entry_no,
        annual_rate * 100,
        result["months_elapsed"],
        result["est_pct_paid_down"] * 100,
        flag,
    )


def run_step(
    month: str,
    county: str = "williamson",
    entry_no: str | None = None,
    force: bool = False,
) -> None:
    amort_cfg = get_amortization_config()
    threshold = float(amort_cfg.get("paydown_threshold", 0.10))

    session = get_session()
    try:
        query = session.query(Property).filter_by(month=month, county=county)
        if entry_no:
            query = query.filter_by(entry_no=entry_no)
        props = query.all()
        log.info("Running step6 (amortization) on %d properties", len(props))
        for prop in props:
            _run_one(session, prop, force=force, threshold=threshold)
        session.commit()
        log.info("Step 6 (amortization) complete")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
