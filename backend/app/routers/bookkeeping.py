from __future__ import annotations

import asyncio

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from fastapi.responses import Response

from .. import store
from ..dependencies import get_current_user
from ..models import CamelModel, Transaction, User
from ..services.import_jobs import create_job, get_job, run_import_job
from ..services.pdf_generator import generate_pnl_pdf
from ..services.pnl import compute_pnl
from ..utils.csv_parser import parse_transactions_csv
from ..utils.rate_limit import check_rate_limit

router = APIRouter(prefix="/api/bookkeeping", tags=["bookkeeping"])

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB (SKILL.md §16 Rule 10)
ALLOWED_TYPES = {"text/csv", "application/vnd.ms-excel", "text/plain", ""}


class CategoryPatch(CamelModel):
    category: str
    subcategory: str | None = None


@router.get("/transactions", response_model=list[Transaction])
async def list_transactions(user: User = Depends(get_current_user)):
    return store.list_transactions(user.id)


@router.patch("/transactions/{transaction_id}/category", response_model=Transaction)
async def patch_transaction_category(
    transaction_id: str,
    body: CategoryPatch,
    user: User = Depends(get_current_user),
):
    from ..services.playbook import observe_correction

    txn = next((t for t in store.list_transactions(user.id) if t.id == transaction_id), None)
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    old_category = txn.category or ""
    patch: dict = {"category": body.category}
    if body.subcategory is not None:
        patch["subcategory"] = body.subcategory
    updated = store.update_transaction(user.id, transaction_id, patch)
    if not updated:
        raise HTTPException(status_code=404, detail="Transaction not found")
    try:
        observe_correction(user.id, transaction_id, txn.description, old_category, body.category)
    except Exception:
        pass
    return updated


@router.post("/upload")
async def upload_csv(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    # Rate limit AI-heavy endpoint (SKILL.md §16 Rule 5).
    rl = check_rate_limit(f"ai:categorize:{user.id}", max_requests=20, window_seconds=3600)
    if not rl.allowed:
        raise HTTPException(status_code=429, detail="Rate limit reached. Try again shortly.")

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only CSV files are accepted")

    raw = await file.read()
    if len(raw) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 5MB)")

    text = raw.decode("utf-8", errors="replace")
    parsed = parse_transactions_csv(text)
    if not parsed.rows:
        raise HTTPException(status_code=400, detail={"error": "No valid rows found", "details": parsed.errors[:10]})
    if len(parsed.rows) > 10000:
        raise HTTPException(status_code=400, detail="File must have 2–10,000 rows")

    job_id = create_job(user.id)
    background_tasks.add_task(run_import_job, job_id, user.id, user.currency, parsed.rows)
    return {
        "ok": True,
        "status": "processing",
        "jobId": job_id,
        "rowsParsed": len(parsed.rows),
        "parseWarnings": parsed.errors[:10],
    }


@router.get("/upload/{job_id}")
async def upload_status(job_id: str, user: User = Depends(get_current_user)):
    job = get_job(job_id, user.id)
    if not job:
        raise HTTPException(status_code=404, detail="Import job not found")
    return job


@router.get("/pnl")
async def get_pnl(user: User = Depends(get_current_user)):
    pnl = compute_pnl(store.list_transactions(user.id))
    return {
        "totalIncome": pnl.total_income,
        "totalExpenses": pnl.total_expenses,
        "netProfit": pnl.net_profit,
        "profitMargin": pnl.profit_margin,
        "incomeByCategory": pnl.income_by_category,
        "expenseByCategory": pnl.expense_by_category,
        "deductibleExpenses": pnl.deductible_expenses,
        "count": pnl.count,
    }


@router.get("/report")
async def download_report(user: User = Depends(get_current_user)):
    txns = store.list_transactions(user.id)
    if not txns:
        raise HTTPException(status_code=400, detail="No transactions to report on")
    dates = sorted(t.date for t in txns)
    pnl = compute_pnl(txns)
    pdf = await asyncio.to_thread(generate_pnl_pdf, user, pnl, dates[0], dates[-1])
    filename = f"kora-pnl-{dates[0]}_to_{dates[-1]}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
