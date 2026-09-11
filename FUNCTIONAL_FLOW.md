# RK-Reality — Auction Pipeline: Functional Flow

> A comprehensive guide to the Texas Trustee Sale (Foreclosure Auction) process and how the **real-auc** pipeline automates due diligence for each property.

---

## Table of Contents

1. [Texas Trustee Sale — Background](#1-texas-trustee-sale--background)
2. [Why Due Diligence Matters](#2-why-due-diligence-matters)
3. [High-Level System Architecture](#3-high-level-system-architecture)
4. [Pipeline Flow — Step by Step](#4-pipeline-flow--step-by-step)
5. [RK-Reality Web Dashboard](#5-rk-reality-web-dashboard)
6. [Database Schema](#6-database-schema)
7. [Data Sources Used](#7-data-sources-used)
8. [Key Engineering Decisions](#8-key-engineering-decisions)

---

## 1. Texas Trustee Sale — Background

In Texas, when a homeowner defaults on a mortgage, the lender can foreclose **non-judicially** through a **Trustee Sale** (also called a foreclosure auction). The process works as follows:

1. **Notice of Trustee Sale**: The lender or their representative (Trustee) files a formal notice of intent to sell the property at a public auction. This notice is publicly available and lists details like the property address, the owner name, the lender, and the scheduled sale date.
2. **Posting Period**: Texas law requires at least 21 days notice before the sale. Notices are posted at the county courthouse and published online.
3. **Auction Date**: On the **first Tuesday of every month**, properties are auctioned off on the steps of the county courthouse. The highest bidder above the minimum bid (typically the outstanding loan balance) wins the property.
4. **No Warranties**: Properties are sold "as-is." The winning bidder takes on **all risks** — including outstanding taxes, liens, and property condition.

> **Investment Opportunity**: If a bidder can purchase a property below market value (because the loan was largely paid down and equity built up), they can profit significantly. This is the core use case for this pipeline.

---

## 2. Why Due Diligence Matters

Before bidding at auction, an investor needs to know:

| Question | Why It Matters |
|---|---|
| **Who owns the property?** | Confirms you are buying the right asset |
| **What is the assessed value?** | Market value reference from the appraisal district |
| **Are there unpaid property taxes?** | Taxes survive a foreclosure — you inherit them |
| **How much of the loan is paid down?** | Higher equity = more room to profit |
| **Are there other liens (IRS, HOA, contractors)?** | Certain liens survive foreclosure and become your problem |
| **What type of loan is it?** | FHA/VA loans have special rules; purchase-money loans limit deficiency claims |

Manually doing this research for dozens of properties every month is extremely time-consuming. This pipeline **automates all of it**.

---

## 3. High-Level System Architecture

```
  React UI (Port 5173)
       |
       v
  FastAPI Backend (Port 8000)
  RK-Reality/backend/main.py
       |
       v
  PostgreSQL Database
  Host: localhost:5432
  DB:   fno_oms
  Schema: rkreality
       |
       v
  auction_pipeline (Python)
  Steps 0-7 (CLI or via UI)
```

**Logs are written to:**
- `logs/backend/api.log` — FastAPI/Uvicorn server logs
- `logs/backend/pipeline.log` — Python pipeline step execution logs
- `logs/frontend/react.log` — Vite React development server logs

---

## 4. Pipeline Flow — Step by Step

### Step 0: Document Discovery & Download

**File:** `auction_pipeline/steps/step0_download.py`

**What it does:**
- Connects to the Williamson County Clerk trustee sales portal.
- Scrapes the index page to find all `.pdf` notice files for the requested month.
- Downloads each PDF file into the local workspace: `workspace/{YYYY-MM}/properties/{entry_no}/trustee_notice.pdf`

**Output:** A raw PDF file on disk for each foreclosure notice filed that month.

---

### Step 1: Notice Parsing & OCR

**File:** `auction_pipeline/steps/step1_parse_notice.py`

**What it does:**
- Opens each downloaded PDF using `pdfplumber` for text-based PDFs.
- For scanned/image PDFs, converts to image via `pdf2image` then runs **Tesseract OCR** to extract text.
- Applies a multi-pattern regex extraction engine to parse:

| Field | Example |
|---|---|
| `owner_full_name` | `JOHN SMITH AND MARY SMITH` |
| `lender` | `ROCKET MORTGAGE, LLC` |
| `servicer` | `LOANCARE, LLC` |
| `trustee` | `SUBSTITUTE TRUSTEE SERVICES` |
| `address` | `123 OAK ST, ROUND ROCK, TX 78664` |
| `sale_date` | `2026-09-01` |
| `original_loan_amount` | `$325,000.00` |
| `instrument_number` | `2018-xxx-xxxxxx` |
| `loan_origination_date` | `2018-05-15` |

**Engineering highlights:**
- Handles **3 distinct notice formats** used by different trustees in Williamson County.
- `_clean_name()` / `_clean_company()` utilities strip OCR noise and limit field length.
- Company name extraction stops at address indicators (e.g., "whose address", "c/o").

---

### Step 2: WCAD Property Lookup

**File:** `auction_pipeline/steps/step2_wcad.py`
**External Source:** `https://search.wcad.org` (Williamson Central Appraisal District)

**What it does:**
- Searches the WCAD property search portal using **Playwright** (headless Chromium browser).
- Extracts the **R-Number** (e.g., `R378555`) — WCAD's unique property identifier.
- Downloads the WCAD Appraisal Notice PDF for the assessed value.
- Fetches the property detail page to extract assessed market value, owner name, and legal description.

**Engineering highlights:**
- **Two-step address fallback**: If full street address fails (e.g., `CONWAY SPGS CT` not found), retries with just house number + first word (e.g., `17060 CONWAY`).
- Properties outside Williamson County will not return results — expected behavior.

---

### Step 3: Tax Status Check

**File:** `auction_pipeline/steps/step3_tax.py`
**External Source:** `https://tax.wilcotx.gov`

**What it does:**
- `tax.wilcotx.gov` disallows automated scraping (bot detection + robots.txt).
- Operates in **manual-assist mode**: generates the direct lookup URL per property and presents it to the operator.
- Operator checks the page and records the result: `current` or `delinquent` (with amount owed).
- Results older than **30 days** are flagged stale for re-verification.

---

### Step 4: Deed of Trust Retrieval

**File:** `auction_pipeline/steps/step4_dot.py`
**External Source:** `https://williamson.tx.publicsearch.us`

**What it does:**
- Uses the `instrument_number` to look up the original Deed of Trust in the county records portal.
- Performs a session-based HTTP flow: gets cookies, accepts disclaimer, searches by instrument number, downloads PDF.
- Parses the DoT PDF for:

| Field | Description |
|---|---|
| `loan_type` | FHA, Conventional, VA, or USDA |
| `origination_date` | Date the original loan was made |
| `maturity_date` | Loan payoff date (typically 30 years out) |
| `is_purchase_money` | Section 27 checkbox — limits lender deficiency claims |
| `has_hoa_rider` | PUD/HOA rider attachment |

---

### Step 5: Lien Check

**File:** `auction_pipeline/steps/step5_liens.py`

**What it does:**
- Checks for other liens filed against the property (HOA liens, IRS/federal tax liens, mechanic liens, junior mortgages).
- HOA and IRS liens can **survive** a non-judicial foreclosure and transfer to the new owner.
- Junior mortgage liens are typically wiped out by the foreclosure sale.
- Operates in manual-assist or semi-automated mode.

---

### Step 6: Amortization & Financial Analysis

**File:** `auction_pipeline/steps/step6_amortize.py`

**What it does:**
- Uses the original loan amount (P), origination date, and historical interest rates from `config.yaml`.
- Standard fixed-rate amortization formula:

```
Monthly Rate (r) = annual_rate / 12
Monthly Payment (M) = P x r x (1+r)^360 / ((1+r)^360 - 1)
Balance at month k = P x (1+r)^k - M x ((1+r)^k - 1) / r
Principal Paid = P - Balance(k)
Pct Paid Down  = Principal Paid / P
```

- Applies filter flags:
  - `GOOD_CANDIDATE` — 10%+ of principal paid down (configurable threshold)
  - `LOW_PAYDOWN` — less than 10% paid down (little equity, less opportunity)

---

### Step 7: Export

**File:** `auction_pipeline/steps/step7_export.py`

**What it does:**
- Queries all properties joined with loan estimates and step results.
- Exports to **Excel (.xlsx)** and/or **CSV** for review and sharing.
- The web dashboard also provides live Excel/CSV download endpoints.

---

## 5. RK-Reality Web Dashboard

### Frontend (React + Vite) — `RK-Reality/frontend/`
- **Dashboard Page** (`/`): All properties for the selected month in a filterable live data table.
- **Property Detail Page** (`/property/:entryNo`): Full drill-down for a single property — all fields, WCAD data, loan estimate, and step audit trail.
- **Admin Page** (`/admin`): Select a month and trigger each pipeline step via UI buttons. Live scrolling log window shows execution output in real time.

### Backend (FastAPI + SQLAlchemy) — `RK-Reality/backend/main.py`

Key API endpoints at `http://localhost:8000`:

| Endpoint | Description |
|---|---|
| `GET /api/properties` | List all properties, filterable by month |
| `GET /api/properties/{entry_no}` | Single property detail |
| `POST /api/pipeline/run` | Trigger a pipeline step in background |
| `GET /api/pipeline/logs/{step}_{month}` | Stream live step execution logs |
| `GET /api/export/excel` | Download Excel report |
| `GET /api/export/csv` | Download CSV report |

---

## 6. Database Schema

**Database:** PostgreSQL (`fno_oms`) | **Schema:** `rkreality`

### `properties` — Core property record

| Column | Type | Description |
|---|---|---|
| `entry_no` | VARCHAR (PK) | Unique ID per property per month |
| `month` | VARCHAR | YYYY-MM format |
| `owner_full_name` | VARCHAR(512) | Extracted from notice |
| `address` | VARCHAR | Property address |
| `r_number` | VARCHAR | WCAD R-Number (e.g., R378555) |
| `assessed_value` | FLOAT | WCAD assessed market value |
| `instrument_number` | VARCHAR | County clerk instrument number |
| `sale_date` | DATE | Auction date |
| `original_loan_amount` | FLOAT | From the Deed of Trust |
| `loan_origination_date` | DATE | When the loan was made |
| `loan_type` | VARCHAR | FHA / Conventional / VA / USDA |
| `lender` | VARCHAR | Original lender |
| `servicer` | VARCHAR | Current loan servicer |
| `trustee` | VARCHAR | Trustee conducting the sale |
| `is_purchase_money` | BOOLEAN | Section 27 DoT flag |
| `has_hoa_rider` | BOOLEAN | PUD/HOA rider flag |

### `loan_estimates` — Amortization results

| Column | Type | Description |
|---|---|---|
| `entry_no` | VARCHAR (FK) | Links to `properties` |
| `est_remaining_balance` | FLOAT | Estimated unpaid principal |
| `est_pct_paid_down` | FLOAT | Percentage of original loan repaid |
| `monthly_payment` | FLOAT | Calculated monthly payment |
| `filter_flag` | VARCHAR | `GOOD_CANDIDATE` or `LOW_PAYDOWN` |
| `annual_rate_used` | FLOAT | Historical interest rate used |
| `months_elapsed` | INTEGER | Months since origination |

### `step_results` — Per-step audit trail

| Column | Type | Description |
|---|---|---|
| `entry_no` | VARCHAR (FK) | Links to `properties` |
| `step_name` | VARCHAR | e.g., `step1_trustee_notice` |
| `status` | VARCHAR | `ok`, `error`, `skipped` |
| `payload` | JSON | Raw extracted data for that step |
| `comment` | TEXT | Error messages or manual notes |
| `fetched_at` | TIMESTAMP | When the step ran |

---

## 7. Data Sources Used

| Source | URL | Access Method | Used For |
|---|---|---|---|
| Williamson County Clerk | `apps.wilco.org/countyclerk/trustee_sales/` | HTTP scraping | Notice PDF download |
| WCAD Property Search | `search.wcad.org` | Playwright (headless browser) | R-Number, assessed value |
| WCAD Documents | `documents.wcad.org/{year}/{r_number}.pdf` | Direct HTTP | Appraisal notice PDF |
| County Tax Office | `tax.wilcotx.gov` | Manual (bot-blocked) | Tax delinquency status |
| County Records (OORP) | `williamson.tx.publicsearch.us` | Session-based HTTP | Deed of Trust PDF |

---

## 8. Key Engineering Decisions

### Why Playwright for WCAD?
WCAD's search portal is a Kendo UI JavaScript single-page application. Standard HTTP requests return an empty shell. Playwright launches a real headless Chromium browser that executes the JavaScript, waits for the data grid to render, and extracts the R-Number from the live DOM.

### Why PostgreSQL instead of SQLite?
Migrated from SQLite to PostgreSQL to support concurrent access from the FastAPI backend while pipeline steps write data, schema namespacing (`rkreality`) for multi-project database sharing, and production-grade reliability for long-running scraping jobs.

### Why the Two-Step Address Fallback in WCAD?
WCAD's search engine is strict about abbreviations. `17060 CONWAY SPGS CT` fails because `SPGS` is not indexed. Retrying with just `17060 CONWAY` is broad enough to find the property. This fallback recovers R-Numbers that would otherwise remain blank.

### Why Manual-Assist for Tax and Lien Checks?
County tax portals actively block automated scraping (robots.txt, CAPTCHA, bot detection). Rather than a fragile workaround, the pipeline assists the human operator — it generates the exact lookup URL and saves the manually-entered result, which is more robust than a scraper that breaks every few weeks.

### Why a `--force` Flag?
Pipeline steps are idempotent by default — they skip properties already processed. The `--force` flag surgically overwrites only the results for the specified step, without touching other steps or deleting core property records. This allows safe re-processing when parsing logic is improved.
