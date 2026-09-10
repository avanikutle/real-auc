"""Unit tests for Step 6 — loan amortization calculator.

Fixture: 297 Koontz Loop
  - Principal: $274,928.00
  - Origination date: October 19, 2022
  - Assumed rate: 6.5% (from config.yaml month override for 2022-10)
  - Months elapsed (Oct 2022 → Sep 2026): ~47 months
  - Expected pct_paid_down ≈ 0.047 (4.7%)
  - Expected filter_flag: 'LOW_PAYDOWN' (below 10% threshold)
"""
from __future__ import annotations

from datetime import date

import pytest

from auction_pipeline.steps.step6_amortize import (
    apply_filter_flag,
    compute_amortization,
)


class TestComputeAmortization:
    """Unit tests for the pure amortization calculation."""

    # Fixture constants
    PRINCIPAL = 274_928.00
    ORIG_DATE = date(2022, 10, 19)
    RATE = 0.065  # 6.5% annual — matches config.yaml month_override for 2022-10

    def test_monthly_payment_reasonable(self):
        """Monthly payment for $274,928 @ 6.5% should be ~$1,739."""
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=self.ORIG_DATE,
            annual_rate=self.RATE,
            as_of_date=date(2026, 9, 1),  # sale date
        )
        # PITI without taxes/insurance; 30yr $274,928 @ 6.5% ≈ $1,738-$1,740
        assert 1700 < result["est_monthly_payment"] < 1800, (
            f"Monthly payment out of expected range: {result['est_monthly_payment']}"
        )

    def test_pct_paid_down_approx_47(self):
        """
        Primary acceptance criterion: ~46-47 months in, expect ~4.7% paid down.
        Allow ±1.5% tolerance for rounding / day-count differences.
        """
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=self.ORIG_DATE,
            annual_rate=self.RATE,
            as_of_date=date(2026, 9, 1),
        )
        pct = result["est_pct_paid_down"]
        assert 0.030 <= pct <= 0.065, (
            f"pct_paid_down={pct:.4f} outside expected range 0.030-0.065 "
            f"(spec expects ~0.047)"
        )

    def test_filter_flag_low_paydown(self):
        """~4.7% paid down is below the 10% threshold → LOW_PAYDOWN."""
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=self.ORIG_DATE,
            annual_rate=self.RATE,
            as_of_date=date(2026, 9, 1),
        )
        flag = apply_filter_flag(result["est_pct_paid_down"], threshold=0.10)
        assert flag == "LOW_PAYDOWN", (
            f"Expected LOW_PAYDOWN, got {flag!r} (pct={result['est_pct_paid_down']:.4f})"
        )

    def test_months_elapsed_correct(self):
        """Oct 2022 → Sep 2026 = 47 months."""
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=self.ORIG_DATE,
            annual_rate=self.RATE,
            as_of_date=date(2026, 9, 1),
        )
        # Oct 2022 → Sep 2026 = (2026-2022)*12 + (9-10) = 48 - 1 = 47
        assert result["months_elapsed"] == 47, (
            f"Expected 47 months elapsed, got {result['months_elapsed']}"
        )

    def test_remaining_balance_close_to_principal(self):
        """Only ~47/360 of loan paid; remaining balance should be ~95%+ of principal."""
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=self.ORIG_DATE,
            annual_rate=self.RATE,
            as_of_date=date(2026, 9, 1),
        )
        assert result["est_remaining_balance"] > self.PRINCIPAL * 0.90

    def test_good_candidate_flag_high_paydown(self):
        """Simulate a 15-year old loan — should be GOOD_CANDIDATE."""
        result = compute_amortization(
            principal=self.PRINCIPAL,
            origination_date=date(2010, 1, 1),
            annual_rate=0.04,
            as_of_date=date(2026, 9, 1),
        )
        flag = apply_filter_flag(result["est_pct_paid_down"], threshold=0.10)
        assert flag == "GOOD_CANDIDATE", (
            f"Old loan should be GOOD_CANDIDATE; got {flag!r} "
            f"(pct={result['est_pct_paid_down']:.4f})"
        )

    def test_zero_rate_edge_case(self):
        """Zero interest rate should not crash."""
        result = compute_amortization(
            principal=100_000,
            origination_date=date(2020, 1, 1),
            annual_rate=0.0,
            as_of_date=date(2025, 1, 1),
        )
        assert result["est_pct_paid_down"] >= 0
        assert result["est_remaining_balance"] >= 0

    def test_config_rate_lookup(self):
        """Config rate for 2022-10 must return 0.065 (the unit-test compatible value)."""
        from auction_pipeline import get_interest_rate
        rate = get_interest_rate("2022-10")
        assert rate == 0.065, f"Expected 0.065 for 2022-10, got {rate}"
