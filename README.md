# Real Estate Auction Pipeline (`real-auc`)

An automated due-diligence pipeline for Texas trustee sales. The pipeline automates the extraction, processing, and financial analysis of real estate foreclosure properties, currently supporting Williamson County, TX.

## Features

- **Automated Document Retrieval**: Downloads trustee-sale notices automatically.
- **Document Parsing & OCR**: Extracts relevant data from notices using `pdfplumber` and `pytesseract` (OCR).
- **Property Records Integration**: Interfaces with WCAD (Williamson Central Appraisal District) to pull property details.
- **Tax Checking**: Checks current tax status and obligations.
- **Deed of Trust (DOT) Parsing**: Extracts original loan amounts and dates from Deed of Trust documents.
- **Lien Checking**: Automates checking for existing liens.
- **Amortization & Financial Analysis**: Estimates remaining loan balances based on origination dates, historical interest rates, and loan terms to evaluate if a property is a good candidate.
- **Export**: Generates comprehensive Excel and CSV reports with the results of the due-diligence pipeline.
- **RK-Reality Web Dashboard**: A modern React and FastAPI web application to view, manage, and trigger pipeline steps interactively.

## Prerequisites

- Python 3.10+
- **PostgreSQL**: The application uses a local PostgreSQL database (`fno_oms`) and schema (`rkreality`).
- **Node.js**: Required to run the React frontend.
- **Tesseract OCR**: Required for parsing images in PDFs. 
  - macOS: `brew install tesseract`
  - Linux: `sudo apt-get install tesseract-ocr`
- **Poppler**: Required by `pdf2image`.
  - macOS: `brew install poppler`
  - Linux: `sudo apt-get install poppler-utils`

## Installation

1. Clone the repository and navigate to the project directory:
   ```bash
   cd real-auc
   ```

2. Create a virtual environment and activate it:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows use `.venv\Scripts\activate`
   ```

3. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

4. Initialize the PostgreSQL database:
   Create a database named `fno_oms` and a user `fnooms` with password `fnooms123`, then run:
   ```bash
   alembic upgrade head
   ```

5. Install Frontend Dependencies:
   ```bash
   cd RK-Reality/frontend
   npm install
   ```

## Configuration

The project is configured via `config.yaml`. Here you can adjust:
- **County definitions**: URLs and settings for different counties (currently Williamson County).
- **Amortization settings**: Loan terms and threshold rules (e.g., % paid down to be considered a good candidate).
- **Interest rates**: Assumed 30-year fixed rates by origination year, used for estimating loan balances.
- **Logging**: Set the log level and format.

## Usage

The pipeline can be operated via the RK-Reality Web Interface or the Command Line Interface (CLI). All outputs and intermediate files are saved in the local `workspace/` directory, and data is stored in the PostgreSQL `fno_oms` database under the `rkreality` schema.

### Running the Web Interface

1. **Start the Backend API:**
   ```bash
   source .venv/bin/activate
   python3 RK-Reality/backend/main.py
   ```
2. **Start the Frontend UI:**
   ```bash
   cd RK-Reality/frontend
   npm run dev
   ```
   Open your browser to `http://localhost:5173/`.

### CLI Commands

You can run the CLI using:
```bash
python3 auction_pipeline/cli.py run --help
```

### Main Commands

- **Run the entire pipeline for a specific month:**
  ```bash
  python3 -m auction_pipeline.cli run --month 2026-09
  ```

- **Download notices (Step 0):**
  ```bash
  python3 -m auction_pipeline.cli download --month 2026-09
  ```

- **Run a specific step:**
  ```bash
  python3 -m auction_pipeline.cli run-step --step 1 --month 2026-09
  ```

- **Manual Entry:**
  Record a manually-looked-up result for steps that require manual intervention (e.g., Step 3 for Taxes, Step 5 for Liens).
  ```bash
  python3 -m auction_pipeline.cli manual-entry --step 3 --entry-no 123 --status PAID --amount 0.0
  ```

- **Export Results:**
  Export the processed data to an Excel or CSV file.
  ```bash
  python3 -m auction_pipeline.cli export --month 2026-09 --output out.xlsx --csv
  ```

## Pipeline Steps

The pipeline is broken down into 8 steps (0-7):
- **Step 0 (`download`)**: Download trustee-sale notices for a given month.
- **Step 1 (`parse_notice`)**: Parse notices and extract basic information.
- **Step 2 (`wcad`)**: Query WCAD (Appraisal District) for property details.
- **Step 3 (`tax`)**: Check county tax office for outstanding taxes.
- **Step 4 (`dot`)**: Extract origination data from the Deed of Trust.
- **Step 5 (`liens`)**: Check for additional liens on the property.
- **Step 6 (`amortize`)**: Calculate amortization and identify good investment candidates.
- **Step 7 (`export`)**: Export all findings to a spreadsheet (Excel/CSV).
