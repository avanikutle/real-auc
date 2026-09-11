"""RK-Reality FastAPI Backend - Full Featured"""
from fastapi import FastAPI, Depends, HTTPException, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
import uvicorn, sys, os, subprocess, json, csv, io, asyncio
from pathlib import Path
from pydantic import BaseModel
from typing import Optional
from datetime import date

repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))

from auction_pipeline.db.models import Property, StepResult, LoanEstimate
from auction_pipeline.db.session import get_session
from auction_pipeline import workspace_path

app = FastAPI(title="RK-Reality API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory step log store
step_logs: dict[str, list[str]] = {}

def get_db():
    db = get_session()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

@app.get("/api/properties")
def get_properties(month: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Property)
    if month:
        q = q.filter(Property.month == month)
    props = q.order_by(Property.entry_no).all()
    result = []
    for p in props:
        le = db.query(LoanEstimate).filter(LoanEstimate.entry_no == p.entry_no).first()
        result.append({
            "entry_no": p.entry_no,
            "month": p.month,
            "county": p.county,
            "address": p.address,
            "owner_full_name": p.owner_full_name,
            "r_number": p.r_number,
            "original_loan_amount": p.original_loan_amount,
            "loan_origination_date": str(p.loan_origination_date) if p.loan_origination_date else None,
            "sale_date": str(p.sale_date) if p.sale_date else None,
            "lender": p.lender,
            "servicer": p.servicer,
            "trustee": p.trustee,
            "instrument_number": p.instrument_number,
            "legal_description": p.legal_description,
            "source_file_name": p.source_file_name,
            "is_purchase_money": p.is_purchase_money,
            "has_hoa_rider": p.has_hoa_rider,
            "status": p.status,
            "filter_flag": le.filter_flag if le else None,
            "est_remaining_balance": le.est_remaining_balance if le else None,
            "est_pct_paid_down": le.est_pct_paid_down if le else None,
        })
    return result


@app.get("/api/properties/{entry_no}")
def get_property(entry_no: str, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.entry_no == entry_no).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    step_results = db.query(StepResult).filter(StepResult.entry_no == entry_no).all()
    le = db.query(LoanEstimate).filter(LoanEstimate.entry_no == entry_no).first()
    return {
        "entry_no": prop.entry_no,
        "month": prop.month,
        "county": prop.county,
        "address": prop.address,
        "owner_full_name": prop.owner_full_name,
        "r_number": prop.r_number,
        "original_loan_amount": prop.original_loan_amount,
        "loan_origination_date": str(prop.loan_origination_date) if prop.loan_origination_date else None,
        "sale_date": str(prop.sale_date) if prop.sale_date else None,
        "lender": prop.lender,
        "servicer": prop.servicer,
        "trustee": prop.trustee,
        "instrument_number": prop.instrument_number,
        "legal_description": prop.legal_description,
        "source_file_name": prop.source_file_name,
        "is_purchase_money": prop.is_purchase_money,
        "has_hoa_rider": prop.has_hoa_rider,
        "status": prop.status,
        "loan_estimate": {
            "months_elapsed": le.months_elapsed,
            "assumed_rate": le.assumed_rate,
            "est_monthly_payment": le.est_monthly_payment,
            "est_principal_paid": le.est_principal_paid,
            "est_interest_paid": le.est_interest_paid,
            "est_remaining_balance": le.est_remaining_balance,
            "est_pct_paid_down": le.est_pct_paid_down,
            "filter_flag": le.filter_flag,
        } if le else None,
        "steps": {sr.step_name: sr.extracted_json for sr in step_results},
    }


class PropertyUpdate(BaseModel):
    owner_full_name: Optional[str] = None
    r_number: Optional[str] = None
    address: Optional[str] = None
    original_loan_amount: Optional[float] = None


@app.put("/api/properties/{entry_no}")
def update_property(entry_no: str, data: PropertyUpdate, db: Session = Depends(get_db)):
    prop = db.query(Property).filter(Property.entry_no == entry_no).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    for field, val in data.dict(exclude_none=True).items():
        setattr(prop, field, val)
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

@app.get("/api/months")
def get_months(db: Session = Depends(get_db)):
    rows = db.execute(text("SELECT DISTINCT month FROM properties ORDER BY month DESC")).fetchall()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Pipeline step execution
# ---------------------------------------------------------------------------

STEP_NAMES = {
    0: "Download Notices",
    1: "Parse Trustee Notice",
    2: "WCAD Lookup",
    3: "Tax Check",
    4: "Deed of Trust",
    5: "Lien Check",
    6: "Amortize",
    7: "Export",
}

_running_steps: dict[str, subprocess.Popen] = {}

def _run_pipeline_step(task_id: str, step: int, month: str, county: str, force: bool):
    venv_python = str(repo_root / ".venv" / "bin" / "python3")
    if not Path(venv_python).exists():
        venv_python = sys.executable

    if step == 0:
        cmd = [venv_python, "-m", "auction_pipeline.cli", "download",
               "--month", month, "--county", county]
        if force:
            cmd.append("--force")
    else:
        cmd = [venv_python, "-m", "auction_pipeline.cli", "run-step",
               "--step", str(step), "--month", month, "--county", county]
        if force:
            cmd.append("--force")

    step_logs[task_id] = [f"▶ Starting step {step} ({STEP_NAMES.get(step, '')}) for {month}...\n"]
    
    try:
        proc = subprocess.Popen(
            cmd, cwd=str(repo_root),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        _running_steps[task_id] = proc
        for line in proc.stdout:
            step_logs[task_id].append(line)
        proc.wait()
        status = "✅ Completed" if proc.returncode == 0 else f"❌ Failed (exit {proc.returncode})"
        step_logs[task_id].append(f"\n{status}\n")
    except Exception as e:
        step_logs[task_id].append(f"\n❌ Error: {e}\n")
    finally:
        _running_steps.pop(task_id, None)


@app.post("/api/pipeline/run-step")
def trigger_step(
    background_tasks: BackgroundTasks,
    step: int = Body(...),
    month: str = Body(...),
    county: str = Body("williamson"),
    force: bool = Body(False),
):
    task_id = f"step{step}_{month}"
    if task_id in _running_steps:
        return {"status": "already_running", "task_id": task_id}
    step_logs[task_id] = []
    background_tasks.add_task(_run_pipeline_step, task_id, step, month, county, force)
    return {"status": "started", "task_id": task_id}


@app.get("/api/pipeline/logs/{task_id}")
def get_logs(task_id: str):
    logs = step_logs.get(task_id, [])
    is_running = task_id in _running_steps
    return {"logs": logs, "running": is_running}


@app.get("/api/pipeline/status/{month}")
def pipeline_status(month: str, db: Session = Depends(get_db)):
    """Return count of properties at each step for a given month."""
    rows = db.execute(
        text("SELECT status, COUNT(*) FROM properties WHERE month=:m GROUP BY status"),
        {"m": month}
    ).fetchall()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

@app.get("/api/documents/{month}/{entry_no}/{filename}")
def get_document(month: str, entry_no: str, filename: str):
    ALLOWED = {"trustee_notice.pdf", "wcad_appraisal.pdf"}
    if filename not in ALLOWED:
        raise HTTPException(status_code=400, detail="Invalid document")
    path = workspace_path(month, "properties", entry_no, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    return FileResponse(str(path), media_type="application/pdf")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@app.get("/api/export/csv")
def export_csv(month: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Property)
    if month:
        q = q.filter(Property.month == month)
    props = q.order_by(Property.entry_no).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Entry No", "Month", "County", "Owner Full Name", "Address",
        "R-Number", "Instrument No", "Sale Date", "Original Loan Amount",
        "Loan Origination Date", "Lender", "Servicer", "Trustee",
        "Is Purchase Money", "Has HOA Rider", "Est Remaining Balance",
        "% Paid Down", "Filter Flag", "Status"
    ])
    for p in props:
        le = db.query(LoanEstimate).filter(LoanEstimate.entry_no == p.entry_no).first()
        writer.writerow([
            p.entry_no, p.month, p.county, p.owner_full_name, p.address,
            p.r_number, p.instrument_number, p.sale_date, p.original_loan_amount,
            p.loan_origination_date, p.lender, p.servicer, p.trustee,
            p.is_purchase_money, p.has_hoa_rider,
            le.est_remaining_balance if le else "",
            f"{le.est_pct_paid_down:.1%}" if le and le.est_pct_paid_down else "",
            le.filter_flag if le else "",
            p.status
        ])
    output.seek(0)
    fname = f"rkreality_{month or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )


if __name__ == "__main__":
    log_dir = repo_root / "logs" / "backend"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "api.log"

    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["handlers"]["file"] = {
        "class": "logging.FileHandler",
        "filename": str(log_file),
        "formatter": "default",
    }
    log_config["loggers"]["uvicorn"]["handlers"] = ["default", "file"]
    log_config["loggers"]["uvicorn.access"]["handlers"] = ["access", "file"]

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_config=log_config)
