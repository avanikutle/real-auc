"""SQLAlchemy ORM models for auction_pipeline.

All column types use only cross-DB-compatible SQLAlchemy types:
    String, Text, Integer, Float, Boolean, Date, DateTime

No SQLite-specific constructs — switching to PostgreSQL is a
connection-string-only change.
"""
from __future__ import annotations

from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Property(Base):
    """One row per foreclosure listing discovered in a monthly batch."""

    __tablename__ = "properties"

    entry_no: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_no: Mapped[str | None] = mapped_column(String(64))
    owner_full_name: Mapped[str | None] = mapped_column(String(512))
    address: Mapped[str | None] = mapped_column(String(512))
    legal_description: Mapped[str | None] = mapped_column(Text)
    r_number: Mapped[str | None] = mapped_column(String(32))
    instrument_number: Mapped[str | None] = mapped_column(String(64))
    sale_date: Mapped[date | None] = mapped_column(Date)
    original_loan_amount: Mapped[float | None] = mapped_column(Float)
    loan_origination_date: Mapped[date | None] = mapped_column(Date)
    loan_type: Mapped[str | None] = mapped_column(String(64))
    lender: Mapped[str | None] = mapped_column(Text)
    servicer: Mapped[str | None] = mapped_column(Text)
    trustee: Mapped[str | None] = mapped_column(Text)
    county: Mapped[str | None] = mapped_column(String(64))
    month: Mapped[str | None] = mapped_column(String(7))  # YYYY-MM
    source_file_name: Mapped[str | None] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    # DoT-specific flags (populated by step 4)
    is_purchase_money: Mapped[bool | None] = mapped_column(Boolean)
    has_hoa_rider: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationships
    step_results: Mapped[list["StepResult"]] = relationship(
        back_populates="property", cascade="all, delete-orphan"
    )
    loan_estimate: Mapped["LoanEstimate | None"] = relationship(
        back_populates="property", cascade="all, delete-orphan", uselist=False
    )


class StepResult(Base):
    """Stores the raw extracted data from each pipeline step."""

    __tablename__ = "step_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_no: Mapped[str] = mapped_column(
        String(64), ForeignKey("properties.entry_no"), nullable=False
    )
    step_name: Mapped[str] = mapped_column(String(64))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_file_path: Mapped[str | None] = mapped_column(Text)
    extracted_json: Mapped[str | None] = mapped_column(Text)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationship
    property: Mapped["Property"] = relationship(back_populates="step_results")


class LoanEstimate(Base):
    """Amortization calculation output for one property."""

    __tablename__ = "loan_estimates"

    entry_no: Mapped[str] = mapped_column(
        String(64), ForeignKey("properties.entry_no"), primary_key=True
    )
    months_elapsed: Mapped[int | None] = mapped_column(Integer)
    assumed_rate: Mapped[float | None] = mapped_column(Float)
    est_monthly_payment: Mapped[float | None] = mapped_column(Float)
    est_principal_paid: Mapped[float | None] = mapped_column(Float)
    est_interest_paid: Mapped[float | None] = mapped_column(Float)
    est_remaining_balance: Mapped[float | None] = mapped_column(Float)
    est_pct_paid_down: Mapped[float | None] = mapped_column(Float)
    filter_flag: Mapped[str | None] = mapped_column(String(32))

    # Relationship
    property: Mapped["Property"] = relationship(back_populates="loan_estimate")
